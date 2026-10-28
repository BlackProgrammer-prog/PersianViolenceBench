"""Versioned metadata; source_type selects the exact allowed structure."""

from typing import Annotated, Literal

from pydantic import Field

from .common import StrictModel


class HarmBenchMetadata(StrictModel):
    metadata_schema_version: Literal["1.0.0"]
    source_type: Literal["harmbench"]
    behavior_id: str
    semantic_category: str
    functional_category: str
    tags_raw: str
    context_string: str


class StrongRejectMetadata(StrictModel):
    metadata_schema_version: Literal["1.0.0"]
    source_type: Literal["strongreject"]
    prompt_source: str


SourceMetadata = Annotated[
    HarmBenchMetadata | StrongRejectMetadata, Field(discriminator="source_type")
]
