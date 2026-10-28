"""Translation-specific settings; credentials are excluded from public metadata."""

import os
import re
from pathlib import Path
from typing import Annotated, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

ROOT = Path(__file__).resolve().parents[3]
INPUT_DEFAULT = (
    "runs/gapgpt/pvb-gap-621566036e034163884561aaf26d655d/all54_categorized_samples.jsonl"
)


def credential_configured(secret: SecretStr) -> bool:
    value = secret.get_secret_value().strip()
    return (
        bool(value)
        and re.search(r"placeholder|paste|your[_ -]|changeme|<|>|\$\{|[\r\n]", value, re.IGNORECASE)
        is None
    )


class TranslationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    input: str = INPUT_DEFAULT
    output: str = "runs/translation"
    scope: Literal["all", "unsafe_violence"] = "all"
    source_language: Literal["en"] = "en"
    target_language: Literal["fa"] = "fa"
    llm_provider: Literal["gapgpt", "openrouter"] = "gapgpt"
    llm_model: str = "gpt-5.6-terra"
    llm_base_url: str = "https://api.gapgpt.app/v1"
    llm_credential_env: Literal["GAPGPT_API_KEY", "OPENROUTER_API_KEY"] = "GAPGPT_API_KEY"
    llm_credential: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    google_credential: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    google_edition: Literal["basic_v2"] = "basic_v2"
    google_model: Literal["nmt"] = "nmt"
    max_cost_usd: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 2.0

    def issues(self) -> dict[str, list[str]]:
        llm, google = [], []
        if not credential_configured(self.llm_credential):
            llm.append("Configure the key named by PVB_TRANSLATION_LLM_CREDENTIAL_ENV.")
        expected_url, expected_key = {
            "gapgpt": ("https://api.gapgpt.app/v1", "GAPGPT_API_KEY"),
            "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
        }[self.llm_provider]
        if self.llm_base_url != expected_url or self.llm_credential_env != expected_key:
            llm.append("Translation provider, base URL and credential variable must match.")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", self.llm_model)
            or ".." in self.llm_model
        ):
            llm.append("Set an exact PVB_TRANSLATION_LLM_MODEL.")
        if not credential_configured(self.google_credential):
            google.append("Set GOOGLE_TRANSLATE_API_KEY for Google Cloud Translation Basic v2.")
        return {"llm": llm, "google_translate": google}

    def public(self) -> dict:
        return self.model_dump()


def load_settings(root: Path = ROOT, *, environ=None) -> TranslationSettings:
    values = dict(dotenv_values(root / ".env", interpolate=False))
    values.update(os.environ if environ is None else environ)
    fields = {
        "PVB_TRANSLATION_INPUT": "input",
        "PVB_TRANSLATION_OUTPUT": "output",
        "PVB_TRANSLATION_SCOPE": "scope",
        "PVB_TRANSLATION_SOURCE_LANGUAGE": "source_language",
        "PVB_TRANSLATION_TARGET_LANGUAGE": "target_language",
        "PVB_TRANSLATION_LLM_PROVIDER": "llm_provider",
        "PVB_TRANSLATION_LLM_MODEL": "llm_model",
        "PVB_TRANSLATION_LLM_BASE_URL": "llm_base_url",
        "PVB_TRANSLATION_LLM_CREDENTIAL_ENV": "llm_credential_env",
        "PVB_GOOGLE_TRANSLATE_EDITION": "google_edition",
        "PVB_GOOGLE_TRANSLATE_MODEL": "google_model",
        "PVB_TRANSLATION_MAX_COST_USD": "max_cost_usd",
    }
    kwargs = {
        dest: values[key] for key, dest in fields.items() if values.get(key) not in (None, "")
    }
    credential_env = kwargs.get("llm_credential_env", "GAPGPT_API_KEY")
    kwargs["llm_credential"] = values.get(credential_env) or ""
    kwargs["google_credential"] = values.get("GOOGLE_TRANSLATE_API_KEY") or ""
    try:
        settings = TranslationSettings(**kwargs)
    except ValidationError as exc:
        names = ", ".join(sorted({str(e["loc"][0]) for e in exc.errors(include_input=False)}))
        raise ValueError("Invalid translation .env settings: " + names) from None
    for key in ("GAPGPT_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_TRANSLATE_API_KEY"):
        value = values.get(key)
        if value and any(value in str(v) for v in settings.public().values()):
            raise ValueError("Translation credential appears in a public configuration field.")
    return settings
