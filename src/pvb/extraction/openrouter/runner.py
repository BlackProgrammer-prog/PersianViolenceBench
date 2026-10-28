"""Paid-run gates, deterministic selection, crash recovery and NexoraDB persistence."""

import asyncio
import fcntl
import math
import uuid
from collections import Counter
from pathlib import Path

import httpx

from pvb.extraction.backends.llm import response_schema
from pvb.extraction.backends.openrouter import ClassificationError, OpenRouterBackend
from pvb.extraction.duplicates import duplicate_report
from pvb.extraction.io import write_json
from pvb.extraction.openrouter.accounting import BudgetExceeded, Journal
from pvb.extraction.openrouter.config import load_config
from pvb.extraction.openrouter.metadata import preflight
from pvb.extraction.openrouter.models import SampleResult
from pvb.extraction.openrouter.reports import generate_reports
from pvb.extraction.openrouter.sampling import select_pilot
from pvb.extraction.openrouter.settings import ConfigurationError
from pvb.extraction.taxonomy import load_taxonomy
from pvb.ingestion.export import load_jsonl
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import SampleAnnotation, utc_now
from pvb.schemas.common import canonical_json, sha256_text
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord
from pvb.schemas.validation import check_unique
from pvb.storage.nexoradb import NexoraRepository


def load_inputs(config_path):
    config, root = load_config(config_path)
    samples = load_jsonl(root / config.input, BenchmarkSample)
    check_unique(samples)
    sources = load_jsonl(root / config.sources, SourceRecord)
    # Reuse Phase 1 collection validation without publishing or changing files.
    from pvb.storage.memory import InMemoryRepository

    repo = InMemoryRepository()
    repo.ingest(sources, samples)
    taxonomy = load_taxonomy(root / config.taxonomy)
    prompt = (root / config.prompt).read_text(encoding="utf-8")
    if not prompt.startswith("Prompt version: " + config.prompt_version + "\n"):
        raise ConfigurationError("Prompt header and configured prompt_version differ.")
    return config, root, samples, sources, taxonomy, prompt


def workload(samples, payload_builder, metadata, output_tokens):
    # Explicit proxy only: native tokenizer usage is known only after generation.
    proxies = [math.ceil(len(canonical_json(payload_builder(s)).encode()) / 4) for s in samples]
    return {
        "sample_count": len(samples),
        "input_token_proxy": sum(proxies),
        "output_tokens_assumed_per_sample": output_tokens,
        "output_token_assumption": "configured maximum, not a measured average",
        "token_proxy_method": "ceil(payload UTF-8 bytes / 4); heuristic, not native tokenizer counts",
        "estimated_cost_usd": (
            sum(proxies) * metadata.input_usd_per_token
            + len(samples) * (output_tokens * metadata.output_usd_per_token + metadata.request_usd)
        )
        if metadata and metadata.input_usd_per_token is not None
        else None,
        "pricing_verified": metadata is not None and metadata.pricing_origin == "provider_metadata",
    }


def native_available(path, *, mutate=False):
    try:
        import nexoradb

        if nexoradb.__version__ != "0.2.1":
            return {"available": False, "reason": "native_version_not_verified"}
        if mutate:
            return {"available": NexoraRepository(path).engine.is_healthy(), "version": "0.2.1"}
        # Availability check without creating a database or modifying prior state.
        return {
            "available": True,
            "version": "0.2.1",
            "database_path_exists": path.exists(),
            "read_write_tested_this_command": False,
        }
    except (ImportError, OSError, RuntimeError):
        return {
            "available": False,
            "reason": "install_optional_nexoradb_extra_for_Python_3_10_Linux",
        }


