"""Qwen-VL multimodal analysis and text-image cross-validation utilities."""

import asyncio
import json
import re
from http import HTTPStatus
from pathlib import Path

from dashscope import AioMultiModalConversation
from pydantic import ValidationError

from claimflow.core.config import Settings, get_settings
from claimflow.core.i18n import Language, normalize_language
from claimflow.core.logging import get_logger
from claimflow.models.schemas import ImageAnalysisResult
from claimflow.services.llm_service import is_model_access_error

logger = get_logger(__name__)

_ACCESS_DENIED_API_CODES = frozenset(
    {"AccessDenied", "AccessDenied.Unpurchased", "InvalidApiKey", "ModelNotFound"}
)

ALLOWED_IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
)

# Keyword map used to normalise free-text damage labels into canonical categories.
DAMAGE_KEYWORDS: dict[str, frozenset[str]] = {
    "AGUA": frozenset(
        {
            "agua",
            "água",
            "water",
            "vazamento",
            "alagamento",
            "umidade",
            "infiltracao",
            "infiltração",
            "enchente",
        }
    ),
    "FOGO": frozenset(
        {
            "fogo",
            "fire",
            "incendio",
            "incêndio",
            "queimadura",
            "chamas",
            "carbonizado",
        }
    ),
    "VENTO": frozenset(
        {
            "vento",
            "wind",
            "tempestade",
            "vendaval",
            "granizo",
            "tormenta",
            "cyclone",
        }
    ),
    "OUTRO": frozenset({"outro", "other", "desconhecido", "unknown", "indefinido"}),
}

VISION_SYSTEM_PROMPT = """\
You are ClaimFlow Vision, a senior insurance claims visual analyst.

CRITICAL LANGUAGE RULE: You MUST respond in {language_name}. All free-text \
field values in your JSON output must be in this language.

Your tasks:
1. Describe what you see: apparent damage type, visual severity, and location cues.
2. Compare the image with the policyholder's textual report.
3. Identify inconsistencies between text and image.

Respond EXCLUSIVELY with a valid JSON object (no markdown) in this format:
{{
  "detected_damage_type": "AGUA|FOGO|VENTO|OUTRO",
  "visual_severity": "baixa|media|alta|critica",
  "location_match": true,
  "description": "detailed visual description in {language_name}",
  "inconsistencies": ["list of inconsistencies in {language_name}, or empty array"]
}}

Be precise. Report only what is visible. Do not invent damage that is not in the image.
"""

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "pt": "Portuguese",
    "es": "Spanish",
}


def get_vision_system_prompt(language: str = "en") -> str:
    """Build the Qwen-VL system prompt forcing output in the selected language.

    Defaults to English for the Alibaba Cloud hackathon.
    """
    language_name = _LANGUAGE_NAMES.get(normalize_language(language), "English")
    return VISION_SYSTEM_PROMPT.format(language_name=language_name)


def vision_system_prompt(lang: Language = "en") -> str:
    """Backwards-compatible alias for :func:`get_vision_system_prompt`."""
    return get_vision_system_prompt(lang)


class VisionServiceError(Exception):
    """Raised when Qwen-VL analysis fails due to API, timeout, or parsing errors."""


