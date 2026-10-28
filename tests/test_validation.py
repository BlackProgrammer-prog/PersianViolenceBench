import json

import pytest

from pvb.ingestion.export import FILENAMES, export_bundle
from pvb.ingestion.normalize import normalize
from pvb.ingestion.validate import main, validate_bundle
from pvb.schemas.common import source_identity


def rewrite(path, transform):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows = transform(rows)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def test_full_validation(snapshot):
    config, output = snapshot
    normalize(config, output)
    assert validate_bundle(output, config) == (2, 2)
    assert main(["--input", str(output), "--config", str(config)]) == 0
    assert validate_bundle(output, None) == (2, 2)


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_sha256", "f" * 64),
        ("raw_record_sha256", "a" * 64),
        ("sample_id", "corrupt"),
        ("extra", "not allowed"),
    ],
)
def test_tampered_sample(snapshot, field, value):
    config, output = snapshot
    normalize(config, output)

    def change(rows):
        rows[0][field] = value
        return rows

    rewrite(output / FILENAMES[1], change)
    with pytest.raises(ValueError, match="line 1"):
        validate_bundle(output, config)


def test_missing_records_even_when_counts_and_formats_agree(snapshot):
    config, output = snapshot
    samples, sources = normalize(config, output)
    remaining = [s for s in samples if s.dataset_name == "strongreject"]
    adjusted = [
        s.model_copy(update={"record_count": 0}) if s.dataset_name == "harmbench" else s
        for s in sources
    ]
    export_bundle(output, remaining, adjusted)
    with pytest.raises(ValueError, match="missing=1"):
        validate_bundle(output, config)


def test_csv_jsonl_mismatch(snapshot):
    config, output = snapshot
    normalize(config, output)
    rewrite(output / FILENAMES[1], lambda rows: rows[1:])
    with pytest.raises(ValueError, match="CSV/JSONL consistency"):
        validate_bundle(output, config)


def test_registry_count(snapshot):
    config, output = snapshot
    normalize(config, output)

    def change(rows):
        rows[0]["record_count"] += 1
        return rows

    rewrite(output / FILENAMES[2], change)
    with pytest.raises(ValueError, match="registry count mismatch"):
        validate_bundle(output, config)


def test_registry_raw_file_hash(snapshot):
    config, output = snapshot
    normalize(config, output)

    def change(rows):
        row = rows[0]
        row["sha256"] = "f" * 64
        row["source_id"] = source_identity(
            row["dataset_name"], row["dataset_split"], row["source_url"], row["sha256"]
        )
        return rows

    rewrite(output / FILENAMES[2], change)
    with pytest.raises(ValueError, match="raw file provenance"):
        validate_bundle(output, config)


def test_duplicate_samples(snapshot):
    config, output = snapshot
    normalize(config, output)
    rewrite(output / FILENAMES[1], lambda rows: rows + [rows[0]])
    with pytest.raises(ValueError, match="duplicate sample ID"):
        validate_bundle(output, config)


def test_duplicate_sources(snapshot):
    config, output = snapshot
    normalize(config, output)
    rewrite(output / FILENAMES[2], lambda rows: rows + [rows[0]])
    with pytest.raises(ValueError, match="duplicate source registry"):
        validate_bundle(output, config)


def test_missing_registry(snapshot):
    config, output = snapshot
    normalize(config, output)
    rewrite(output / FILENAMES[2], lambda rows: rows[1:])
    with pytest.raises(ValueError, match="no matching source"):
        validate_bundle(output, config)


def test_duplicate_json_key(snapshot):
    config, output = snapshot
    normalize(config, output)
    path = output / FILENAMES[1]
    path.write_text('{"schema_version":"1.0.0","schema_version":"1.0.0"}\n')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        validate_bundle(output, config)


def test_validation_exit_code(snapshot):
    config, output = snapshot
    assert main(["--input", str(output), "--config", str(config)]) == 1