def dry_run(config_path, settings):
    config, root, samples, sources, taxonomy, prompt = load_inputs(config_path)
    pilot, sampling = select_pilot(samples, config.seed)
    output = root / config.output / "dry-run"
    output.mkdir(parents=True, exist_ok=True)

    # Probe writability with an atomic report only; no request backend is created.
    def proxy_payload(sample):
        return {
            "messages": [
                {"role": "system", "content": prompt + canonical_json(taxonomy.model_dump())},
                {
                    "role": "user",
                    "content": canonical_json(
                        {
                            "original_prompt": sample.original_prompt,
                            "original_context": sample.original_context,
                        }
                    ),
                },
            ],
            "schema": response_schema(sample),
        }

    report = {
        "estimated_workload": workload(samples, proxy_payload, None, settings.max_output_tokens),
        "mode": "dry-run",
        "paid_requests": 0,
        "network_requests": 0,
        "configuration_ready": not settings.issues(),
        "configuration_issues": settings.issues(),
        "settings": settings.public(),
        "sample_count": len(samples),
        "source_count": len(sources),
        "source_split_counts": dict(
            Counter(s.dataset_name + "/" + s.dataset_split for s in samples)
        ),
        "canonical_schema_fields": len(BenchmarkSample.model_fields),
        "taxonomy_version": taxonomy.version,
        "prompt_version": config.prompt_version,
        "prompt_sha256": sha256_text(prompt),
        "storage": native_available(root / config.database, mutate=True),
        "output": str(output),
        "pilot_sampling": sampling,
        "pilot_sample_ids": [s.sample_id for s in pilot],
        "duplicates": duplicate_report(samples),
        "model_verified_remotely": False,
        "estimated_cost_usd": None,
        "pricing_status": "unknown_until_remote_metadata_preflight",
        "input_dataset_fingerprint": sha256_text((root / config.input).read_text(encoding="utf-8")),
    }
    write_json(output / "dry_run_report.json", report)
    return report


def annotation_from_event(event, run):
    return SampleAnnotation(
        **event.decision.model_dump(),
        annotation_id="pvb:annotation:" + sha256_text(canonical_json([run.run_id, event.event_id])),
        sample_id=event.sample_id,
        review_status="pending",
        annotation_method="llm",
        annotator_id=run.provider + ":" + run.model_identifier,
        annotation_run_id=run.run_id,
        created_at=event.created_at,
        updated_at=event.created_at,
    )


def save_annotation(directory, event, run, repository):
    annotation = annotation_from_event(event, run)
    path = directory / "annotations" / (sha256_text(annotation.sample_id) + ".json")
    if path.exists() and SampleAnnotation.model_validate_json(path.read_text()) != annotation:
        raise ValueError("annotation history conflict")
    write_json(path, annotation.model_dump(mode="json"))
    repository.add_annotations([annotation])
    return annotation


