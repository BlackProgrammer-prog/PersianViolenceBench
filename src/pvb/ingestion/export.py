"""Deterministic interchange with atomic replacement of fully staged files."""

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pvb.schemas.common import StrictModel
from pvb.schemas.samples import CANONICAL_FIELDS, BenchmarkSample
from pvb.schemas.sources import SourceRecord

from .adapters.base import IngestionError, read_records

T = TypeVar("T", bound=StrictModel)
FILENAMES = ("benchmark_samples.csv", "benchmark_samples.jsonl", "benchmark_sources.jsonl")
# All nullable scalar cells are JSON literals, including present strings. This
# distinguishes null, an empty string, and a literal string containing 'null'.
NULLABLE_FIELDS = ("source_record_id", "original_context", "functional_category")
JSON_FIELDS = (*NULLABLE_FIELDS, "source_tags", "source_metadata")


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _write_jsonl(path: Path, records: list[T]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        for record in records:
            stream.write(json_text(record.model_dump(mode="json")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def export_bundle(
    output: Path, samples: list[BenchmarkSample], sources: list[SourceRecord]
) -> None:
    """Stage every artifact before replacing any existing output file.

    Each replacement is atomic. The bundle is not a multi-file transaction;
    concurrent readers must coordinate with the single writer.
    """
    ordered_samples = sorted(samples, key=lambda sample: sample.sample_id)
    ordered_sources = sorted(sources, key=lambda source: source.source_id)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pvb-", dir=output) as directory:
        staging = Path(directory)
        with (staging / FILENAMES[0]).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CANONICAL_FIELDS, lineterminator="\r\n")
            writer.writeheader()
            for sample in ordered_samples:
                row = sample.model_dump(mode="json")
                for field in JSON_FIELDS:
                    row[field] = json_text(row[field])
                writer.writerow(row)
            stream.flush()
            os.fsync(stream.fileno())
        _write_jsonl(staging / FILENAMES[1], ordered_samples)
        _write_jsonl(staging / FILENAMES[2], ordered_sources)
        for filename in FILENAMES:
            os.replace(staging / filename, output / filename)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def decode_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_unique_object)


def load_jsonl(path: Path, model: type[T]) -> list[T]:
    result = []
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            for line, text in enumerate(stream, 1):
                try:
                    result.append(model.model_validate(decode_json(text)))
                except ValueError as exc:
                    raise IngestionError(f"{path}: line {line}: {exc}") from exc
    except (OSError, UnicodeError) as exc:
        raise IngestionError(f"{path}: {exc}") from exc
    return result


def load_samples_csv(path: Path) -> list[BenchmarkSample]:
    result = []
    # Column order is part of the canonical interchange contract.
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            if next(csv.reader(stream), None) != list(CANONICAL_FIELDS):
                raise IngestionError(f"{path}: invalid canonical CSV column order/header")
    except (OSError, UnicodeError, csv.Error) as exc:
        raise IngestionError(f"{path}: {exc}") from exc
    for line, row in read_records(path, CANONICAL_FIELDS):
        try:
            decoded: dict[str, object] = dict(row)
            for field in JSON_FIELDS:
                decoded[field] = decode_json(row[field])
            result.append(BenchmarkSample.model_validate(decoded))
        except ValueError as exc:
            raise IngestionError(f"{path}: line {line}: {exc}") from exc
    return result
