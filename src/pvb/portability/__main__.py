"""Versioned cultural-portability review with the existing paid GapGPT budget guard."""

import argparse
import asyncio
import csv
import fcntl
import io
import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Annotated

import httpx
import yaml
from pydantic import Field

from pvb.extraction.backends.openrouter import ClassificationError
from pvb.extraction.gapgpt.metadata import preflight, read_billing
from pvb.extraction.gapgpt.settings import load_settings
from pvb.extraction.io import write_json, write_jsonl, write_text
from pvb.extraction.openrouter.accounting import BudgetExceeded, Journal
from pvb.extraction.openrouter.settings import ConfigurationError
from pvb.portability.backend import PortabilityBackend
from pvb.portability.report import write_report
from pvb.schemas.annotations import SampleAnnotation, utc_now
from pvb.schemas.common import StrictModel, canonical_json, sha256_text
from pvb.schemas.samples import CANONICAL_FIELDS, BenchmarkSample

ROOT = Path(__file__).resolve().parents[3]
LABELS = {
    "translation_portable": "قابل انتقال با ترجمهٔ وفادار",
    "localization_required": "نیازمند بومی‌سازی با نظارت انسانی",
    "uncertain": "نیازمند بررسی بیشتر",
}


class Config(StrictModel):
    schema_version: str = "1.0.0"
    root: str = ".."
    input: str
    output: str = "runs/portability"
    prompt: str
    prompt_version: str
    target_context: str = "fa-IR"
    explanation_language: str = "fa"
    expected_samples: Annotated[int, Field(gt=0)] = 54
    requests_per_minute: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 18.0
    prior_refusal_run: str | None = None


def load_inputs(config_path):
    config = Config.model_validate(yaml.safe_load(config_path.read_text()))
    root = (config_path.resolve().parent / config.root).resolve()
    input_path, output = (root / config.input).resolve(), (root / config.output).resolve()
    if input_path.is_relative_to(output) or any(
        output.is_relative_to(root / p) for p in ("data/raw", "data/normalized", "src", "configs")
    ):
        raise ConfigurationError("Portability output overlaps protected source paths.")
    rows = [json.loads(s) for s in input_path.read_text().splitlines() if s.strip()]
    if len(rows) != config.expected_samples or len({r["sample_id"] for r in rows}) != len(rows):
        raise ConfigurationError(
            "Portability input must contain the exact number of unique selected samples."
        )
    samples = []
    for row in rows:
        sample = BenchmarkSample.model_validate({key: row[key] for key in CANONICAL_FIELDS})
        annotation = SampleAnnotation.model_validate(row["annotation"])
        if (
            annotation.sample_id != sample.sample_id
            or row["classification_label"] != annotation.label
        ):
            raise ConfigurationError("Portability input classification provenance does not match.")
        if sample.dataset_split == "test":
            raise ConfigurationError("This review does not permit held-out test samples.")
        samples.append(sample)
    prompt = (root / config.prompt).read_text()
    if not prompt.startswith("Prompt version: " + config.prompt_version + "\n"):
        raise ConfigurationError("Portability prompt version differs from configuration.")
    return config, root, rows, samples, prompt


def prior_refusals(output, run_id, sample_ids):
    if run_id is None:
        return {}
    if not run_id.startswith("pvb-portability-") or "/" in run_id or ".." in run_id:
        raise ConfigurationError("Invalid prior portability run ID.")
    if not (output / run_id / "run.json").exists():
        raise ConfigurationError("Prior portability run does not exist.")
    refused = {}
    for event in Journal(output / run_id).events:
        if event.sample_id in sample_ids and (
            event.error_code == "provider_refusal"
            or (event.error_code == "provider_error" and event.http_status == 403)
        ):
            refused[event.sample_id] = {
                "prior_run_id": run_id,
                "prior_event_id": event.event_id,
                "reason": "provider_declined_sample; no cultural judgment inferred",
            }
    return refused


