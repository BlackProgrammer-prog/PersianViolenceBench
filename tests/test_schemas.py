import copy
import hashlib
import json

import pytest
from pydantic import ValidationError

from pvb.ingestion.adapters.harmbench import adapt
from pvb.schemas.common import record_hash
from pvb.schemas.samples import CANONICAL_FIELDS, BenchmarkSample

FIELDS = (
    "schema_version",
    "sample_id",
    "dataset_name",
    "dataset_split",
    "source_record_id",
    "original_language",
    "original_prompt",
    "original_context",
    "source_category",
    "functional_category",
    "source_tags",
    "source_metadata",
    "raw_record_sha256",
    "prompt_sha256",
)


def test_exact_schema():
    assert CANONICAL_FIELDS == FIELDS


@pytest.mark.parametrize("field", FIELDS)
def test_every_field_required(field, hb_record):
    data = adapt(hb_record, "validation").model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        BenchmarkSample.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0.0"),
        ("dataset_name", "other"),
        ("dataset_split", "train"),
        ("original_language", "fa"),
        ("original_prompt", " \n"),
        ("source_category", "wrong"),
        ("source_tags", ["wrong"]),
        ("original_context", None),
        ("source_record_id", "wrong"),
        ("functional_category", "wrong"),
        ("prompt_sha256", "a" * 64),
        ("raw_record_sha256", "b" * 64),
        ("raw_record_sha256", "Z" * 64),
        ("sample_id", "wrong"),
        ("source_file", "forbidden"),
        ("source_tags", "tag"),
    ],
)
def test_rejects_invalid_canonical_values(field, value, hb_record):
    data = adapt(hb_record, "validation").model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        BenchmarkSample.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("metadata_schema_version", "2.0.0"),
        ("source_type", "strongreject"),
        ("unknown", "extra"),
        ("semantic_category", "mismatch"),
        ("tags_raw", "different"),
    ],
)
def test_strict_metadata(field, value, hb_record):
    data = adapt(hb_record, "validation").model_dump()
    data["source_metadata"][field] = value
    with pytest.raises(ValidationError):
        BenchmarkSample.model_validate(data)


@pytest.mark.parametrize(
    "field",
    [
        "metadata_schema_version",
        "source_type",
        "behavior_id",
        "semantic_category",
        "functional_category",
        "tags_raw",
        "context_string",
    ],
)
def test_metadata_fields_required(field, hb_record):
    data = adapt(hb_record, "validation").model_dump()
    del data["source_metadata"][field]
    with pytest.raises(ValidationError):
        BenchmarkSample.model_validate(data)


def test_independent_hashes(hb_record):
    sample = adapt(hb_record, "validation")
    serialized = json.dumps(hb_record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert sample.raw_record_sha256 == hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert sample.prompt_sha256 == hashlib.sha256(hb_record["Behavior"].encode("utf-8")).hexdigest()
    assert sample.original_record() == hb_record
    assert record_hash(dict(reversed(list(hb_record.items())))) == sample.raw_record_sha256
    changed = copy.copy(hb_record)
    changed["Behavior"] = changed["Behavior"].strip()
    assert adapt(changed, "validation").prompt_sha256 != sample.prompt_sha256
