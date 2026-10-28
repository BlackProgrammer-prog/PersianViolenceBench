"""Read root .env without mutating process state or exposing credentials."""

import os
import re
from pathlib import Path
from typing import Annotated

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

ROOT = Path(__file__).resolve().parents[4]


class ConfigurationError(ValueError):
    """Safe, actionable configuration error with no input values."""


class OpenRouterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    credential: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    model: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    concurrency: Annotated[int, Field(ge=1, le=100)] = 5
    max_retries: Annotated[int, Field(ge=0, le=10)] = 3
    timeout_seconds: Annotated[float, Field(gt=0, le=3600, allow_inf_nan=False)] = 90.0
    max_cost_usd: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 2.0
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] = 0.0
    max_output_tokens: Annotated[int, Field(ge=1, le=100000)] = 600
    reasoning_enabled: bool | None = None

    @property
    def provider(self) -> str:
        return "openrouter"

    @property
    def run_prefix(self) -> str:
        return "pvb-or-"

    @property
    def credential_configured(self) -> bool:
        key = self.credential.get_secret_value().strip()
        return (
            bool(key)
            and re.search(
                r"paste|placeholder|your[_ -]|changeme|<|>|\$\{|[\r\n]", key, re.IGNORECASE
            )
            is None
        )

    def issues(self) -> list[str]:
        problems = []
        if not self.credential_configured:
            problems.append(
                "OpenRouter API key is not configured. Set OPENROUTER_API_KEY in the root .env file."
            )
        if (
            not self.model
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+", self.model)
            or self.model.startswith("openrouter/")
        ):
            problems.append(
                "Set OPENROUTER_MODEL to an exact author/model identifier; automatic routers are not supported."
            )
        # This dedicated backend never redirects credentials to a different service.
        if self.base_url != "https://openrouter.ai/api/v1":
            problems.append(
                "OPENROUTER_BASE_URL must be https://openrouter.ai/api/v1; endpoint substitution is not supported."
            )
        return problems

    def require_ready(self) -> None:
        if self.issues():
            raise ConfigurationError("\n".join(self.issues()) + "\nEdit: " + str(ROOT / ".env"))

    def public(self) -> dict:
        return self.model_dump(exclude={"credential"})

    def redact(self, value: str) -> str:
        key = self.credential.get_secret_value()
        if key:
            value = value.replace(key, "[REDACTED]")
        return re.sub(r"sk-or-[A-Za-z0-9_-]+", "[REDACTED]", value)


def load_settings(
    root: Path = ROOT,
    *,
    environ: dict[str, str] | None = None,
    settings_class: type[OpenRouterSettings] = OpenRouterSettings,
    field_overrides: dict[str, str] | None = None,
) -> OpenRouterSettings:
    # Environment deliberately takes precedence, but no export is needed for .env.
    values = dict(dotenv_values(root / ".env", interpolate=False))
    values.update(os.environ if environ is None else environ)
    fields = {
        "OPENROUTER_API_KEY": "credential",
        "OPENROUTER_MODEL": "model",
        "OPENROUTER_BASE_URL": "base_url",
        "PVB_API_CONCURRENCY": "concurrency",
        "PVB_API_MAX_RETRIES": "max_retries",
        "PVB_API_TIMEOUT_SECONDS": "timeout_seconds",
        "PVB_API_MAX_COST_USD": "max_cost_usd",
        "PVB_CLASSIFICATION_TEMPERATURE": "temperature",
        "PVB_CLASSIFICATION_MAX_OUTPUT_TOKENS": "max_output_tokens",
        "PVB_CLASSIFICATION_REASONING_ENABLED": "reasoning_enabled",
    }
    if field_overrides is not None:
        fields = {key: dest for key, dest in fields.items() if not key.startswith("OPENROUTER_")}
        fields.pop("PVB_CLASSIFICATION_REASONING_ENABLED", None)
        fields.update(field_overrides)
    try:
        settings = settings_class(
            **{
                dest: values[key]
                for key, dest in fields.items()
                if key in values and values[key] is not None and values[key] != ""
            }
        )
    except ValidationError as exc:
        names = ", ".join(
            sorted({".".join(map(str, error["loc"])) for error in exc.errors(include_input=False)})
        )
        raise ConfigurationError(
            f"Invalid .env setting(s): {names}. Check values in {root / '.env'}."
        ) from None
    # Prevent a credential reused accidentally in public settings from being persisted.
    secret = settings.credential.get_secret_value()
    if secret and any(secret in str(value) for value in settings.public().values()):
        raise ConfigurationError(
            "Credential appears in a non-secret configuration field. Correct the root .env file."
        )
    return settings
