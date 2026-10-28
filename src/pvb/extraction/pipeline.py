"""Run provisional extraction with immutable attempts, checkpoints and explicit abstentions."""

import argparse
import asyncio
import fcntl
import json
import uuid
from collections import Counter
from pathlib import Path

from pvb.extraction.backends.llm import PROMPT_VERSION, HTTPTransport, LLMBackend
from pvb.extraction.backends.rule_based import RuleBasedBackend
from pvb.extraction.config import load_config
from pvb.extraction.duplicates import duplicate_report
from pvb.extraction.io import write_json, write_jsonl
from pvb.extraction.quality import audit, grouped_summary
from pvb.extraction.taxonomy import load_taxonomy
from pvb.ingestion.export import load_jsonl
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import SampleAnnotation, utc_now
from pvb.schemas.common import canonical_json, sha256_text
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.validation import check_unique


def annotation_for(sample, decision, run, identifier):
    timestamp = utc_now()
    return SampleAnnotation(
        **decision.model_dump(),
        annotation_id="pvb:annotation:"
        + sha256_text(canonical_json([run.run_id, sample.sample_id, identifier])),
        sample_id=sample.sample_id,
        review_status="pending",
        annotation_method=run.method,
        annotator_id=identifier,
        annotation_run_id=run.run_id,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def extract(
    config_path: Path,
    *,
    backend_name: str | None = None,
    resume: str | None = None,
    backend_override=None,
) -> dict:
    config, root = load_config(config_path)
    name = backend_name or config.backend
    input_path, output = (root / config.input).resolve(), (root / config.output).resolve()
    # Never publish over canonical/raw inputs, even with a malicious configuration.
    if (
        input_path.is_relative_to(output)
        or output.is_relative_to(input_path.parent)
        or output.is_relative_to(root / "data/raw")
    ):
        raise ValueError("output overlaps protected input/raw paths")
    samples = load_jsonl(input_path, BenchmarkSample)
    check_unique(samples)
    if any(s.dataset_split == "test" for s in samples) and not config.method_frozen:
        raise ValueError("freeze extraction method before applying to held-out test")
    taxonomy = load_taxonomy(root / config.taxonomy)
    if (
        name == "llm"
        and not backend_override
        and not (config.llm.provider and config.llm.model and config.llm.endpoint)
    ):
        raise ValueError("LLM backend unavailable: configure real provider, model and endpoint")
    prompt = (root / config.llm.prompt).read_text(encoding="utf-8") if name == "llm" else None
    # Fingerprint the complete extraction implementation, not only a version label.
    code_root = Path(__file__).parent.parent
    code_fingerprint = sha256_text(
        canonical_json(
            {
                str(p.relative_to(code_root)): sha256_text(p.read_text())
                for p in sorted(code_root.rglob("*.py"))
            }
        )
    )
    configuration = {
        "extraction": config.model_dump(mode="json"),
        "selected_backend": name,
        "taxonomy_sha256": sha256_text(canonical_json(taxonomy.model_dump())),
        "implementation_sha256": code_fingerprint,
        "prompt_sha256": sha256_text(prompt) if prompt else None,
        "override_identifier": backend_override.identifier if backend_override else None,
    }
    fingerprint = sha256_text(input_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if resume:
            if not resume.startswith("pvb-run-") or "/" in resume or ".." in resume:
                raise ValueError("invalid resume run ID")
            run_dir = output / "runs" / resume
            run = AnnotationRun.model_validate_json((run_dir / "run.json").read_text())
            if run.configuration != configuration or run.input_dataset_fingerprint != fingerprint:
                raise ValueError(
                    "resume requires identical input, implementation and configuration"
                )
        else:
            run = AnnotationRun(
                run_id="pvb-run-" + uuid.uuid4().hex,
                method="llm" if name == "llm" else "rule_based",
                configuration=configuration,
                input_dataset_fingerprint=fingerprint,
                started_at=utc_now(),
                status="running",
                sample_count=len(samples),
                model_identifier=config.llm.model if name == "llm" else None,
                model_version=config.llm.model_version if name == "llm" else None,
                provider=config.llm.provider if name == "llm" else None,
                prompt_version=PROMPT_VERSION if name == "llm" else None,
            )
            run_dir = output / "runs" / run.run_id
            write_json(run_dir / "run.json", run.model_dump(mode="json"))
            write_json(
                run_dir / "run_events" / (uuid.uuid4().hex + ".json"), run.model_dump(mode="json")
            )
        backend = backend_override or (
            RuleBasedBackend()
            if name == "rules"
            else LLMBackend(
                transport=HTTPTransport(config.llm.endpoint, config.llm.credential_env),
                model=config.llm.model,
                provider=config.llm.provider,
                prompt=prompt,
                taxonomy=taxonomy.model_dump(),
                cache_dir=output / "cache",
                temperature=config.llm.temperature,
                timeout=config.llm.timeout,
                retries=config.llm.retries,
                requests_per_minute=config.llm.requests_per_minute,
                concurrency=config.concurrency,
                cache_namespace=sha256_text(canonical_json(configuration)),
            )
        )
        if backend.method != run.method:
            raise ValueError("backend method does not match run")
        semaphore = asyncio.Semaphore(config.concurrency)

        async def one(sample):
            path = run_dir / "checkpoints" / (sha256_text(sample.sample_id) + ".json")
            if path.exists():
                row = json.loads(path.read_text())
                if row["sample_id"] != sample.sample_id or row["status"] not in (
                    "classified",
                    "abstained",
                    "failed",
                ):
                    raise ValueError("invalid checkpoint")
                if row["annotation"]:
                    a = SampleAnnotation.model_validate(row["annotation"])
                    if a.sample_id != sample.sample_id or a.annotation_run_id != run.run_id:
                        raise ValueError("checkpoint provenance mismatch")
                # Failed calls may be retried on resume; successful attempts are immutable.
                if row["status"] != "failed":
                    return row
            async with semaphore:
                try:
                    decision = await backend.classify(sample)
                    annotation = (
                        annotation_for(sample, decision, run, backend.identifier)
                        if decision
                        else None
                    )
                    row = {
                        "sample_id": sample.sample_id,
                        "status": "classified" if annotation else "abstained",
                        "annotation": annotation.model_dump(mode="json") if annotation else None,
                        "reason": None
                        if annotation
                        else "Backend abstained: unsupported or ambiguous request/context.",
                    }
                except (
                    OSError,
                    ValueError,
                    RuntimeError,
                    KeyError,
                    TypeError,
                    TimeoutError,
                ) as exc:
                    # Exception messages may contain provider responses or secrets. Store type only.
                    row = {
                        "sample_id": sample.sample_id,
                        "status": "failed",
                        "annotation": None,
                        "reason": type(exc).__name__,
                    }
                # Preserve every completed backend call, including failures retried later.
                write_json(
                    run_dir
                    / "attempts"
                    / sha256_text(sample.sample_id)
                    / (uuid.uuid4().hex + ".json"),
                    row,
                )
                write_json(path, row)
                return row

        rows = []
        for start in range(0, len(samples), config.batch_size):
            rows.extend(
                await asyncio.gather(*(one(s) for s in samples[start : start + config.batch_size]))
            )
        counts = Counter(r["status"] for r in rows)
        annotations = [
            SampleAnnotation.model_validate(r["annotation"]) for r in rows if r["annotation"]
        ]
        missing = [r for r in rows if not r["annotation"]]
        finished = run.model_dump()
        finished.update(
            success_count=counts["classified"],
            failure_count=counts["failed"],
            abstention_count=counts["abstained"],
            completed_at=run.completed_at if run.status == "completed" else utc_now(),
            status="partial" if counts["failed"] else "completed",
        )
        run = AnnotationRun.model_validate(finished)
        qc = audit(
            samples, annotations, [run], accounted_unclassified={r["sample_id"] for r in missing}
        )
        duplicates = duplicate_report(samples, **config.duplicates.model_dump())
        grouped = grouped_summary(samples, annotations)
        report = {
            "run_id": run.run_id,
            "taxonomy_id": taxonomy.taxonomy_id,
            "taxonomy_version": taxonomy.version,
            "input_dataset_fingerprint": fingerprint,
            "configuration": configuration,
            "sample_count": len(samples),
            "classified_count": len(annotations),
            "unclassified_count": len(missing),
            "abstention_count": counts["abstained"],
            "failure_count": counts["failed"],
            "review_queue_size": len(samples),
            "provisional_label_distribution": grouped["classification_label"],
            "coverage": len(annotations) / len(samples) if samples else 0.0,
            "uncertain_count": len(missing)
            + sum(a.intent == "ambiguous" or a.confidence == 0.0 for a in annotations),
            "grouped_summary": grouped,
            "quality": qc,
            "unclassified_by_source_split": dict(
                Counter(
                    f"{s.dataset_name}/{s.dataset_split}"
                    for s in samples
                    if s.sample_id in {r["sample_id"] for r in missing}
                )
            ),
            "ground_truth": False,
        }
        lookup = {s.sample_id: s for s in samples}
        queue = [{"sample": lookup[r["sample_id"]].model_dump(mode="json"), **r} for r in rows]
        artifacts = {
            "annotations.jsonl": [a.model_dump(mode="json") for a in annotations],
            "annotation_runs.jsonl": [run.model_dump(mode="json")],
            "unclassified.jsonl": missing,
            "classification_results.jsonl": rows,
            "review_queue.jsonl": queue,
        }
        for label in taxonomy.labels:
            artifacts[label + ".jsonl"] = [
                {
                    "sample": lookup[a.sample_id].model_dump(mode="json"),
                    "annotation": a.model_dump(mode="json"),
                }
                for a in annotations
                if a.label == label
            ]
        # Archive each execution; top-level artifacts are only the latest view.
        for directory in (run_dir, output):
            for filename, data in artifacts.items():
                write_jsonl(directory / filename, data)
            write_json(directory / "duplicate_report.json", duplicates)
            write_json(directory / "quality_report.json", qc)
            write_json(directory / "extraction_report.json", report)
        write_json(run_dir / "run.json", run.model_dump(mode="json"))
        event = run.model_dump(mode="json")
        event_path = run_dir / "run_events" / (sha256_text(canonical_json(event)) + ".json")
        if not event_path.exists():
            write_json(event_path, event)
        return report


def main(argv=None):
    import sys

    raw_arguments = sys.argv[1:] if argv is None else list(argv)
    if any(arg in ("--backend=openrouter", "--backend=gapgpt") for arg in raw_arguments) or any(
        value == "--backend"
        and index + 1 < len(raw_arguments)
        and raw_arguments[index + 1] in ("openrouter", "gapgpt")
        for index, value in enumerate(raw_arguments)
    ):
        from pvb.extraction.openrouter.cli import main as openrouter_main

        return openrouter_main(raw_arguments)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/extraction.yaml"))
    parser.add_argument("--backend", choices=["rules", "llm", "openrouter", "gapgpt"])
    parser.add_argument("--resume", help="Existing run ID; identical configuration/input required")
    args, remaining = parser.parse_known_args(argv)
    if remaining:
        parser.error("unrecognized arguments: " + " ".join(remaining))
    try:
        report = asyncio.run(extract(args.config, backend_name=args.backend, resume=args.resume))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Extraction failed: {exc}")
        return 1
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "run_id",
                    "sample_count",
                    "provisional_label_distribution",
                    "unclassified_count",
                    "abstention_count",
                    "failure_count",
                    "review_queue_size",
                )
            }
        )
    )
    return 0 if report["quality"]["passed"] and not report["failure_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
