import csv
import shutil

import pytest
import yaml
from conftest import write_csv

from pvb.ingestion.adapters.harmbench import COLUMNS, load
from pvb.ingestion.export import FILENAMES, load_jsonl, load_samples_csv
from pvb.ingestion.normalize import check_unique, collect, main, normalize
from pvb.schemas.samples import BenchmarkSample


def test_roundtrip_unicode_duplicates_and_determinism(snapshot):
    config, output = snapshot
    samples, sources = normalize(config, output)
    assert len(samples) == 2
    assert len(sources) == 2
    assert samples[0].original_prompt == samples[1].original_prompt
    assert samples[0].sample_id != samples[1].sample_id
    assert load_samples_csv(output / FILENAMES[0]) == load_jsonl(
        output / FILENAMES[1], BenchmarkSample
    )
    first = {name: (output / name).read_bytes() for name in FILENAMES}
    normalize(config, output)
    assert first == {name: (output / name).read_bytes() for name in FILENAMES}
    assert "متن فارسی" in (output / FILENAMES[1]).read_text(encoding="utf-8")


def test_reordering_and_moving_inputs(snapshot, hb_record, tmp_path):
    config, output = snapshot
    extra = {**hb_record, "BehaviorID": "second", "Behavior": "another prompt"}
    write_csv(config.parent / "hb.csv", COLUMNS, [hb_record, extra])
    first, _ = normalize(config, output)
    first_bytes = (output / FILENAMES[1]).read_bytes()
    write_csv(config.parent / "hb.csv", tuple(reversed(COLUMNS)), [extra, hb_record])
    moved = tmp_path / "moved"
    moved.mkdir()
    for name in ("hb.csv", "sr.csv", "datasets.yaml"):
        shutil.copy(config.parent / name, moved / name)
    second, _ = normalize(moved / "datasets.yaml", output)
    assert {s.sample_id for s in first} == {s.sample_id for s in second}
    assert first_bytes == (output / FILENAMES[1]).read_bytes()


def test_duplicate_sample_id(snapshot):
    samples, _ = collect(snapshot[0])
    with pytest.raises(ValueError, match="duplicate sample ID"):
        check_unique([samples[0], samples[0]])


def test_failed_ingestion_preserves_output(snapshot):
    config, output = snapshot
    normalize(config, output)
    first = {name: (output / name).read_bytes() for name in FILENAMES}
    (config.parent / "sr.csv").unlink()
    with pytest.raises(ValueError, match="sr.csv"):
        normalize(config, output)
    assert first == {name: (output / name).read_bytes() for name in FILENAMES}


@pytest.mark.parametrize(
    "text",
    [
        "wrong,header\nx,y\n",
        ",".join(COLUMNS) + ",Behavior\n",
        ",".join(COLUMNS) + "\nshort,row\n",
        ",".join(COLUMNS) + '\n"unclosed\n',
        ",".join(COLUMNS) + "\n\n",
    ],
)
def test_invalid_csv(tmp_path, text):
    path = tmp_path / "broken.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="broken.csv: line"):
        load(path, "validation")


def test_count_discrepancy_is_reported(snapshot, caplog):
    config, output = snapshot
    data = yaml.safe_load(config.read_text())
    data["sources"][0]["expected_record_count"] = 20
    config.write_text(yaml.safe_dump(data))
    samples, _ = normalize(config, output)
    assert len(samples) == 2
    assert "expected snapshot count 20, observed 1" in caplog.text


def test_cli_failure_and_help(snapshot):
    config, output = snapshot
    assert main(["--config", str(config), "--output", str(output)]) == 0
    assert main(["--config", str(config.parent / "missing")]) == 1
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_nulls_roundtrip(snapshot):
    _, output = snapshot
    normalize(snapshot[0], output)
    with (output / FILENAMES[0]).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert any(row["source_record_id"] == "null" for row in rows)


def test_real_snapshot(project_root, tmp_path):
    paths = [
        project_root / "data/raw/harmbench/text_val.csv",
        project_root / "data/raw/harmbench/text_test.csv",
        project_root / "data/raw/strongreject/full.csv",
    ]
    if not all(path.exists() for path in paths):
        pytest.skip("real raw snapshots not installed")
    from pvb.ingestion.validate import validate_bundle

    config = project_root / "configs/datasets.yaml"
    samples, sources = normalize(config, tmp_path)
    assert {(s.dataset_name, s.dataset_split): s.record_count for s in sources} == {
        ("harmbench", "validation"): 80,
        ("harmbench", "test"): 320,
        ("strongreject", "unspecified"): 313,
    }
    assert len(samples) == 713  # Snapshot-specific integration assertion only.
    assert validate_bundle(tmp_path, config) == (713, 3)


def test_staging_failure_preserves_all_outputs(snapshot, monkeypatch):
    config, output = snapshot
    normalize(config, output)
    before = {name: (output / name).read_bytes() for name in FILENAMES}

    def fail(*args, **kwargs):
        raise OSError("simulated disk error")

    monkeypatch.setattr("pvb.ingestion.export._write_jsonl", fail)
    with pytest.raises(OSError, match="disk error"):
        normalize(config, output)
    assert before == {name: (output / name).read_bytes() for name in FILENAMES}
    assert not list(output.glob(".pvb-*"))


def test_duplicate_config_namespace(snapshot):
    config, _ = snapshot
    data = yaml.safe_load(config.read_text())
    data["sources"].append(data["sources"][0])
    config.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="duplicate dataset/split"):
        collect(config)


@pytest.mark.parametrize("context", ["", "null", "\\N", '"quotes"', "  ", "فارسی\r\n"])
def test_nullable_csv_values_are_unambiguous(snapshot, hb_record, context):
    config, output = snapshot
    hb_record["ContextString"] = context
    hb_record["BehaviorID"] = "null"
    write_csv(config.parent / "hb.csv", COLUMNS, [hb_record])
    samples, _ = normalize(config, output)
    loaded = load_samples_csv(output / FILENAMES[0])
    actual = next(sample for sample in loaded if sample.dataset_name == "harmbench")
    expected = next(sample for sample in samples if sample.dataset_name == "harmbench")
    assert actual == expected
    assert actual.source_record_id == "null"
    assert actual.original_context == (context or None)
    assert actual.source_metadata.context_string == context


def test_output_cannot_overwrite_raw(snapshot):
    config, _ = snapshot
    data = yaml.safe_load(config.read_text())
    raw = config.parent / FILENAMES[0]
    (config.parent / "hb.csv").rename(raw)
    data["sources"][0]["path"] = FILENAMES[0]
    config.write_text(yaml.safe_dump(data))
    before = raw.read_bytes()
    with pytest.raises(ValueError, match="overlap raw source"):
        normalize(config, config.parent)
    assert raw.read_bytes() == before
