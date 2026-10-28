"""GapGPT credentials never fall back to another provider's key."""

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from pvb.extraction.openrouter.settings import ROOT, OpenRouterSettings
from pvb.extraction.openrouter.settings import load_settings as load_base

Rate = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class GapGPTSettings(OpenRouterSettings):
    model: str = "gpt-5.6-terra"
    base_url: str = "https://api.gapgpt.app/v1"
    concurrency: Annotated[int, Field(ge=1, le=100)] = 2
    timeout_seconds: Annotated[float, Field(gt=0, le=3600, allow_inf_nan=False)] = 180.0
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "medium"
    context_limit_tokens: Annotated[int, Field(ge=1)] = 32768
    input_usd_per_million: Rate | None = None
    output_usd_per_million: Rate | None = None
    request_usd: Rate | None = None
    pricing_source: str | None = None

    @property
    def provider(self) -> str:
        return "gapgpt"

    @property
    def run_prefix(self) -> str:
        return "pvb-gap-"

    def issues(self) -> list[str]:
        problems = []
        if not self.credential_configured:
            problems.append(
                "GapGPT API key is not configured. Set GAPGPT_API_KEY in the root .env file."
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", self.model) or ".." in self.model:
            problems.append(
                "Set GAPGPT_MODEL to an exact model identifier from the GapGPT catalog."
            )
        if self.base_url != "https://api.gapgpt.app/v1":
            problems.append("GAPGPT_BASE_URL must be https://api.gapgpt.app/v1.")
        return problems


def load_settings(root: Path = ROOT, *, environ: dict[str, str] | None = None) -> GapGPTSettings:
    return load_base(
        root,
        environ=environ,
        settings_class=GapGPTSettings,
        field_overrides={
            "GAPGPT_API_KEY": "credential",
            "GAPGPT_MODEL": "model",
            "GAPGPT_BASE_URL": "base_url",
            "GAPGPT_CONCURRENCY": "concurrency",
            "GAPGPT_TIMEOUT_SECONDS": "timeout_seconds",
            "GAPGPT_REASONING_EFFORT": "reasoning_effort",
            "GAPGPT_CONTEXT_LIMIT_TOKENS": "context_limit_tokens",
            "GAPGPT_INPUT_USD_PER_MILLION": "input_usd_per_million",
            "GAPGPT_OUTPUT_USD_PER_MILLION": "output_usd_per_million",
            "GAPGPT_REQUEST_USD": "request_usd",
            "GAPGPT_PRICING_SOURCE": "pricing_source",
        },
    )
