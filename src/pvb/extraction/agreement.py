"""Two independent annotators: categorical kappa and per-subcategory binary kappa."""

from collections import Counter


def kappa(left: list[str], right: list[str]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    n = len(left)
    a, b = Counter(left), Counter(right)
    observed = sum(x == y for x, y in zip(left, right)) / n
    expected = sum(a[k] * b[k] for k in a.keys() | b.keys()) / n**2
    return (observed - expected) / (1 - expected) if expected < 1 else None


def agreement(annotations, annotator_a: str, annotator_b: str) -> dict:
    if annotator_a == annotator_b:
        raise ValueError("two distinct independent annotators required")
    maps = {annotator_a: {}, annotator_b: {}}
    for a in annotations:
        if (
            a.annotation_method == "human"
            and a.annotator_id in maps
            and not a.adjudicates
            and not a.supersedes_annotation_id
            and a.review_status == "approved"
        ):
            mapping = maps[a.annotator_id]
            if a.sample_id in mapping:
                raise ValueError("select one independent attempt per annotator/sample")
            mapping[a.sample_id] = a
    left, right = maps.values()
    shared = sorted(left.keys() & right.keys())
    disagreements = [
        sid
        for sid in shared
        if (left[sid].label, set(left[sid].subcategories))
        != (right[sid].label, set(right[sid].subcategories))
    ]
    return {
        "paired_count": len(shared),
        "label_kappa": kappa([left[s].label for s in shared], [right[s].label for s in shared]),
        "subcategory_binary_kappa": {
            v: kappa(
                [str(v in left[s].subcategories) for s in shared],
                [str(v in right[s].subcategories) for s in shared],
            )
            for v in ("V1", "V2", "V3", "V4", "V5")
        },
        "disagreement_sample_ids": disagreements,
        "limitation": "Two selected independent approved human attempts only. Null means insufficient pairs or degenerate marginals. Per-label binary kappa is not one multi-label kappa; prevalence affects agreement.",
    }


def main(argv=None):
    import argparse
    from pathlib import Path

    from pvb.extraction.io import write_json
    from pvb.ingestion.export import load_jsonl
    from pvb.schemas.annotations import SampleAnnotation

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--annotator-a", required=True)
    parser.add_argument("--annotator-b", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.resolve() == args.annotations.resolve():
        parser.error("output overlaps input")
    report = agreement(
        load_jsonl(args.annotations, SampleAnnotation), args.annotator_a, args.annotator_b
    )
    write_json(args.output, report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
