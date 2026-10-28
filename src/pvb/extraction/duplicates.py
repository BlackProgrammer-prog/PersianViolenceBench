"""Exact and normalized-text duplicates, with no record merging."""

import argparse
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from pvb.extraction.io import write_json
from pvb.ingestion.export import load_jsonl
from pvb.schemas.common import sha256_text
from pvb.schemas.samples import BenchmarkSample


def duplicate_report(
    samples: list[BenchmarkSample],
    *,
    unicode_form: str = "NFKC",
    whitespace: bool = True,
    casefold: bool = True,
) -> dict:
    if unicode_form not in ("NFC", "NFKC", "NFD", "NFKD", "none"):
        raise ValueError("unsupported Unicode normalization")
    exact, normalized = defaultdict(list), defaultdict(list)
    for sample in samples:
        text = sample.original_prompt
        if unicode_form != "none":
            text = unicodedata.normalize(unicode_form, text)
        if whitespace:
            text = re.sub(r"\s+", " ", text).strip()
        if casefold:
            text = text.casefold()
        entry = {
            "sample_id": sample.sample_id,
            "dataset_name": sample.dataset_name,
            "dataset_split": sample.dataset_split,
        }
        exact[sample.prompt_sha256].append(entry)
        normalized[sha256_text(text)].append(entry)

    def groups(mapping):
        return [
            {
                "key": key,
                "samples": rows,
                "cross_source": len({r["dataset_name"] for r in rows}) > 1,
                "cross_split": len({(r["dataset_name"], r["dataset_split"]) for r in rows}) > 1,
            }
            for key, rows in sorted(mapping.items())
            if len(rows) > 1
        ]

    return {
        "sample_count": len(samples),
        "configuration": {
            "unicode_form": unicode_form,
            "whitespace": whitespace,
            "casefold": casefold,
        },
        "exact_groups": groups(exact),
        "normalized_text_groups": groups(normalized),
        "policy": "No merge or deletion. Normalized equality is not byte-exact equality; context may differ.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=Path("data/normalized/benchmark_samples.jsonl")
    )
    parser.add_argument("--output", type=Path, default=Path("data/extracted/duplicate_report.json"))
    parser.add_argument(
        "--unicode-form", choices=["NFC", "NFKC", "NFD", "NFKD", "none"], default="NFKC"
    )
    parser.add_argument("--keep-case", action="store_true")
    parser.add_argument("--keep-whitespace", action="store_true")
    args = parser.parse_args(argv)
    report = duplicate_report(
        load_jsonl(args.input, BenchmarkSample),
        unicode_form=args.unicode_form,
        whitespace=not args.keep_whitespace,
        casefold=not args.keep_case,
    )
    if args.output.resolve() == args.input.resolve():
        parser.error("output overlaps input")
    write_json(args.output, report)
    print(
        f"exact_groups={len(report['exact_groups'])}; normalized_groups={len(report['normalized_text_groups'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
