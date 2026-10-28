"""Audit annotations without confusing provisional labels with human truth."""

import argparse
from collections import Counter
from pathlib import Path

from pvb.extraction.io import write_json
from pvb.ingestion.export import load_jsonl
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.samples import BenchmarkSample


def audit(
    samples: list[BenchmarkSample],
    annotations: list[SampleAnnotation],
    runs: list[AnnotationRun],
    *,
    accounted_unclassified: set[str] | None = None,
) -> dict:
    errors, warnings = [], []
    sample_map = {s.sample_id: s for s in samples}
    run_map = {r.run_id: r for r in runs}
    ids, classified = set(), set()
    if len(sample_map) != len(samples):
        errors.append("duplicate sample IDs")
    if len(run_map) != len(runs):
        errors.append("duplicate run IDs")
    for raw in annotations:
        try:
            a = SampleAnnotation.model_validate(raw.model_dump())
        except ValueError:
            errors.append("invalid annotation structure")
            continue
        if a.annotation_id in ids:
            errors.append("duplicate annotation ID: " + a.annotation_id)
        ids.add(a.annotation_id)
        sample = sample_map.get(a.sample_id)
        run = run_map.get(a.annotation_run_id)
        if sample is None:
            errors.append("unknown sample ID: " + a.sample_id)
        else:
            classified.add(a.sample_id)
            if sample.functional_category == "contextual" and not sample.original_context:
                errors.append("missing context: " + a.sample_id)
            text = sample.original_prompt + "\n" + (sample.original_context or "")
            if any(
                excerpt not in text and excerpt.casefold() not in text.casefold()
                for excerpt in a.evidence
            ):
                errors.append("unsupported evidence: " + a.annotation_id)
        if run is None:
            errors.append("missing run metadata: " + a.annotation_id)
        elif a.annotation_method != run.method or a.taxonomy_version != run.taxonomy_version:
            errors.append("run provenance mismatch: " + a.annotation_id)
        if a.supersedes_annotation_id and a.supersedes_annotation_id not in {
            x.annotation_id for x in annotations
        }:
            errors.append("unknown superseded annotation: " + a.annotation_id)
        for parent in a.adjudicates:
            prior = next((x for x in annotations if x.annotation_id == parent), None)
            if prior is None or prior.sample_id != a.sample_id:
                errors.append("invalid adjudication reference: " + a.annotation_id)
    # Context completeness applies even to abstentions.
    missing_context = [
        s.sample_id
        for s in samples
        if s.functional_category == "contextual" and not s.original_context
    ]
    if missing_context:
        errors.append(f"{len(missing_context)} context-dependent samples lack context")
    missing = set(sample_map) - classified
    accounted = accounted_unclassified or set()
    if accounted - set(sample_map):
        errors.append("unknown unclassified sample IDs")
    if accounted & classified:
        errors.append("samples both classified and unclassified")
    if missing - accounted:
        errors.append(f"{len(missing - accounted)} missing unaccounted classifications")
    if missing:
        warnings.append(f"{len(missing)} explicitly unclassified samples require review")
    provisional = sum(a.annotation_method != "human" for a in annotations)
    if provisional:
        warnings.append(
            f"{provisional} provisional automatic annotations; not verified ground truth"
        )
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "sample_count": len(samples),
        "annotation_count": len(annotations),
        "unclassified_count": len(missing),
        "unreviewed_llm_count": sum(a.annotation_method == "llm" for a in annotations),
        "approved_human_count": sum(
            a.annotation_method == "human" and a.review_status == "approved" for a in annotations
        ),
    }


def grouped_summary(samples, annotations) -> dict:
    lookup = {s.sample_id: s for s in samples}
    counters = {
        key: Counter()
        for key in (
            "source_dataset",
            "source_category",
            "dataset_split",
            "classification_label",
            "violence_subcategory",
            "review_status",
            "annotation_method",
        )
    }
    for a in annotations:
        s = lookup[a.sample_id]
        values = {
            "source_dataset": s.dataset_name,
            "source_category": s.source_category,
            "dataset_split": s.dataset_split,
            "classification_label": a.label,
            "review_status": a.review_status,
            "annotation_method": a.annotation_method,
        }
        for key, value in values.items():
            counters[key][value] += 1
        counters["violence_subcategory"].update(a.subcategories)
    return {key: dict(sorted(count.items())) for key, count in counters.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=Path("data/normalized/benchmark_samples.jsonl")
    )
    parser.add_argument("--directory", type=Path, default=Path("data/extracted"))
    args = parser.parse_args(argv)
    samples = load_jsonl(args.input, BenchmarkSample)
    annotations = load_jsonl(args.directory / "annotations.jsonl", SampleAnnotation)
    runs = load_jsonl(args.directory / "annotation_runs.jsonl", AnnotationRun)
    import json

    unclassified = {
        row["sample_id"]
        for row in map(json.loads, (args.directory / "unclassified.jsonl").read_text().splitlines())
    }
    report = audit(samples, annotations, runs, accounted_unclassified=unclassified)
    write_json(args.directory / "quality_report.json", report)
    print(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
