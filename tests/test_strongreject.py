import pytest
from conftest import write_csv
from pydantic import ValidationError

from pvb.ingestion.adapters.strongreject import COLUMNS, adapt, load
from pvb.schemas.samples import BenchmarkSample


def test_valid_strongreject(sr_record):
    sample = adapt(sr_record)
    assert sample.dataset_split == "unspecified"
    assert sample.source_record_id is None
    assert sample.original_context is None
    assert sample.source_tags == []
    assert sample.source_metadata.prompt_source == sr_record["source"]
    assert sample.original_record() == sr_record


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown", "extra"),
        ("metadata_schema_version", "2.0.0"),
        ("source_type", "harmbench"),
    ],
)
def test_strict_metadata(sr_record, field, value):
    data = adapt(sr_record).model_dump()
    data["source_metadata"][field] = value
    with pytest.raises(ValidationError):
        BenchmarkSample.model_validate(data)


@pytest.mark.parametrize("field", ["prompt_source", "source_type", "metadata_schema_version"])
def test_required_metadata(sr_record, field):
    data = adapt(sr_record).model_dump()
    del data["source_metadata"][field]
    with pytest.raises(ValidationError):
        BenchmarkSample.model_validate(data)


def test_empty_prompt(sr_record):
    sr_record["forbidden_prompt"] = ""
    with pytest.raises(ValueError, match="forbidden_prompt"):
        adapt(sr_record)


def test_duplicate_content(tmp_path, sr_record):
    path = tmp_path / "sr.csv"
    write_csv(path, COLUMNS, [sr_record, sr_record])
    with pytest.raises(ValueError, match="duplicate content/sample ID"):
        load(path)


def test_same_prompt_different_provenance(sr_record):
    first = adapt(sr_record)
    second = adapt({**sr_record, "source": "another provider"})
    assert first.prompt_sha256 == second.prompt_sha256
    assert first.sample_id != second.sample_id
