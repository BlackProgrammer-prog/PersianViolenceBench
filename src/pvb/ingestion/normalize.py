"""Normalize configured local snapshots without modifying or downloading raw data."""

import argparse
import hashlib
import logging
from pathlib import Path

from pvb.schemas.common import source_identity
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord
from pvb.schemas.validation import check_unique

from .adapters import harmbench, strongreject
from .adapters.base import IngestionError
from .config import load_config
from .export import FILENAMES, export_bundle
from .provenance import verified_commit

LOGGER = logging.getLogger(__name__)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise IngestionError(f"{path}: cannot hash source: {exc}") from exc
    return digest.hexdigest()


def collect(config_path: Path) -> tuple[list[BenchmarkSample], list[SourceRecord]]:
    config, root = load_config(config_path)
    samples: list[BenchmarkSample] = []
    sources: list[SourceRecord] = []
    for source in config.sources:
        path = root / source.path
        before_hash = file_sha256(path)
        adapter = harmbench if source.dataset_name == "harmbench" else strongreject
        records = adapter.load(path, source.dataset_split)
        if file_sha256(path) != before_hash:
            raise IngestionError(f"{path}: raw source changed while reading")
        if (
            source.expected_record_count is not None
            and len(records) != source.expected_record_count
        ):
            LOGGER.warning(
                "%s: expected snapshot count %d, observed %d",
                path,
                source.expected_record_count,
                len(records),
            )
        registry = SourceRecord(
            source_id=source_identity(
                source.dataset_name, source.dataset_split, source.source_url, before_hash
            ),
            schema_version="1.0.0",
            dataset_name=source.dataset_name,
            dataset_split=source.dataset_split,
            source_url=source.source_url,
            sha256=before_hash,
            record_count=len(records),
            retrieved_commit=verified_commit(source, root, before_hash),
        )
        samples.extend(records)
        sources.append(registry)
        LOGGER.info(
            "%s/%s: %d records; SHA256=%s",
            source.dataset_name,
            source.dataset_split,
            len(records),
            before_hash,
        )
    check_unique(samples)
    return samples, sources


def normalize(config_path: Path, output: Path) -> tuple[list[BenchmarkSample], list[SourceRecord]]:
    config, root = load_config(config_path)
    destinations = {(output / filename).resolve() for filename in FILENAMES}
    if any((root / source.path).resolve() in destinations for source in config.sources):
        raise IngestionError("output paths overlap raw source files; refusing to modify raw data")
    samples, sources = collect(config_path)
    export_bundle(output, samples, sources)
    LOGGER.info("Exported %d samples and %d sources to %s", len(samples), len(sources), output)
    return samples, sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--output", type=Path, default=Path("data/normalized"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        normalize(args.config, args.output)
    except (IngestionError, OSError, ValueError) as exc:
        LOGGER.error("Normalization failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
