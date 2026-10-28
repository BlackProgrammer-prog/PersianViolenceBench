"""Shared validation and byte-level identity conventions."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

DatasetName = Literal["harmbench", "strongreject"]
DatasetSplit = Literal["validation", "test", "unspecified"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def canonical_json(value: Any) -> str:
    """Canonical source JSON: sorted keys, compact separators, literal Unicode."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_hash(record: dict[str, str]) -> str:
    return sha256_text(canonical_json(record))


def sample_identity(dataset: str, split: str, raw_hash: str) -> str:
    return f"pvb:{dataset}:" + sha256_text(canonical_json(["1.0.0", dataset, split, raw_hash]))


def source_identity(dataset: str, split: str, url: str, file_hash: str) -> str:
    return "pvb:source:" + sha256_text(canonical_json(["1.0.0", dataset, split, url, file_hash]))


def parse_tags(raw: str) -> list[str]:
    return [tag.strip() for tag in raw.split(",") if tag.strip()]
