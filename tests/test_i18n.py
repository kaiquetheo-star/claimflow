"""Unit tests for claimflow.core.i18n."""

from __future__ import annotations

from claimflow.core.i18n import (
    DEFAULT_LANGUAGE,
    TRANSLATIONS,
    get_available_languages,
    get_request_language,
    llm_output_instruction,
    normalize_language,
    set_request_language,
    t,
)


def test_default_language_is_english() -> None:
    assert DEFAULT_LANGUAGE == "en"
    assert normalize_language(None) == "en"
    assert normalize_language("fr") == "en"
    assert "English" in t("app_title") or "Claimflow" in t("app_title")


def test_normalize_language_accepts_bcp47() -> None:
    assert normalize_language("pt-BR") == "pt"
    assert normalize_language("es-MX") == "es"
    assert normalize_language("EN") == "en"


def test_translations_have_parity() -> None:
    en_keys = set(TRANSLATIONS["en"])
    assert en_keys == set(TRANSLATIONS["pt"])
    assert en_keys == set(TRANSLATIONS["es"])
    assert "submit_button" in en_keys
    assert "language_selector" in en_keys


def test_t_falls_back_and_formats() -> None:
    assert t("submit_button", "en") != t("submit_button", "pt")
    assert "API" in t("api_error", "en", "boom") or "boom" in t("api_error", "en", "boom")
    assert t("missing_key_xyz") == "missing_key_xyz"


def test_available_languages() -> None:
    codes = [code for code, _label in get_available_languages()]
    assert codes == ["en", "pt", "es"]


def test_request_language_context() -> None:
    set_request_language("en")
    assert get_request_language() == "en"
    set_request_language("es")
    assert get_request_language() == "es"
    set_request_language("en")


def test_llm_output_instruction_mentions_language() -> None:
    en = llm_output_instruction("en")
    pt = llm_output_instruction("pt")
    assert "English" in en
    assert "Portuguese" in pt
    assert en != pt


def test_claim_submission_request_defaults_language_to_english() -> None:
    from claimflow.models.schemas import ClaimSubmissionRequest

    req = ClaimSubmissionRequest(claim_id="CLM-1", raw_input_text="Storm damage today")
    assert req.language == "en"


def test_claim_submission_request_normalizes_language() -> None:
    from claimflow.models.schemas import ClaimSubmissionRequest

    req = ClaimSubmissionRequest(
        claim_id="CLM-1",
        raw_input_text="Storm damage today",
        language="PT-BR",  # type: ignore[arg-type]
    )
    assert req.language == "pt"
