"""Readable category exports retaining original benchmark provenance."""

import csv
import io
from collections import Counter, defaultdict

from pvb.extraction.io import write_jsonl, write_text
from pvb.schemas.common import canonical_json

CATEGORY_TITLES = {
    "unsafe_violence": "خشونت فیزیکی",
    "benign_violence_related": "بحث مجاز مرتبط با خشونت",
    "other_violence": "سایر خشونت‌ها (طبق تعریف منبع)",
    "out_of_scope": "سایر موضوعات خارج از دامنه",
    "unclassified": "طبقه‌بندی‌نشده",
}


def export_categories(
    directory,
    samples,
    annotations,
    results,
    run,
    *,
    sources=(),
    source_violence_categories=None,
    all_samples=None,
):
    if source_violence_categories is None:
        source_violence_categories = {"strongreject": ["Violence"], "harmbench": []}
    source_categories = {
        dataset: {category.strip().casefold() for category in categories}
        for dataset, categories in source_violence_categories.items()
    }
    annotation_map = {a.sample_id: a for a in annotations}
    registry = defaultdict(list)
    for source in sources:
        registry[source.dataset_name, source.dataset_split].append(source.model_dump(mode="json"))
    rows = []
    for sample in samples:
        result = results[sample.sample_id]
        annotation = annotation_map.get(sample.sample_id)
        source_declares_violence = (
            sample.source_category.strip().casefold()
            in source_categories.get(sample.dataset_name, set())
        )
        if result.status == "classified" and annotation is not None:
            category = (
                "other_violence"
                if annotation.label == "out_of_scope" and source_declares_violence
                else annotation.label
            )
        else:
            category = "unclassified"
        rows.append(
            {
                **sample.model_dump(mode="json"),
                "category": category,
                "category_title_fa": CATEGORY_TITLES[category],
                "classification_label": annotation.label if annotation else None,
                "source_declares_violence": source_declares_violence,
                "source_violence_rejected_by_definition": category == "other_violence",
                "processing_status": result.status,
                "processing_reason": result.reason,
                "annotation": annotation.model_dump(mode="json") if annotation else None,
                "classification_run": {
                    "run_id": run.run_id,
                    "provider": run.provider,
                    "model_identifier": run.model_identifier,
                    "prompt_version": run.prompt_version,
                },
                "source_registry": registry[sample.dataset_name, sample.dataset_split],
            }
        )
    write_jsonl(directory / "categorized_samples.jsonl", rows)
    for category in CATEGORY_TITLES:
        write_jsonl(
            directory / "categories" / (category + ".jsonl"),
            [row for row in rows if row["category"] == category],
        )

    fields = [
        "sample_id",
        "category",
        "category_title_fa",
        "classification_label",
        "processing_status",
        "dataset_name",
        "dataset_split",
        "source_record_id",
        "source_category",
        "source_declares_violence",
        "source_violence_rejected_by_definition",
        "functional_category",
        "source_tags",
        "source_metadata",
        "source_registry",
        "original_language",
        "original_prompt",
        "original_context",
        "raw_record_sha256",
        "prompt_sha256",
        "annotation_id",
        "subcategories",
        "confidence",
        "review_status",
        "run_id",
        "provider",
        "model_identifier",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        flat = {key: row.get(key) for key in fields}
        annotation = row["annotation"] or {}
        flat.update(
            {
                key: annotation.get(key)
                for key in (
                    "annotation_id",
                    "subcategories",
                    "confidence",
                    "review_status",
                )
            }
        )
        flat.update(
            {
                key: row["classification_run"][key]
                for key in (
                    "run_id",
                    "provider",
                    "model_identifier",
                )
            }
        )
        for key, value in flat.items():
            if isinstance(value, (list, dict)):
                flat[key] = canonical_json(value)
        writer.writerow(flat)
    write_text(directory / "categorized_samples.csv", buffer.getvalue())

    counts = Counter(row["category"] for row in rows)
    by_dataset = defaultdict(Counter)
    for row in rows:
        by_dataset[row["dataset_name"]][row["category"]] += 1
    source_coverage = defaultdict(Counter)
    selected_rows = {row["sample_id"]: row for row in rows}
    inventory = []
    for sample in samples if all_samples is None else all_samples:
        if sample.source_category.strip().casefold() in source_categories.get(
            sample.dataset_name, set()
        ):
            source_coverage[sample.dataset_name]["in_input"] += 1
            selected = selected_rows.get(sample.sample_id)
            inventory.append(
                {
                    **sample.model_dump(mode="json"),
                    "in_this_run": selected is not None,
                    "processing_status": selected["processing_status"]
                    if selected
                    else "not_selected",
                    "category": selected["category"] if selected else "unclassified",
                    "classification_label": selected["classification_label"] if selected else None,
                    "source_violence_rejected_by_definition": selected[
                        "source_violence_rejected_by_definition"
                    ]
                    if selected
                    else False,
                    "source_registry": registry[sample.dataset_name, sample.dataset_split],
                    "report_run_id": run.run_id,
                }
            )
    write_jsonl(directory / "source_violence_inventory.jsonl", inventory)
    for row in rows:
        if row["source_declares_violence"]:
            values = source_coverage[row["dataset_name"]]
            values["in_run"] += 1
            values[row["category"]] += 1
    return {
        "category_counts": {key: counts[key] for key in CATEGORY_TITLES},
        "category_titles_fa": CATEGORY_TITLES,
        "category_rules": {
            "other_violence": "classified out_of_scope AND original source category explicitly declares violence",
            "source_violence_categories": source_violence_categories,
            "source_metadata_is_not_ground_truth": True,
        },
        "category_counts_by_benchmark": {
            dataset: {key: values[key] for key in CATEGORY_TITLES}
            for dataset, values in sorted(by_dataset.items())
        },
        "category_exports": {
            "jsonl": "categorized_samples.jsonl",
            "csv": "categorized_samples.csv",
            "source_violence_inventory": "source_violence_inventory.jsonl",
            "buckets": {key: "categories/" + key + ".jsonl" for key in CATEGORY_TITLES},
        },
        "source_violence_coverage": {
            dataset: {
                "in_input": values["in_input"],
                "in_run": values["in_run"],
                "not_selected_in_run": values["in_input"] - values["in_run"],
                "rejected_by_our_definition": values["other_violence"],
                "accepted_unsafe": values["unsafe_violence"],
                "benign_related": values["benign_violence_related"],
                "unclassified_in_run": values["unclassified"],
            }
            for dataset, values in sorted(source_coverage.items())
        },
    }
