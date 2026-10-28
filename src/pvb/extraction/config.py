from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import Field, model_validator

from pvb.schemas.annotation_runs import reject_secrets
from pvb.schemas.common import StrictModel


class LLMConfig(StrictModel):
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    endpoint: str | None = None
    credential_env: str = "PVB_LLM_API_KEY"
    prompt: str = "configs/prompts/violence_classifier_v1.txt"
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] = 0.0
    timeout: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 60.0
    retries: Annotated[int, Field(ge=0, le=10)] = 2
    requests_per_minute: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 30.0

    @model_validator(mode="after")
    def safe_endpoint(self):
        if self.endpoint:
            parsed = urlsplit(self.endpoint)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("endpoint must not embed credentials, query or fragment")
        return self


class DuplicateConfig(StrictModel):
    unicode_form: Literal["NFC", "NFKC", "NFD", "NFKD", "none"] = "NFKC"
    whitespace: bool = True
    casefold: bool = True


class ExtractionConfig(StrictModel):
    schema_version: Literal["1.0.0"]
    root: str = ".."
    input: str = "data/normalized/benchmark_samples.jsonl"
    taxonomy: str = "configs/taxonomy.yaml"
    output: str = "data/extracted"
    backend: Literal["rules", "llm"] = "rules"
    method_frozen: bool = False
    rules_version: Literal["rules-1.0.0"] = "rules-1.0.0"
    batch_size: Annotated[int, Field(ge=1, le=10000)] = 32
    concurrency: Annotated[int, Field(ge=1, le=100)] = 2
    duplicates: DuplicateConfig = Field(default_factory=DuplicateConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def load_config(path: Path):
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    reject_secrets(raw)
    config = ExtractionConfig.model_validate(raw)
    return config, (path.resolve().parent / config.root).resolve()