async def execute(
    config_path: Path,
    settings,
    *,
    mode: str,
    confirm_paid: bool = False,
    confirm_full: bool = False,
    resume: str | None = None,
    retry_uncertain: bool = False,
    client: httpx.AsyncClient | None = None,
    repository=None,
    metadata_override=None,
):
    if mode not in ("pilot", "full", "smoke", "selected"):
        raise ConfigurationError("Paid execution mode must be pilot, full or smoke.")
    if (mode == "full" and not confirm_full) or (mode != "full" and not confirm_paid):
        raise ConfigurationError(
            "Full mode requires --confirm-full-run; pilot/smoke requires --confirm-paid-run."
        )
    settings.require_ready()
    config, root, all_samples, sources, taxonomy, prompt = load_inputs(config_path)
    if mode == "selected":
        ids = config.selected_sample_ids
        if not ids or len(set(ids)) != len(ids):
            raise ConfigurationError(
                "Selected mode requires a nonempty, unique selected_sample_ids list."
            )
        lookup = {s.sample_id: s for s in all_samples}
        if any(sid not in lookup for sid in ids):
            raise ConfigurationError("Selected sample ID is absent from the canonical input.")
        samples = [lookup[sid] for sid in ids]
        if any(s.dataset_split == "test" for s in samples):
            raise ConfigurationError(
                "Selected mode does not permit held-out test samples; use the frozen full workflow."
            )
        selection = {"mode": "selected", "sample_count": len(samples)}
    elif mode == "full":
        if len(all_samples) != 713:
            raise ConfigurationError(
                "Full benchmark run requires the verified 713-sample snapshot."
            )
        samples, selection = all_samples, {"mode": "full", "sample_count": len(all_samples)}
    else:
        samples, selection = select_pilot(all_samples, config.seed)
        if mode == "smoke":
            samples = samples[:1]
            selection = {**selection, "mode": "smoke", "sample_count": 1}
    output = (root / config.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".paid-writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owns_client = client is None
        client = client or httpx.AsyncClient(follow_redirects=False)
        try:
            if repository is None and not native_available(root / config.database)["available"]:
                raise ConfigurationError(
                    "Verified NexoraDB is unavailable. Install with uv sync --extra nexoradb using Python 3.10 on Linux x86_64."
                )
            backend_class = OpenRouterBackend
            provider_preflight = preflight
            if settings.provider == "gapgpt":
                from pvb.extraction.backends.gapgpt import GapGPTBackend
                from pvb.extraction.gapgpt.metadata import preflight as gapgpt_preflight

                backend_class = GapGPTBackend
                provider_preflight = gapgpt_preflight
            metadata = metadata_override or await provider_preflight(settings, client)
            repository = (
                repository if repository is not None else NexoraRepository(root / config.database)
            )
            # Preserve annotations from all prior methods/runs.
            repository.ingest(sources, all_samples)
            metadata_stable = metadata.model_dump(mode="json", exclude={"retrieved_at"})
            hashes = {
                key: sha256_text((root / getattr(config, key)).read_text(encoding="utf-8"))
                for key in ("input", "sources", "taxonomy", "prompt")
            }
            hashes["extraction_config"] = sha256_text(config_path.read_text(encoding="utf-8"))
            hashes["public_settings"] = sha256_text(canonical_json(settings.public()))
            hashes["schema"] = sha256_text(canonical_json(response_schema()))
            implementation_root = Path(__file__).parents[2]
            hashes["implementation"] = sha256_text(
                canonical_json(
                    {
                        str(p.relative_to(implementation_root)): sha256_text(p.read_text())
                        for p in sorted(implementation_root.rglob("*.py"))
                    }
                )
            )
            frozen = {
                "mode": mode,
                "settings": settings.public(),
                "paths_and_controls": config.model_dump(mode="json"),
                "hashes": hashes,
                "model_metadata": metadata_stable,
                "selected_sample_ids": [s.sample_id for s in samples],
                "selection": selection,
                "method_frozen_before_requests": True,
                "schema_version": "1.0.0",
            }
            if settings.redact(canonical_json(frozen)) != canonical_json(frozen):
                raise ConfigurationError(
                    "Sensitive content found in configuration metadata; run refused."
                )
            if resume:
                if not resume.startswith(settings.run_prefix) or "/" in resume or ".." in resume:
                    raise ConfigurationError("Invalid Phase 3 resume run ID.")
                directory = output / resume
                run = AnnotationRun.model_validate_json((directory / "run.json").read_text())
                frozen["model_metadata_retrieved_at"] = run.configuration[
                    "model_metadata_retrieved_at"
                ]
                if run.configuration != frozen:
                    raise ConfigurationError(
                        "Resume requires identical data, model metadata, prompt, code and configuration. Create a new run instead."
                    )
            else:
                frozen["model_metadata_retrieved_at"] = metadata.retrieved_at
                run = AnnotationRun(
                    run_id=settings.run_prefix + uuid.uuid4().hex,
                    method="llm",
                    model_identifier=settings.model,
                    provider=settings.provider,
                    prompt_version=config.prompt_version,
                    configuration=frozen,
                    input_dataset_fingerprint=hashes["input"],
                    started_at=utc_now(),
                    status="running",
                    sample_count=len(samples),
                )
                directory = output / run.run_id
                write_json(directory / "run.json", run.model_dump(mode="json"))
                write_json(directory / "config.json", frozen)
                write_json(directory / "model_metadata.json", metadata.model_dump(mode="json"))
            repository.save_run(run)
            journal = Journal(directory, repository)
            backend = backend_class(
                settings=settings,
                metadata=metadata,
                client=client,
                prompt=prompt,
                taxonomy=taxonomy.model_dump(),
                prompt_version=config.prompt_version,
                run_id=run.run_id,
                journal=journal,
                cache_dir=root / config.cache,
                requests_per_minute=config.requests_per_minute,
                paid_authorized=True,
            )
            results = {
                s.sample_id: SampleResult(
                    sample_id=s.sample_id,
                    fingerprint=backend.fingerprint(s),
                    status="not_scheduled",
                    reason="not_started",
                )
                for s in samples
            }
            lookup = {s.sample_id: s for s in samples}
            # Recover successful billed calls even if checkpoint or DB write was interrupted.
            for event in sorted(journal.events, key=lambda e: (e.created_at, e.event_id)):
                if event.sample_id not in lookup or event.fingerprint != backend.fingerprint(
                    lookup[event.sample_id]
                ):
                    raise ConfigurationError(
                        "Request journal has invalid sample/fingerprint provenance."
                    )
                if event.outcome in ("classified", "abstained"):
                    annotation = (
                        save_annotation(directory, event, run, repository)
                        if event.outcome == "classified"
                        else None
                    )
                    results[event.sample_id] = SampleResult(
                        sample_id=event.sample_id,
                        fingerprint=event.fingerprint,
                        status=event.outcome,
                        annotation_id=annotation.annotation_id if annotation else None,
                        reason=event.decision.rationale if event.outcome == "abstained" else None,
                        event_id=event.event_id,
                    )
            settled_ids = {
                e.request_id
                for e in journal.events
                if e.kind == "settled" and e.outcome != "cancelled"
            }
            uncertain = {
                e.sample_id
                for e in journal.events
                if e.kind == "reserved" and e.request_id not in settled_ids
            }
            for sid in uncertain:
                if results[sid].status not in ("classified", "abstained") and not retry_uncertain:
                    results[sid] = SampleResult(
                        sample_id=sid,
                        fingerprint=backend.fingerprint(lookup[sid]),
                        status="interrupted",
                        reason="uncertain_prior_charge_requires_explicit_retry_uncertain",
                    )
            queue = asyncio.Queue()
            for s in samples:
                if results[s.sample_id].status == "not_scheduled":
                    queue.put_nowait(s)
            interrupted = False

            async def worker():
                while not queue.empty() and not backend.budget.stopped and not backend.stop_code:
                    sample = queue.get_nowait()
                    sid, fingerprint = sample.sample_id, backend.fingerprint(sample)
                    try:
                        decision = await backend.classify(sample)
                        event = backend.last_events[sid]
                        annotation = (
                            save_annotation(directory, event, run, repository) if decision else None
                        )
                        result = SampleResult(
                            sample_id=sid,
                            fingerprint=fingerprint,
                            status="classified" if decision else "abstained",
                            annotation_id=annotation.annotation_id if annotation else None,
                            reason=event.decision.rationale if not decision else None,
                            event_id=event.event_id,
                        )
                    except BudgetExceeded:
                        result = SampleResult(
                            sample_id=sid,
                            fingerprint=fingerprint,
                            status="not_scheduled",
                            reason="budget_exhausted",
                        )
                    except ClassificationError as exc:
                        event = backend.last_events.get(sid)
                        result = SampleResult(
                            sample_id=sid,
                            fingerprint=fingerprint,
                            status="failed",
                            reason=exc.code,
                            event_id=event.event_id if event else None,
                        )
                    except asyncio.CancelledError:
                        result = SampleResult(
                            sample_id=sid,
                            fingerprint=fingerprint,
                            status="interrupted",
                            reason="interrupted",
                        )
                        results[sid] = result
                        write_json(
                            directory / "checkpoints" / (sha256_text(sid) + ".json"),
                            result.model_dump(mode="json"),
                        )
                        raise
                    except (OSError, ValueError, RuntimeError):
                        backend.stop_code = "local_processing_error"
                        result = SampleResult(
                            sample_id=sid,
                            fingerprint=fingerprint,
                            status="failed",
                            reason="local_processing_error",
                        )
                    results[sid] = result
                    write_json(
                        directory / "checkpoints" / (sha256_text(sid) + ".json"),
                        result.model_dump(mode="json"),
                    )
                    queue.task_done()

            workers = [asyncio.create_task(worker()) for _ in range(settings.concurrency)]
            try:
                await asyncio.gather(*workers)
            except asyncio.CancelledError:
                interrupted = True
                for task in workers:
                    task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
            finally:
                counts = Counter(r.status for r in results.values())
                terminal = counts["classified"] + counts["abstained"] == len(samples)
                finished = run.model_dump()
                finished.update(
                    status="completed" if terminal else "partial",
                    completed_at=run.completed_at if run.status == "completed" else utc_now(),
                    success_count=counts["classified"],
                    abstention_count=counts["abstained"],
                    failure_count=len(samples) - counts["classified"] - counts["abstained"],
                )
                run = AnnotationRun.model_validate(finished)
                repository.save_run(run)
                write_json(directory / "run.json", run.model_dump(mode="json"))
                rules = (
                    load_jsonl(root / config.rules_annotations, SampleAnnotation)
                    if (root / config.rules_annotations).exists()
                    else []
                )
                report = generate_reports(
                    directory,
                    samples,
                    all_samples,
                    run,
                    results,
                    journal,
                    rule_annotations=rules,
                    threshold=config.low_confidence_threshold,
                    metadata=metadata,
                    sources=sources,
                    source_violence_categories=config.source_violence_categories,
                )
            if interrupted:
                raise asyncio.CancelledError
            return report
        finally:
            if owns_client:
                await client.aclose()