def reports(directory, run, rows, results, journal):
    ordered = [results[row["sample_id"]] for row in rows]
    write_jsonl(directory / "assessments.jsonl", ordered)
    for label in LABELS:
        write_jsonl(
            directory / (label + ".jsonl"),
            [r for r in ordered if (r.get("cultural_portability") or {}).get("label") == label],
        )
    write_jsonl(
        directory / "manual_review_required.jsonl",
        [r for r in ordered if r["portability_status"] == "manual_review_required"],
    )
    fields = [
        "sample_id",
        "dataset_name",
        "source_category",
        "original_prompt_source",
        "original_violence_category",
        "original_classification_label",
        "portability_status",
        "portability_label",
        "portability_title_fa",
        "dependency_dimensions",
        "source_context_summary",
        "rationale_fa",
        "localization_guidance_fa",
        "invariants_to_preserve",
        "evidence",
        "confidence",
        "requires_human_review",
        "translation_tested",
        "target_context",
        "provider",
        "model",
        "prompt_version",
        "original_prompt",
        "original_context",
        "source_metadata",
        "source_registry",
        "annotation_id",
        "run_id",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in ordered:
        d = row.get("cultural_portability") or {}
        label = d.get("label")
        record = {
            "sample_id": row["sample_id"],
            "dataset_name": row["dataset_name"],
            "source_category": row["source_category"],
            "original_prompt_source": row["source_metadata"].get("prompt_source"),
            "original_violence_category": row["category"],
            "original_classification_label": row["classification_label"],
            "portability_status": row["portability_status"],
            "portability_label": label,
            "portability_title_fa": LABELS.get(
                label,
                "ارجاع مستقیم به بازبین انسانی"
                if row["portability_status"] == "manual_review_required"
                else "ارزیابی کامل نشده",
            ),
            **{
                key: d.get(key)
                for key in (
                    "dependency_dimensions",
                    "source_context_summary",
                    "invariants_to_preserve",
                    "evidence",
                    "confidence",
                    "requires_human_review",
                    "translation_tested",
                )
            },
            "rationale_fa": d.get("rationale"),
            "localization_guidance_fa": d.get("localization_guidance"),
            "target_context": run["configuration"]["config"]["target_context"],
            "provider": "gapgpt",
            "model": run["configuration"]["settings"]["model"],
            "prompt_version": run["configuration"]["config"]["prompt_version"],
            "original_prompt": row["original_prompt"],
            "original_context": row["original_context"],
            "source_metadata": row["source_metadata"],
            "source_registry": row.get("source_registry", []),
            "annotation_id": row.get("portability_annotation_id"),
            "run_id": run["run_id"],
        }
        record["requires_human_review"] = True
        record["translation_tested"] = False
        writer.writerow(
            {
                key: canonical_json(value) if isinstance(value, (list, dict)) else value
                for key, value in record.items()
            }
        )
    write_text(directory / "portability_review.csv", buffer.getvalue())
    counts = Counter(
        (r.get("cultural_portability") or {}).get("label")
        for r in ordered
        if r.get("cultural_portability")
    )
    statuses = Counter(r["portability_status"] for r in ordered)
    cross = {}
    for category in sorted({r["category"] for r in ordered}):
        cross[category] = {
            label: sum(
                r["category"] == category
                and (r.get("cultural_portability") or {}).get("label") == label
                for r in ordered
            )
            for label in LABELS
        }
    summary = {
        "run_id": run["run_id"],
        "total_samples": len(ordered),
        "status_counts": dict(statuses),
        "label_counts": {label: counts[label] for label in LABELS},
        "label_titles_fa": LABELS,
        "by_original_violence_category": cross,
        "dependency_counts": dict(
            Counter(
                d
                for row in ordered
                for d in (row.get("cultural_portability") or {}).get("dependency_dimensions", [])
            )
        ),
        "target_context": run["configuration"]["config"]["target_context"],
        "model": run["configuration"]["settings"]["model"],
        "provider": "gapgpt",
        "prompt_version": run["configuration"]["config"]["prompt_version"],
        "requires_human_review": len(ordered),
        "model_assessments": statuses["assessed"],
        "manual_review_due_provider_refusal": statuses["manual_review_required"],
        "ground_truth": False,
        "actual_translations_evaluated": False,
        "usage": journal.summary(),
        "files": {
            "csv": "portability_review.csv",
            "jsonl": "assessments.jsonl",
            "html": "portability_report.html",
            "manual_review": "manual_review_required.jsonl",
        },
    }
    write_json(directory / "summary.json", summary)
    write_jsonl(
        directory / "request_events.jsonl", [e.model_dump(mode="json") for e in journal.events]
    )
    return summary


async def execute(config_path, *, confirmed=False, resume=None, client=None):
    if not confirmed:
        raise ConfigurationError("Portability review requires --confirm-paid-run.")
    config, root, rows, samples, prompt = load_inputs(config_path)
    settings = load_settings(root)
    settings.require_ready()
    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=False)
    output = (root / config.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        with (output / ".writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            metadata = await preflight(settings, client)
            code_root = Path(__file__).resolve().parents[1]
            frozen = {
                "config": config.model_dump(mode="json"),
                "settings": settings.public(),
                "input_sha256": sha256_text((root / config.input).read_text()),
                "prompt_sha256": sha256_text(prompt),
                "sample_ids": [s.sample_id for s in samples],
                "metadata": metadata.model_dump(mode="json", exclude={"retrieved_at"}),
                "implementation_sha256": sha256_text(
                    canonical_json(
                        {
                            str(p.relative_to(code_root)): sha256_text(p.read_text())
                            for p in sorted(code_root.rglob("*.py"))
                        }
                    )
                ),
            }
            if settings.redact(canonical_json(frozen)) != canonical_json(frozen):
                raise ConfigurationError("Sensitive configuration content rejected.")
            if resume:
                if not resume.startswith("pvb-portability-") or "/" in resume or ".." in resume:
                    raise ConfigurationError("Invalid portability run ID.")
                directory = output / resume
                run = json.loads((directory / "run.json").read_text())
                if run["configuration"] != frozen:
                    raise ConfigurationError(
                        "Resume requires identical input, prompt, implementation and settings."
                    )
            else:
                cap, used = await read_billing(settings, client)
                run = {
                    "schema_version": "1.0.0",
                    "run_id": "pvb-portability-" + uuid.uuid4().hex,
                    "started_at": utc_now(),
                    "configuration": frozen,
                    "status": "running",
                    "provider_account_cap_usd": cap,
                    "provider_usage_before_usd": used,
                }
                directory = output / run["run_id"]
                write_json(directory / "run.json", run)
                write_json(directory / "model_metadata.json", metadata.model_dump(mode="json"))
            journal = Journal(directory)
            backend = PortabilityBackend(
                settings=settings,
                metadata=metadata,
                client=client,
                prompt=prompt,
                taxonomy={
                    "version": "portability-1.0.0",
                    "target_context": config.target_context,
                    "explanation_language": config.explanation_language,
                },
                prompt_version=config.prompt_version,
                run_id=run["run_id"],
                journal=journal,
                cache_dir=output / "cache",
                requests_per_minute=config.requests_per_minute,
                paid_authorized=True,
            )
            result = {
                row["sample_id"]: {
                    **row,
                    "portability_status": "not_scheduled",
                    "cultural_portability": None,
                }
                for row in rows
            }
            by_id = {r["sample_id"]: r for r in rows}
            for sid, reason in prior_refusals(output, config.prior_refusal_run, set(by_id)).items():
                result[sid] = {
                    **by_id[sid],
                    "portability_status": "manual_review_required",
                    "cultural_portability": None,
                    "refusal_provenance": reason,
                }

            def assessed(sid, decision, event):
                return {
                    **by_id[sid],
                    "portability_status": "assessed",
                    "cultural_portability": decision.model_dump(mode="json"),
                    "portability_annotation_id": "pvb:portability:"
                    + sha256_text(canonical_json([run["run_id"], sid, event.event_id])),
                    "portability_run_id": run["run_id"],
                    "portability_event_id": event.event_id,
                }

            for event in sorted(journal.events, key=lambda e: (e.created_at, e.event_id)):
                if (
                    event.sample_id in result
                    and event.error_code == "provider_refusal"
                    and result[event.sample_id]["portability_status"] != "assessed"
                ):
                    result[event.sample_id] = {
                        **by_id[event.sample_id],
                        "portability_status": "manual_review_required",
                        "cultural_portability": None,
                        "refusal_provenance": {
                            "prior_run_id": run["run_id"],
                            "prior_event_id": event.event_id,
                        },
                    }
                if (
                    event.sample_id in result
                    and event.portability_decision
                    and event.outcome == "classified"
                ):
                    sample = samples[[s.sample_id for s in samples].index(event.sample_id)]
                    if event.fingerprint == backend.fingerprint(sample):
                        result[event.sample_id] = assessed(
                            event.sample_id, event.portability_decision, event
                        )
            try:
                for sample in samples:
                    sid = sample.sample_id
                    if result[sid]["portability_status"] in ("assessed", "manual_review_required"):
                        continue
                    try:
                        decision = await backend.classify(sample)
                        event = backend.last_events[sid]
                        result[sid] = assessed(sid, decision, event)
                    except BudgetExceeded:
                        result[sid] = {
                            **by_id[sid],
                            "portability_status": "not_scheduled",
                            "cultural_portability": None,
                            "reason": "budget_exhausted_or_unsettled_charge",
                        }
                    except ClassificationError as exc:
                        result[sid] = {
                            **by_id[sid],
                            "portability_status": "manual_review_required"
                            if exc.code == "provider_refusal"
                            else "failed",
                            "cultural_portability": None,
                            "reason": exc.code,
                        }
                    write_json(
                        directory / "checkpoints" / (sha256_text(sid) + ".json"), result[sid]
                    )
            finally:
                run["status"] = (
                    "completed"
                    if all(
                        r["portability_status"] in ("assessed", "manual_review_required")
                        for r in result.values()
                    )
                    else "partial"
                )
                run["completed_at"] = utc_now()
                try:
                    cap, used = await read_billing(settings, client)
                    run.update(provider_account_cap_usd=cap, provider_usage_after_usd=used)
                except ConfigurationError:
                    run["provider_usage_after_usd"] = None
                write_json(directory / "run.json", run)
                summary = reports(directory, run, rows, result, journal)
                summary.update(
                    provider_account_cap_usd=run["provider_account_cap_usd"],
                    provider_usage_before_usd=run["provider_usage_before_usd"],
                    provider_usage_after_usd=run["provider_usage_after_usd"],
                )
                write_json(directory / "summary.json", summary)
                write_report(directory)
            return summary
    finally:
        if owns_client:
            await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/portability.yaml")
    parser.add_argument("--mode", choices=["config-check", "run"], default="config-check")
    parser.add_argument("--confirm-paid-run", action="store_true")
    parser.add_argument("--resume")
    args = parser.parse_args()
    try:
        if args.mode == "config-check":
            config, root, rows, _samples, _prompt = load_inputs(args.config)
            settings = load_settings(root)
            settings.require_ready()
            summary = {
                "samples": len(rows),
                "target_context": config.target_context,
                "model": settings.model,
                "original_category_counts": dict(Counter(r["category"] for r in rows)),
                "paid_requests": 0,
            }
        else:
            summary = asyncio.run(
                execute(args.config, confirmed=args.confirm_paid_run, resume=args.resume)
            )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if "status_counts" in summary:
            processed = sum(
                summary["status_counts"].get(k, 0) for k in ("assessed", "manual_review_required")
            )
            return 0 if processed == summary["total_samples"] else 1
        return 0
    except ConfigurationError as exc:
        print(str(exc))
        return 1
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, httpx.HTTPError):
        print(
            "Portability review failed safely. Check configuration and local run artifacts; provider bodies and credentials are not printed."
        )
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Paid request reservations and completed assessments were retained.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
