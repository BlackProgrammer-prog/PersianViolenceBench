"""Canonical 14-field sample schema, version 1.0.0."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    DatasetName,
    DatasetSplit,
    StrictModel,
    parse_tags,
    record_hash,
    sample_identity,
    sha256_text,
)
from .metadata import HarmBenchMetadata, SourceMetadata

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BenchmarkSample(StrictModel):
    schema_version: Literal["1.0.0"]
    sample_id: str
    dataset_name: DatasetName
    dataset_split: DatasetSplit
    source_record_id: str | None
    original_language: Literal["en"]
    original_prompt: str
    original_context: str | None
    source_category: str
    functional_category: str | None
    source_tags: list[str]
    source_metadata: SourceMetadata
    raw_record_sha256: SHA256
    prompt_sha256: SHA256

    def original_record(self) -> dict[str, str]:
        """Reconstruct every source column without losing empty-string values."""
        meta = self.source_metadata
        if isinstance(meta, HarmBenchMetadata):
            return {
                "Behavior": self.original_prompt,
                "FunctionalCategory": meta.functional_category,
                "SemanticCategory": meta.semantic_category,
                "Tags": meta.tags_raw,
                "ContextString": meta.context_string,
                "BehaviorID": meta.behavior_id,
            }
        return {
            "category": self.source_category,
            "source": meta.prompt_source,
            "forbidden_prompt": self.original_prompt,
        }

    @model_validator(mode="after")
    def check_consistency(self) -> "BenchmarkSample":
        if not self.original_prompt.strip():
            raise ValueError("original_prompt must contain non-whitespace text")
        if not self.source_category.strip():
            raise ValueError("source_category must not be empty")
        meta = self.source_metadata
        if self.dataset_name != meta.source_type:
            raise ValueError("dataset_name/source_type mismatch")
        if isinstance(meta, HarmBenchMetadata):
            if self.dataset_split not in ("validation", "test"):
                raise ValueError("HarmBench requires validation or test split")
            if not meta.behavior_id.strip() or not meta.functional_category.strip():
                raise ValueError("HarmBench ID and functional category must not be empty")
            expected = (
                meta.behavior_id,
                meta.semantic_category,
                meta.functional_category,
                meta.context_string or None,
                parse_tags(meta.tags_raw),
            )
            actual = (
                self.source_record_id,
                self.source_category,
                self.functional_category,
                self.original_context,
                self.source_tags,
            )
            if actual != expected:
                raise ValueError("HarmBench metadata/canonical fields mismatch")
        elif (
            self.dataset_split != "unspecified"
            or self.source_record_id is not None
            or self.original_context is not None
            or self.functional_category is not None
            or self.source_tags != []
        ):
            raise ValueError("StrongREJECT requires unspecified split and absent optional fields")
        if self.dataset_name == "strongreject" and not meta.prompt_source.strip():
            raise ValueError("StrongREJECT prompt_source must not be empty")
        if self.prompt_sha256 != sha256_text(self.original_prompt):
            raise ValueError("prompt_sha256 does not match original_prompt")
        if self.raw_record_sha256 != record_hash(self.original_record()):
            raise ValueError("raw_record_sha256 does not match reconstructed original record")
        if self.sample_id != sample_identity(
            self.dataset_name, self.dataset_split, self.raw_record_sha256
        ):
            raise ValueError("sample_id does not match dataset, split and raw record")
        return self


CANONICAL_FIELDS = tuple(BenchmarkSample.model_fields)
