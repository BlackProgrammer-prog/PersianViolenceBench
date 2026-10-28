"""Local validation, metadata, cost estimates and explicitly authorized execution."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from pvb.extraction.io import write_json
from pvb.extraction.openrouter.accounting import Journal
from pvb.extraction.openrouter.metadata import preflight
from pvb.extraction.openrouter.models import ModelMetadata, SampleResult
from pvb.extraction.openrouter.reports import generate_reports
from pvb.extraction.openrouter.runner import dry_run, execute, load_inputs, workload
from pvb.extraction.openrouter.settings import ConfigurationError, load_settings
from pvb.schemas.annotation_runs import AnnotationRun


def rebuild_reports(config_path: Path, run_id: str):
    config, root, all_samples, sources, _, _ = load_inputs(config_path)
    if not run_id.startswith(("pvb-or-", "pvb-gap-")) or "/" in run_id or ".." in run_id:
        raise ConfigurationError("Invalid run ID.")
    directory = root / config.output / run_id
    run = AnnotationRun.model_validate_json((directory / "run.json").read_text())
    ids = run.configuration["selected_sample_ids"]
    lookup = {s.sample_id: s for s in all_samples}
    samples = [lookup[s] for s in ids]
    results = {
        r.sample_id: r
        for r in [
            SampleResult.model_validate_json(line)
            for line in (directory / "results.jsonl").read_text().splitlines()
        ]
    }
    metadata = ModelMetadata.model_validate_json((directory / "model_metadata.json").read_text())
    from pvb.ingestion.export import load_jsonl
    from pvb.schemas.annotations import SampleAnnotation

    rules = (
        load_jsonl(root / config.rules_annotations, SampleAnnotation)
        if (root / config.rules_annotations).exists()
        else []
    )
    return generate_reports(
        directory,
        samples,
        all_samples,
        run,
        results,
        Journal(directory),
        metadata=metadata,
        rule_annotations=rules,
        threshold=config.low_confidence_threshold,
        sources=sources,
        source_violence_categories=config.source_violence_categories,
    )


async def remote_command(mode, config_path, settings, selection):
    config, _root, samples, _, taxonomy, prompt = load_inputs(config_path)
    async with httpx.AsyncClient(follow_redirects=False) as client:
        provider_preflight = preflight
        if settings.provider == "gapgpt":
            from pvb.extraction.gapgpt.metadata import preflight as gapgpt_preflight

            provider_preflight = gapgpt_preflight
        metadata = await provider_preflight(settings, client)
        if mode == "preflight":
            return metadata.model_dump(mode="json")
        if selection == "pilot":
            from pvb.extraction.openrouter.sampling import select_pilot

            samples, _ = select_pilot(samples, config.seed)
        # Cost estimation never constructs a paid-capable instance or needs credentials.
        from pvb.extraction.backends.llm import response_schema
        from pvb.schemas.common import canonical_json

        def payload(sample):
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
                "response_format": response_schema(sample),
            }

        estimate = workload(samples, payload, metadata, settings.max_output_tokens)
        estimate.update(
            model_metadata=metadata.model_dump(mode="json"),
            generation_requests=0,
            conservative_reservation_per_request_usd=(
                (
                    metadata.context_length * metadata.input_usd_per_token
                    + settings.max_output_tokens * metadata.output_usd_per_token
                    + metadata.request_usd
                )
                * 1.05
                if metadata.input_usd_per_token is not None
                else settings.max_cost_usd
            ),
            budget_limit_usd=settings.max_cost_usd,
        )
        return estimate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["openrouter", "gapgpt"], default="openrouter")
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--mode",
        choices=[
            "config-check",
            "preflight",
            "estimate-cost",
            "dry-run",
            "smoke",
            "pilot",
            "selected",
            "full",
            "report",
            "export-review",
        ],
        default="dry-run",
    )
    parser.add_argument(
        "--selection",
        choices=["pilot", "full"],
        default="full",
        help="Workload selection for cost estimate",
    )
    parser.add_argument("--confirm-paid-run", action="store_true")
    parser.add_argument("--confirm-full-run", action="store_true")
    parser.add_argument("--resume", help="Phase 3 run ID; preserves budget and completed results")
    parser.add_argument(
        "--retry-uncertain",
        action="store_true",
        help="Explicitly retry calls whose outcome/charge was interrupted; previous reservations remain",
    )
    parser.add_argument(
        "--output", type=Path, help="New report export path; existing paths are never overwritten"
    )
    args = parser.parse_args(argv)
    if args.config is None:
        args.config = Path("configs/" + args.backend + ".yaml")
    if args.output is not None and args.output.exists():
        parser.error("--output must be a new file")
    try:
        settings_loader = load_settings
        if args.backend == "gapgpt":
            from pvb.extraction.gapgpt.settings import load_settings as load_gapgpt_settings

            settings_loader = load_gapgpt_settings
        settings = settings_loader()
        if args.mode == "config-check":
            settings.require_ready()
            result = {
                "configuration_ready": True,
                "settings": settings.public(),
                "paid_requests": 0,
            }
        elif args.mode == "dry-run":
            result = dry_run(args.config, settings)
        elif args.mode in ("preflight", "estimate-cost"):
            result = asyncio.run(remote_command(args.mode, args.config, settings, args.selection))
        elif args.mode in ("report", "export-review"):
            if not args.resume:
                raise ConfigurationError("Report/review export requires --resume RUN_ID.")
            result = rebuild_reports(args.config, args.resume)
            if args.mode == "export-review" and args.output:
                from pvb.extraction.io import write_text
                from pvb.extraction.openrouter.config import load_config

                config, root = load_config(args.config)
                write_text(
                    args.output,
                    (root / config.output / args.resume / result["review_csv"])
                    .read_bytes()
                    .decode("utf-8"),
                )
                result = {
                    "review_csv": str(args.output),
                    "sample_count": result["total_sample_count"],
                }
        else:
            result = asyncio.run(
                execute(
                    args.config,
                    settings,
                    mode=args.mode,
                    confirm_paid=args.confirm_paid_run,
                    confirm_full=args.confirm_full_run,
                    resume=args.resume,
                    retry_uncertain=args.retry_uncertain,
                )
            )
        if args.output and args.mode != "export-review":
            write_json(args.output, result)
        # Compact console output; detailed dry-run and run reports remain on disk.
        if args.mode == "dry-run":
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "mode",
                            "paid_requests",
                            "configuration_ready",
                            "configuration_issues",
                            "sample_count",
                            "storage",
                            "output",
                        )
                    },
                    ensure_ascii=False,
                )
            )
        elif args.mode in ("pilot", "full", "smoke", "selected", "report"):
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "run_id",
                            "total_sample_count",
                            "processing_counts",
                            "label_counts",
                            "category_counts",
                            "human_review_required",
                        )
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.mode in ("pilot", "full", "smoke", "selected", "report"):
            return (
                0
                if result["quality"]["passed"]
                and not (result["failed_samples"] + result["not_scheduled"] + result["interrupted"])
                else 1
            )
        return 0
    except ConfigurationError as exc:
        print(str(exc))
        return 1
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, httpx.HTTPError):
        print(
            "Provider operation failed safely. Check local inputs, native storage and model configuration. Provider bodies and credentials are not logged."
        )
        return 1
    except KeyboardInterrupt:
        print(
            "Interrupted. Durable request reservations and completed events were retained. Resume with the same run/configuration and explicit paid confirmation."
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
