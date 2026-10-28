import pytest
from conftest import write_csv

from pvb.ingestion.adapters.harmbench import COLUMNS, adapt, load


def test_valid_harmbench(hb_record):
    sample = adapt(hb_record, "validation")
    assert sample.source_record_id == "original-id"
    assert sample.original_prompt == hb_record["Behavior"]
    assert sample.original_context == hb_record["ContextString"]
    assert sample.source_tags == ["tag1", "tag2", "tag1"]
    assert sample.source_metadata.tags_raw == hb_record["Tags"]


def test_empty_context_and_tags(hb_record):
    hb_record.update(ContextString="", Tags="")
    sample = adapt(hb_record, "test")
    assert sample.original_context is None
    assert sample.source_metadata.context_string == ""
    assert sample.source_tags == []


@pytest.mark.parametrize(
    "field", ["Behavior", "BehaviorID", "SemanticCategory", "FunctionalCategory"]
)
def test_empty_required_field(hb_record, field):
    hb_record[field] = " \t"
    with pytest.raises(ValueError, match=field):
        adapt(hb_record, "validation")


def test_duplicate_behavior_id(tmp_path, hb_record):
    path = tmp_path / "hb.csv"
    second = {**hb_record, "Behavior": "different"}
    write_csv(path, COLUMNS, [hb_record, second])
    with pytest.raises(ValueError, match="line .*duplicate BehaviorID"):
        load(path, "validation")


def test_utf8_sig(tmp_path, hb_record):
    path = tmp_path / "hb.csv"
    write_csv(path, COLUMNS, [hb_record])
    assert load(path, "validation")[0].original_record() == hb_record
