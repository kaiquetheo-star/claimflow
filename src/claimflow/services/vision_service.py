"""Qwen-VL multimodal analysis and text-image cross-validation utilities."""

import asyncio
import json
import re
from http import HTTPStatus
from pathlib import Path

from dashscope import AioMultiModalConversation
from pydantic import ValidationError

from claimflow.core.config import Settings, get_settings
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
Você é um perito em sinistros de seguros residenciais especializado em análise visual.
Analise a imagem fornecida e compare com o relato textual do segurado.

Suas tarefas:
1. Descrever o que vê na imagem: tipo de dano aparente, severidade visual e localização.
2. Comparar a imagem com o relato textual fornecido.
3. Identificar inconsistências entre texto e imagem.

Responda EXCLUSIVAMENTE com um objeto JSON válido (sem markdown) no formato:
{
  "detected_damage_type": "AGUA|FOGO|VENTO|OUTRO",
  "visual_severity": "baixa|media|alta|critica",
  "location_match": true,
  "description": "descrição detalhada em português",
  "inconsistencies": ["lista de inconsistências encontradas, ou array vazio"]
}
"""


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

    async def analyze_claim_image(self, image_path: str, context_text: str) -> dict:
        """Analyse a claim image and cross-validate it against the textual report.

        Args:
            image_path: Absolute or relative path to the image on local disk.
            context_text: Raw claim text used for cross-validation.

        Returns:
            Serialised :class:`ImageAnalysisResult` as a plain dict.

        Raises:
            VisionServiceError: On invalid image format, API failure, timeout, or
                unparseable model output.
        """
        path = Path(image_path)
        self._validate_image_path(path)

        log = logger
        image_ref = str(path.resolve())
        user_prompt = (
            f"Relato textual do sinistro:\n\n{context_text}\n\n"
            "Analise a imagem anexa e retorne o JSON solicitado."
        )
        messages = [
            {
                "role": "system",
                "content": [{"text": VISION_SYSTEM_PROMPT}],
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
                return self._return_mock_analysis(context_text, errors)
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
                return self._return_mock_analysis(context_text, errors)

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
                return self._return_mock_analysis(context_text, errors)

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

        return self._return_mock_analysis(context_text, errors)

    @staticmethod
    def build_mock_analysis(context_text: str) -> dict:
        """Return a realistic offline vision analysis simulating water damage."""
        text_lower = context_text.lower()
        inconsistencies = [
            "Texto relata incêndio/fogo, imagem mostra vazamento e infiltração de água.",
        ]
        if any(word in text_lower for word in ("chuva", "tempestade", "vendaval")):
            inconsistencies.append(
                "Relato menciona evento climático severo, mas imagem indica apenas dano por água."
            )
        return {
            "detected_damage_type": "AGUA",
            "visual_severity": "alta",
            "location_match": False,
            "description": (
                "Imagem mock: manchas extensas de umidade, piso encharcado e bolhas na pintura "
                "indicando vazamento de água."
            ),
            "inconsistencies": inconsistencies,
            "source": "mock",
        }

    def _return_mock_analysis(self, context_text: str, errors: list[str]) -> dict:
        """Log and return mock vision analysis after API failures."""
        logger.warning(
            "All Qwen-VL models failed; returning mock vision analysis",
            extra={"failed_models": errors},
        )
        return self.build_mock_analysis(context_text)

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
