"""Auditable execution metadata without credentials."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .annotations import Method, Text, utc_timestamp
from .common import StrictModel
from .samples import SHA256


def reject_secrets(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if re.search(
                r"api.?key|secret|password|authorization|access.?token", key, re.IGNORECASE
            ):
                raise ValueError("secret-like configuration key forbidden")
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)


class AnnotationRun(StrictModel):
    run_id: Text
    schema_version: Literal["1.0.0"] = "1.0.0"
    taxonomy_version: Literal["1.0.0"] = "1.0.0"
    method: Method
    model_identifier: str | None = None
    model_version: str | None = None
    provider: str | None = None
    prompt_version: str | None = None
    configuration: dict[str, JsonValue]
    input_dataset_fingerprint: SHA256
    started_at: str
    completed_at: str | None = None
    status: Literal["running", "completed", "partial", "failed"]
    sample_count: Annotated[int, Field(ge=0)]
    success_count: Annotated[int, Field(ge=0)] = 0
    failure_count: Annotated[int, Field(ge=0)] = 0
    abstention_count: Annotated[int, Field(ge=0)] = 0

    _start = field_validator("started_at")(utc_timestamp)

    @field_validator("completed_at")
    @classmethod
    def end_time(cls, value: str | None) -> str | None:
        return utc_timestamp(value) if value is not None else None

    @model_validator(mode="after")
    def consistent(self) -> "AnnotationRun":
        reject_secrets(self.configuration)
        if not self.run_id.strip():
            raise ValueError("run ID must not be blank")
        for value in (
            self.model_identifier,
            self.model_version,
            self.provider,
            self.prompt_version,
        ):
            if value is not None and not value.strip():
                raise ValueError("provided model metadata must not be blank")
        if self.method == "llm" and not (
            self.model_identifier and self.prompt_version and self.provider
        ):
            raise ValueError("LLM run requires model, provider and prompt version")
        total = self.success_count + self.failure_count + self.abstention_count
        if total > self.sample_count:
            raise ValueError("run counts exceed sample count")
        if self.status != "running" and (total != self.sample_count or self.completed_at is None):
            raise ValueError("finished run requires complete counts and completion time")
        if self.completed_at and datetime.fromisoformat(
            self.completed_at.replace("Z", "+00:00")
        ) < datetime.fromisoformat(self.started_at.replace("Z", "+00:00")):
            raise ValueError("completion before start")
        if self.status == "completed" and self.failure_count:
            raise ValueError("completed run cannot have failures")
        return self
