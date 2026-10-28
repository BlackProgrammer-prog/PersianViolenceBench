"""Validated source manifest. Relative paths resolve from config/root."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, model_validator

from pvb.schemas.common import DatasetName, DatasetSplit, StrictModel

from .adapters.base import IngestionError


class SourceConfig(StrictModel):
    dataset_name: DatasetName
    dataset_split: DatasetSplit
    path: str
    source_url: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    expected_record_count: Annotated[int, Field(ge=0)] | None = None
    # Only record an independently verified upstream revision; null is the default.
    retrieved_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None = None

    commit_repository: str | None = None

    @model_validator(mode="after")
    def check_split(self) -> "SourceConfig":
        if (self.dataset_name == "harmbench" and self.dataset_split == "unspecified") or (
            self.dataset_name == "strongreject" and self.dataset_split != "unspecified"
        ):
            raise ValueError("unsupported dataset/split combination")
        if not self.path.strip():
            raise ValueError("source path must not be empty")
        return self


class DatasetConfig(StrictModel):
    schema_version: Literal["1.0.0"]
    root: str = ".."
    sources: Annotated[list[SourceConfig], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_namespaces(self) -> "DatasetConfig":
        keys = [(s.dataset_name, s.dataset_split) for s in self.sources]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate dataset/split in source configuration")
        return self


def load_config(path: Path) -> tuple[DatasetConfig, Path]:
    try:
        config = DatasetConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        return config, (path.resolve().parent / config.root).resolve()
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise IngestionError(f"{path}: invalid source configuration: {exc}") from exc
