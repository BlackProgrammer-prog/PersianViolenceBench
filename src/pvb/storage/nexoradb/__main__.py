"""Persist canonical data and one archived extraction run, then verify reads."""

import argparse
from pathlib import Path

from pvb.ingestion.export import load_jsonl
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord
from pvb.storage.nexoradb import NexoraRepository


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--normalized", type=Path, default=Path("data/normalized"))
    parser.add_argument("--extracted", type=Path, default=Path("data/extracted"))
    args = parser.parse_args(argv)
    samples = load_jsonl(args.normalized / "benchmark_samples.jsonl", BenchmarkSample)
    sources = load_jsonl(args.normalized / "benchmark_sources.jsonl", SourceRecord)
    runs = load_jsonl(args.extracted / "annotation_runs.jsonl", AnnotationRun)
    annotations = load_jsonl(args.extracted / "annotations.jsonl", SampleAnnotation)
    repo = NexoraRepository(args.database)
    repo.ingest(sources, samples)
    for run in runs:
        repo.save_run(run)
    repo.add_annotations(annotations)
    if {s.sample_id: s for s in repo.list_samples()} != {s.sample_id: s for s in samples}:
        raise RuntimeError("native sample read-after-write failed")
    if not {a.annotation_id for a in annotations} <= {
        a.annotation_id for a in repo.list_annotations()
    }:
        raise RuntimeError("native annotation read-after-write failed")
    print(
        f"verified: sources={len(sources)}, samples={len(samples)}, runs={len(runs)}, annotations={len(annotations)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
