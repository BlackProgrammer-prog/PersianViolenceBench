"""Reconciled Phase 3 reports and Phase 2-compatible human-review CSV."""

from collections import Counter
from pathlib import Path

from pvb.extraction.duplicates import duplicate_report
from pvb.extraction.io import write_json, write_jsonl
from pvb.extraction.openrouter.categories import export_categories
from pvb.extraction.quality import audit, grouped_summary
from pvb.extraction.review import export_review
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.common import sha256_text


def review_priorities(samples, annotations, results, all_samples, rule_annotations, threshold):
    annotations = {a.sample_id: a for a in annotations}
    rules = {a.sample_id: a for a in rule_annotations if a.annotation_method == "rule_based"}
    duplicate = duplicate_report(all_samples)
    cross_split = {
        s["sample_id"]
        for group in duplicate["exact_groups"]
        if group["cross_split"]
        for s in group["samples"]
    }
    priorities = []
    for s in samples:
        a, rule = annotations.get(s.sample_id), rules.get(s.sample_id)
        reasons = []
        if a is None:
            reasons.append("unresolved_or_api_failure")
        else:
            if a.confidence < threshold:
                reasons.append("low_confidence")
            if a.intent == "ambiguous":
                reasons.append("ambiguous_intent")
            if a.risk_severity in ("high", "critical"):
                reasons.append("high_severity")
            if rule and (a.label, set(a.subcategories)) != (rule.label, set(rule.subcategories)):
                reasons.append("rule_llm_disagreement")
            source_violence = "violence" in s.source_category.casefold()
            if source_violence != (a.label == "unsafe_violence"):
                reasons.append("source_category_label_difference_not_ground_truth")
        if s.sample_id in cross_split:
            reasons.append("cross_split_duplicate")
        priorities.append(
            {
                "sample_id": s.sample_id,
                "priority_score": len(reasons),
                "reasons": reasons,
                "processing_status": results[s.sample_id].status,
            }
        )
    return sorted(priorities, key=lambda r: (-r["priority_score"], r["sample_id"]))


def generate_reports(
    directory: Path,
    samples,
    all_samples,
    run,
    results,
    journal,
    *,
    rule_annotations=None,
    threshold=0.7,
    metadata=None,
    sources=(),
    source_violence_categories=None,
):
    annotations = []
    for path in sorted((directory / "annotations").glob("*.json")):
        annotations.append(SampleAnnotation.model_validate_json(path.read_text()))
    selected_ids = {s.sample_id for s in samples}
    if any(
        a.sample_id not in selected_ids or a.annotation_run_id != run.run_id for a in annotations
    ):
        raise ValueError("annotation/run/sample provenance mismatch")
    if len({a.sample_id for a in annotations}) != len(annotations):
        raise ValueError("multiple selected annotations for a sample")
    classified_ids = {s for s, row in results.items() if row.status == "classified"}
    if classified_ids != {a.sample_id for a in annotations}:
        raise ValueError("annotation and result counts do not reconcile")
    missing = selected_ids - classified_ids
    qc = audit(samples, annotations, [run], accounted_unclassified=missing)
    groups = grouped_summary(samples, annotations)
    processing = Counter(row.status for row in results.values())
    if sum(processing.values()) != len(samples) or set(results) != selected_ids:
        raise ValueError("processing counts do not reconcile")
    usage = journal.summary()
    latencies = usage["latencies_seconds"]
    report = {
        "run_id": run.run_id,
        "backend": run.provider,
        "ground_truth": False,
        "total_sample_count": len(samples),
        "processed_sample_count": sum(processing[k] for k in ("classified", "abstained", "failed")),
        "successfully_classified": processing["classified"],
        "abstentions": processing["abstained"],
        "failed_samples": processing["failed"],
        "api_failed_request_attempts": usage["failed_requests"],
        "not_scheduled": processing["not_scheduled"],
        "interrupted": processing["interrupted"],
        "processing_counts": dict(processing),
        "label_counts": {
            k: groups["classification_label"].get(k, 0)
            for k in ("unsafe_violence", "benign_violence_related", "out_of_scope")
        },
        "subcategory_counts": {
            k: groups["violence_subcategory"].get(k, 0) for k in ("V1", "V2", "V3", "V4", "V5")
        },
        "selected_source_counts": dict(Counter(s.dataset_name for s in samples)),
        "selected_split_counts": dict(Counter(s.dataset_split for s in samples)),
        "grouped_annotations": groups,
        "model_identifier": run.model_identifier,
        "prompt_version": run.prompt_version,
        "usage": usage,
        "mean_request_latency_seconds": sum(latencies) / len(latencies) if latencies else None,
        "human_review_required": len(samples),
        "approved_human_count": 0,
        "quality": qc,
        "frozen_configuration": run.configuration,
        "metadata_is_not_live_generation_proof": True,
    }
    report.update(
        export_categories(
            directory,
            samples,
            annotations,
            results,
            run,
            sources=sources,
            source_violence_categories=source_violence_categories,
            all_samples=all_samples,
        )
    )
    priorities = review_priorities(
        samples, annotations, results, all_samples, rule_annotations or [], threshold
    )
    lookup = {s.sample_id: s for s in samples}
    write_jsonl(directory / "annotations.jsonl", [a.model_dump(mode="json") for a in annotations])
    write_jsonl(directory / "annotation_runs.jsonl", [run.model_dump(mode="json")])
    write_jsonl(
        directory / "results.jsonl", [results[s.sample_id].model_dump(mode="json") for s in samples]
    )
    write_jsonl(
        directory / "failures.jsonl",
        [e.model_dump(mode="json") for e in journal.events if e.outcome in ("failed", "cancelled")],
    )
    write_jsonl(
        directory / "request_events.jsonl", [e.model_dump(mode="json") for e in journal.events]
    )
    write_jsonl(directory / "review_priorities.jsonl", priorities)
    # Preserve CSVs that may contain human work; changed proposals get a new file.
    staging = directory / ".review-staging.csv"
    export_review(staging, [lookup[r["sample_id"]] for r in priorities], annotations)
    generated = staging.read_bytes().decode("utf-8")
    staging.unlink()
    review_path = directory / "review_queue.csv"
    if review_path.exists() and review_path.read_bytes().decode("utf-8") != generated:
        review_path = directory / ("review_queue." + sha256_text(generated)[:16] + ".csv")
    if not review_path.exists():
        from pvb.extraction.io import write_text

        write_text(review_path, generated)
    report["review_csv"] = review_path.name
    write_json(directory / "usage.json", usage)
    write_json(
        directory / "cost_report.json",
        {
            "budget_limit_usd": run.configuration["settings"]["max_cost_usd"],
            "provider_reported_sum_usd": usage["reported_cost_usd"],
            "actual_cost_complete": usage["actual_cost_complete"],
            "token_pricing_estimate_sum_usd": usage["estimated_cost_usd"],
            "accounted_cost_usd": usage["accounted_cost_usd"],
            "outstanding_reservations_usd": usage["outstanding_reservations_usd"],
            "pricing": metadata.model_dump(mode="json")
            if metadata
            else run.configuration.get("model_metadata"),
            "limitation": (
                "Client-side reservations reduce risk but are not an absolute no-overspend guarantee. "
                "Routing price caps apply only to OpenRouter, not GapGPT. Operator-configured "
                "rates are not provider-verified billing rates. Unreported/interrupted charges "
                "retain full reservations."
            ),
        },
    )
    write_json(directory / "classification_report.json", report)
    return report
