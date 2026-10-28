"""Check translation settings or prepare language-variant plans without API calls."""

import argparse
import json
from collections import Counter
from pathlib import Path

from pvb.extraction.io import write_json, write_jsonl
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.common import canonical_json, sha256_text
from pvb.schemas.samples import CANONICAL_FIELDS, BenchmarkSample
from pvb.translation.settings import ROOT, load_settings


def prepare(settings, root):
    root = root.resolve()
    source = (root / settings.input).resolve()
    output = (root / settings.output).resolve()
    if any(
        output.is_relative_to(root / p) for p in ("data/raw", "data/normalized", "src", "configs")
    ) or source.is_relative_to(output):
        raise ValueError("Translation output overlaps protected source paths.")
    records = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    if settings.scope != "all":
        records = [r for r in records if r["category"] == settings.scope]
    if not records or len({r["sample_id"] for r in records}) != len(records):
        raise ValueError("Translation input must contain nonempty, unique sample records.")
    settings_public = settings.public()
    identity = sha256_text(
        canonical_json(
            {
                "plan_schema_version": "1.0.0",
                "source": sha256_text(source.read_text()),
                "settings": settings_public,
            }
        )
    )
    directory = output / ("plan-" + identity[:16])
    variants = {name: [] for name in ("english", "llm_translation", "google_translate")}
    for row in records:
        sample = BenchmarkSample.model_validate({key: row[key] for key in CANONICAL_FIELDS})
        annotation = SampleAnnotation.model_validate(row["annotation"])
        if (
            annotation.sample_id != sample.sample_id
            or row["classification_label"] != annotation.label
        ):
            raise ValueError("Translation source annotation does not match the sample.")
        common = {
            "sample_id": sample.sample_id,
            "category": row["category"],
            "classification_label": row["classification_label"],
            "classification_inherited_from": "english",
            "classification_annotation_id": annotation.annotation_id,
            "classification_run_id": annotation.annotation_run_id,
            "sample": sample.model_dump(mode="json"),
            "source_registry": row.get("source_registry", []),
            "source_prompt_sha256": sample.prompt_sha256,
            "source_context_sha256": sha256_text(sample.original_context)
            if sample.original_context is not None
            else None,
        }
        for name, variant_rows in variants.items():
            original = name == "english"
            provider = (
                None
                if original
                else settings.llm_provider
                if name == "llm_translation"
                else "google_cloud_translation"
            )
            model = (
                None
                if original
                else settings.llm_model
                if name == "llm_translation"
                else settings.google_model
            )
            variant_rows.append(
                {
                    **common,
                    "variant_id": "pvb:variant:"
                    + sha256_text(canonical_json([identity, sample.sample_id, name])),
                    "variant": name,
                    "language": "en" if original else settings.target_language,
                    "status": "original" if original else "pending_translation",
                    "prompt": sample.original_prompt if original else None,
                    "context": sample.original_context if original else None,
                    "provider": provider,
                    "model_requested": model,
                    "model_returned": None,
                    "api_version": "v2" if name == "google_translate" else None,
                    "translation_review_status": "not_applicable" if original else "not_started",
                }
            )
    for name, rows in variants.items():
        filename = "samples.jsonl" if name == "english" else "pending.jsonl"
        path = directory / name / filename
        if path.exists():
            existing = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            if existing != rows:
                raise ValueError("Existing translation plan has changes; it was not overwritten.")
        else:
            write_jsonl(path, rows)
    report = {
        "plan_schema_version": "1.0.0",
        "plan_directory": str(directory),
        "source_samples": len(records),
        "category_counts": dict(Counter(r["category"] for r in records)),
        "variants": {
            name: {"rows": len(rows), "status": rows[0]["status"]}
            for name, rows in variants.items()
        },
        "settings": settings_public,
        "network_requests": 0,
        "paid_requests": 0,
        "translated_samples": 0,
    }
    write_json(directory / "plan.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("config-check", "prepare"), default="config-check")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.root)
        if args.mode == "prepare":
            result = prepare(settings, args.root)
            code = 0
        else:
            issues = settings.issues()
            result = {
                "settings": settings.public(),
                "configuration_issues": issues,
                "llm_configuration_ready": not issues["llm"],
                "google_configuration_ready": not issues["google_translate"],
                "remote_credentials_verified": False,
                "network_requests": 0,
                "paid_requests": 0,
            }
            code = int(any(issues.values()))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError, KeyError, TypeError):
        print(
            "Translation preparation failed. Check input paths and .env settings; credentials are not printed."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
