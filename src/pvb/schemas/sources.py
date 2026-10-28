"""File-level provenance, independent of local paths."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import DatasetName, DatasetSplit, StrictModel, source_identity
from .samples import SHA256


class SourceRecord(StrictModel):
    source_id: str
    schema_version: Literal["1.0.0"]
    dataset_name: DatasetName
    dataset_split: DatasetSplit
    source_url: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    sha256: SHA256
    record_count: Annotated[int, Field(ge=0)]
    retrieved_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None

    @model_validator(mode="after")
    def check_identity(self) -> "SourceRecord":
        if (self.dataset_name == "harmbench" and self.dataset_split == "unspecified") or (
            self.dataset_name == "strongreject" and self.dataset_split != "unspecified"
        ):
            raise ValueError("dataset/split mismatch")
        if self.source_id != source_identity(
            self.dataset_name, self.dataset_split, self.source_url, self.sha256
        ):
            raise ValueError("source_id does not match source provenance")
        return self
