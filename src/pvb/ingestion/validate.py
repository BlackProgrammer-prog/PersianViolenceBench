"""Validate normalized artifacts and compare them with the configured raw snapshots."""

import argparse
import logging
from collections import Counter
from pathlib import Path

from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord
from pvb.schemas.validation import check_unique

from .adapters.base import IngestionError
from .export import load_jsonl, load_samples_csv
from .normalize import collect

LOGGER = logging.getLogger(__name__)


def validate_bundle(
    directory: Path, config_path: Path | None = Path("configs/datasets.yaml")
) -> tuple[int, int]:
    samples = load_jsonl(directory / "benchmark_samples.jsonl", BenchmarkSample)
    csv_samples = load_samples_csv(directory / "benchmark_samples.csv")
    sources = load_jsonl(directory / "benchmark_sources.jsonl", SourceRecord)
    check_unique(samples)
    check_unique(csv_samples)
    json_map = {s.sample_id: s for s in samples}
    if json_map != {s.sample_id: s for s in csv_samples}:
        raise IngestionError("CSV/JSONL consistency failure: sample sets or field values differ")
    source_keys = [(s.dataset_name, s.dataset_split) for s in sources]
    if len(source_keys) != len(set(source_keys)):
        raise IngestionError("duplicate source registry dataset/split")
    if len({s.source_id for s in sources}) != len(sources):
        raise IngestionError("duplicate source registry ID")
    counts = Counter((s.dataset_name, s.dataset_split) for s in samples)
    if set(counts) - set(source_keys):
        raise IngestionError("samples have no matching source registry entry")
    for source in sources:
        key = (source.dataset_name, source.dataset_split)
        if counts[key] != source.record_count:
            raise IngestionError(
                f"source registry count mismatch for {key}: "
                f"registry={source.record_count}, samples={counts[key]}"
            )
    if config_path is not None:
        expected_samples, expected_sources = collect(config_path)
        expected_map = {s.sample_id: s for s in expected_samples}
        if json_map != expected_map:
            missing = len(expected_map.keys() - json_map.keys())
            extra = len(json_map.keys() - expected_map.keys())
            changed = sum(
                json_map[k] != expected_map[k] for k in json_map.keys() & expected_map.keys()
            )
            raise IngestionError(
                f"raw source comparison failed: missing={missing}, extra={extra}, changed={changed}"
            )
        if {s.source_id: s for s in sources} != {s.source_id: s for s in expected_sources}:
            raise IngestionError("source registry differs from configured raw file provenance")
    else:
        LOGGER.warning(
            "Raw comparison disabled: completeness, file hashes and upstream provenance "
            "cannot be verified; record hashes are checked against reconstructed records"
        )
    LOGGER.info(
        "Validation passed: %d samples, %d source records; CSV/JSONL equivalent",
        len(samples),
        len(sources),
    )
    return len(samples), len(sources)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/normalized"))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument(
        "--skip-raw",
        action="store_true",
        help="Validate interchange only, without raw completeness/provenance checks",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        validate_bundle(args.input, None if args.skip_raw else args.config)
    except (IngestionError, OSError, ValueError) as exc:
        LOGGER.error("Validation failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