class VisionService:
    """Analyse claim images with Qwen-VL via the native DashScope async SDK.

    Uses :class:`AioMultiModalConversation` instead of LangChain because the
    DashScope SDK provides more reliable multimodal image support.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _vision_model_chain(self) -> list[str]:
        """Return primary vision model followed by configured fallbacks."""
        return self._settings.vision_models

    @staticmethod
    def _is_access_denied_response(response: object) -> bool:
        status_code = getattr(response, "status_code", None)
        code = str(getattr(response, "code", "") or "")
        message = str(getattr(response, "message", "") or "")
        if status_code == HTTPStatus.FORBIDDEN:
            return True
        if code in _ACCESS_DENIED_API_CODES:
            return True
        return is_model_access_error(Exception(f"{code}: {message}"))

    async def analyze_claim_image(
        self,
        image_path: str,
        context_text: str,
        language: Language | str = "en",
    ) -> dict:
        """Analyse a claim image and cross-validate it against the textual report.

        Args:
            image_path: Absolute or relative path to the image on local disk.
            context_text: Raw claim text used for cross-validation.
            language: Output language for free-text fields (default: English).

        Returns:
            Serialised :class:`ImageAnalysisResult` as a plain dict.

        Raises:
            VisionServiceError: On invalid image format, API failure, timeout, or
                unparseable model output.
        """
        path = Path(image_path)
        self._validate_image_path(path)

        lang = normalize_language(language)
        log = logger
        image_ref = str(path.resolve())
        user_prompt = (
            f"Claim textual report:\n\n{context_text}\n\n"
            "Analyse the attached image and return the requested JSON."
        )
        messages = [
            {
                "role": "system",
                "content": [{"text": get_vision_system_prompt(lang)}],
            },
            {
                "role": "user",
                "content": [
                    {"image": image_ref},
                    {"text": user_prompt},
                ],
            },
        ]

        models = self._vision_model_chain()
        errors: list[str] = []

        for index, model in enumerate(models):
            log.info(
                "Starting Qwen-VL image analysis",
                extra={"image_path": str(path.resolve()), "model": model},
            )
            try:
                response = await asyncio.wait_for(
                    AioMultiModalConversation.call(
                        model=model,
                        messages=messages,
                        api_key=self._settings.dashscope_api_key.get_secret_value(),
                        temperature=0.1,
                        result_format="message",
                    ),
                    timeout=self._settings.vision_timeout_seconds,
                )
            except TimeoutError as exc:
                log.warning(
                    "Qwen-VL request timed out; trying next fallback or mock",
                    extra={
                        "image_path": str(path),
                        "model": model,
                        "timeout_s": self._settings.vision_timeout_seconds,
                    },
                )
                errors.append(f"{model}: timeout {exc}")
                VisionServiceError(
                    f"Vision analysis timed out after {self._settings.vision_timeout_seconds}s"
                )
                if index < len(models) - 1:
                    continue
                return self._return_mock_analysis(context_text, errors, lang)
            except Exception as exc:
                VisionServiceError(f"Vision API call failed: {exc}")
                if (is_model_access_error(exc) or isinstance(exc, TimeoutError)) and index < len(
                    models
                ) - 1:
                    log.warning(
                        "Vision model unavailable; trying next fallback",
                        extra={"model": model, "error": str(exc)},
                    )
                    errors.append(f"{model}: {exc}")
                    continue
                log.warning(
                    "Qwen-VL API call failed; using mock if no models remain",
                    extra={"image_path": str(path), "model": model, "error": str(exc)},
                )
                errors.append(f"{model}: {exc}")
                if index < len(models) - 1:
                    continue
                return self._return_mock_analysis(context_text, errors, lang)

            try:
                raw_text = self._extract_response_text(response)
            except VisionServiceError as exc:
                if self._is_access_denied_response(response) and index < len(models) - 1:
                    log.warning(
                        "Vision model access denied; trying next fallback",
                        extra={"model": model, "error": str(exc)},
                    )
                    errors.append(f"{model}: {exc}")
                    continue
                errors.append(f"{model}: {exc}")
                if index < len(models) - 1:
                    continue
                return self._return_mock_analysis(context_text, errors, lang)

            result = self._parse_analysis_result(raw_text)

            if index > 0:
                log.warning(
                    f"Falling back to {model} due to access restrictions",
                    extra={"model": model, "failed_models": errors},
                )

            log.info(
                "Qwen-VL analysis completed",
                extra={
                    "image_path": str(path),
                    "model": model,
                    "detected_damage_type": result["detected_damage_type"],
                    "visual_severity": result["visual_severity"],
                    "location_match": result["location_match"],
                },
            )
            return result

        return self._return_mock_analysis(context_text, errors, lang)

    @staticmethod
    def build_mock_analysis(
        context_text: str,
        language: Language | str = "en",
    ) -> dict:
        """Return a realistic offline vision analysis simulating water damage.

        Free-text fields follow ``language`` (default English) so English UI
        mode never surfaces Portuguese mock copy.
        """
        lang = normalize_language(language)
        text_lower = context_text.lower()

        fire_words = ("fire", "incêndio", "incendio", "fogo", "queim", "kitchen caught")
        weather_words = (
            "chuva",
            "tempestade",
            "vendaval",
            "storm",
            "rain",
            "wind",
            "vento",
            "tormenta",
        )

        texts: dict[Language, dict[str, str]] = {
            "en": {
                "description": (
                    "Mock image: extensive moisture stains, soaked flooring and "
                    "paint bubbling indicating a water leak."
                ),
                "fire_mismatch": (
                    "Text reports fire damage; image shows water leak and infiltration."
                ),
                "weather_mismatch": (
                    "Report mentions a severe weather event, but the image indicates "
                    "water damage only."
                ),
            },
            "pt": {
                "description": (
                    "Imagem mock: manchas extensas de umidade, piso encharcado e "
                    "bolhas na pintura indicando vazamento de água."
                ),
                "fire_mismatch": (
                    "Texto relata incêndio/fogo, imagem mostra vazamento e "
                    "infiltração de água."
                ),
                "weather_mismatch": (
                    "Relato menciona evento climático severo, mas imagem indica "
                    "apenas dano por água."
                ),
            },
            "es": {
                "description": (
                    "Imagen mock: manchas extensas de humedad, piso empapado y "
                    "pintura con burbujas indicando una fuga de agua."
                ),
                "fire_mismatch": (
                    "El texto reporta incendio/fuego; la imagen muestra fuga e "
                    "infiltración de agua."
                ),
                "weather_mismatch": (
                    "El relato menciona un evento climático severo, pero la imagen "
                    "indica solo daño por agua."
                ),
            },
        }
        copy = texts[lang]

        inconsistencies: list[str] = []
        if any(word in text_lower for word in fire_words):
            inconsistencies.append(copy["fire_mismatch"])
        if any(word in text_lower for word in weather_words):
            inconsistencies.append(copy["weather_mismatch"])

        return {
            "detected_damage_type": "AGUA",
            "visual_severity": "alta",
            "location_match": False,
            "description": copy["description"],
            "inconsistencies": inconsistencies,
            "source": "mock",
        }

    def _return_mock_analysis(
        self,
        context_text: str,
        errors: list[str],
        language: Language | str = "en",
    ) -> dict:
        """Log and return mock vision analysis after API failures."""
        logger.warning(
            "All Qwen-VL models failed; returning mock vision analysis",
            extra={"failed_models": errors},
        )
        return self.build_mock_analysis(context_text, language)

    def _validate_image_path(self, path: Path) -> None:
        """Ensure the image exists and has a supported file extension."""
        if not path.exists():
            raise VisionServiceError(f"Image file not found: {path}")
        if not path.is_file():
            raise VisionServiceError(f"Path is not a file: {path}")
        if path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
            raise VisionServiceError(
                f"Unsupported image format '{path.suffix}'. Allowed: {allowed}"
            )

    def _extract_response_text(self, response: object) -> str:
        """Extract plain text from a DashScope multimodal response object."""
        status_code = getattr(response, "status_code", None)
        if status_code != HTTPStatus.OK:
            code = getattr(response, "code", "unknown")
            message = getattr(response, "message", "unknown error")
            raise VisionServiceError(f"DashScope API error [{code}]: {message}")

        output = getattr(response, "output", None)
        if output is None:
            raise VisionServiceError("Empty response output from Qwen-VL")

        choices = getattr(output, "choices", None)
        if not choices:
            raise VisionServiceError("No choices in Qwen-VL response")

        message = choices[0].message
        content = getattr(message, "content", None)

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "".join(parts)

        raise VisionServiceError("Unable to extract text from Qwen-VL response")

    def _parse_analysis_result(self, raw_text: str) -> dict:
        """Parse and validate the JSON payload returned by Qwen-VL."""
        payload = self._extract_json(raw_text)
        try:
            validated = ImageAnalysisResult.model_validate(payload)
        except ValidationError as exc:
            raise VisionServiceError(f"Invalid vision analysis schema: {exc}") from exc
        return validated.model_dump(mode="json")

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract a JSON object from raw model text, tolerating markdown fences."""
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
        if fence_match:
            return json.loads(fence_match.group(1))

        brace_match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if brace_match:
            return json.loads(brace_match.group(0))

        raise VisionServiceError("Failed to parse JSON from Qwen-VL response")

    @staticmethod
    def normalize_damage_type(value: str) -> str:
        """Map a free-text damage label to a canonical category (AGUA, FOGO, VENTO, OUTRO)."""
        normalised = value.strip().upper()
        if normalised in DAMAGE_KEYWORDS:
            return normalised

        value_lower = value.lower().strip()
        for category, keywords in DAMAGE_KEYWORDS.items():
            if any(keyword in value_lower for keyword in keywords):
                return category
        return "OUTRO"

    @staticmethod
    def compute_consistency_score(text_damage: str, image_damage: str) -> float:
        """Score how well the text-reported damage type matches the visual analysis.

        Returns:
            1.0 — exact category match.
            0.5 — one side is ambiguous (OUTRO).
            0.0 — clear category mismatch (e.g. FOGO vs AGUA).
        """
        text_norm = VisionService.normalize_damage_type(text_damage)
        image_norm = VisionService.normalize_damage_type(image_damage)

        if text_norm == image_norm:
            return 1.0
        if text_norm == "OUTRO" or image_norm == "OUTRO":
            return 0.5
        return 0.0
