"""CSV human review, independent attempts and explicit adjudication."""

import argparse
import csv
import io
from pathlib import Path

from pvb.extraction.io import write_jsonl, write_text
from pvb.ingestion.export import load_jsonl
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import Decision, SampleAnnotation, utc_now
from pvb.schemas.common import canonical_json, sha256_text
from pvb.schemas.samples import BenchmarkSample

DIMENSIONS = (
    "label",
    "subcategories",
    "intent",
    "target",
    "actionability",
    "risk_severity",
    "rationale",
)
FIELDS = [
    "sample_id",
    "original_prompt",
    "original_context",
    "proposed_annotation_id",
    *["proposed_" + d for d in DIMENSIONS],
    *["reviewer_" + d for d in DIMENSIONS],
    "reviewer_confidence",
    "reviewer_id",
    "reviewer_notes",
    "review_status",
    "adjudicates",
    "reviewer_overlapping_risks",
]


def export_review(
    path: Path,
    samples: list[BenchmarkSample],
    annotations: list[SampleAnnotation],
    *,
    independent: bool = False,
):
    proposals = {}
    for a in annotations:
        if a.sample_id in proposals:
            raise ValueError("export requires one selected proposal per sample")
        proposals[a.sample_id] = a
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    for s in samples:
        row = dict.fromkeys(FIELDS, "")
        row.update(
            sample_id=s.sample_id,
            original_prompt=s.original_prompt,
            original_context=s.original_context or "",
            review_status="pending",
        )
        a = proposals.get(s.sample_id)
        if a is not None and not independent:
            row["proposed_annotation_id"] = a.annotation_id
            for dimension in DIMENSIONS:
                value = getattr(a, dimension)
                row["proposed_" + dimension] = "|".join(value) if isinstance(value, list) else value
        writer.writerow(row)
    write_text(path, buffer.getvalue())


def import_review(
    path: Path,
    samples: list[BenchmarkSample],
    previous: list[SampleAnnotation],
    *,
    reviewer_id: str | None = None,
):
    sample_map = {s.sample_id: s for s in samples}
    known = {a.annotation_id: a for a in previous}
    digest = sha256_text(path.read_text(encoding="utf-8-sig"))
    run_id = "pvb-human-" + sha256_text(canonical_json([digest, reviewer_id]))
    now = utc_now()
    annotations, seen = [], set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError("review CSV header mismatch")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("malformed review CSV row")
            sample = sample_map.get(row["sample_id"])
            if sample is None or sample.sample_id in seen:
                raise ValueError("unknown or duplicate review sample ID")
            seen.add(sample.sample_id)
            if row["original_prompt"] != sample.original_prompt or row["original_context"] != (
                sample.original_context or ""
            ):
                raise ValueError("review text differs from canonical sample")
            if not row["reviewer_label"]:
                if row["review_status"] != "pending":
                    raise ValueError("review status without human classification")
                continue
            identity = row["reviewer_id"].strip() or reviewer_id
            if not identity or not identity.strip():
                raise ValueError("reviewer identity required")
            data = {key: row["reviewer_" + key] for key in DIMENSIONS}
            data["subcategories"] = [
                v.strip() for v in data["subcategories"].split("|") if v.strip()
            ]
            data["confidence"] = float(row["reviewer_confidence"])
            data["requires_human_review"] = row["review_status"] != "approved"
            data["overlapping_risks"] = [
                v.strip() for v in row["reviewer_overlapping_risks"].split("|") if v.strip()
            ]
            # Every dimension must be supplied by the reviewer; no invented human fields.
            decision = Decision.model_validate(data)
            supersedes = row["proposed_annotation_id"] or None
            parents = [v.strip() for v in row["adjudicates"].split("|") if v.strip()]
            for ref in ([supersedes] if supersedes else []) + parents:
                if ref not in known or known[ref].sample_id != sample.sample_id:
                    raise ValueError("unknown or different-sample review reference")
            annotations.append(
                SampleAnnotation(
                    **decision.model_dump(),
                    annotation_id="pvb:annotation:"
                    + sha256_text(canonical_json([run_id, sample.sample_id, identity])),
                    sample_id=sample.sample_id,
                    annotation_method="human",
                    annotator_id=identity,
                    annotation_run_id=run_id,
                    review_status=row["review_status"],
                    created_at=now,
                    updated_at=now,
                    supersedes_annotation_id=supersedes,
                    adjudicates=parents,
                    reviewer_notes=row["reviewer_notes"],
                )
            )
    if not annotations:
        raise ValueError("no completed human classifications in review CSV")
    run = AnnotationRun(
        run_id=run_id,
        method="human",
        configuration={"csv_sha256": digest, "reviewer_id": reviewer_id},
        input_dataset_fingerprint=sha256_text(
            canonical_json([s.model_dump(mode="json") for s in samples])
        ),
        started_at=now,
        completed_at=now,
        status="completed",
        sample_count=len(annotations),
        success_count=len(annotations),
    )
    return annotations, run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument(
        "--samples", type=Path, default=Path("data/normalized/benchmark_samples.jsonl")
    )
    parser.add_argument(
        "--annotations", type=Path, default=Path("data/extracted/annotations.jsonl")
    )
    parser.add_argument("--output", type=Path, default=Path("data/reviews"))
    parser.add_argument("--reviewer-id")
    parser.add_argument("--independent", action="store_true")
    args = parser.parse_args(argv)
    samples = load_jsonl(args.samples, BenchmarkSample)
    previous = load_jsonl(args.annotations, SampleAnnotation)
    if args.action == "export":
        if args.csv.exists() or args.csv.resolve() in (
            args.samples.resolve(),
            args.annotations.resolve(),
        ):
            parser.error("review export refuses to overwrite an existing file")
        export_review(args.csv, samples, previous, independent=args.independent)
    else:
        annotations, run = import_review(args.csv, samples, previous, reviewer_id=args.reviewer_id)
        destination = args.output / run.run_id
        if destination.exists():
            parser.error("this review import already exists; history is immutable")
        write_jsonl(
            destination / "annotations.jsonl", [a.model_dump(mode="json") for a in annotations]
        )
        write_jsonl(destination / "annotation_runs.jsonl", [run.model_dump(mode="json")])
        print(f"imported={len(annotations)}; run_id={run.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
