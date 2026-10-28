"""Download, test, or run local TranslateGemma within the existing translation module."""

import argparse
import csv
import io
import json
import platform
import socket
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pvb.extraction.io import write_json, write_jsonl, write_text
from pvb.schemas.common import canonical_json, sha256_text
from pvb.translation.local_settings import load_local_settings, local_values
from pvb.translation.service import (
    MANIFEST,
    TranslationError,
    TranslationService,
    file_sha256,
    validate_model_directory,
)
from pvb.translation.settings import ROOT, load_settings

SMOKE_TEXTS = [
    "Artificial intelligence is changing the way people work.",
    "Which of the following numbers is a prime number?",
    "If all birds have wings and some animals are birds, which conclusion must be true?",
    "Which of the following statements is NOT correct?",
    "A student has 15 apples and gives away 7. How many apples remain?",
]


def download(settings, root, *, workers=2):
    from huggingface_hub import HfApi, snapshot_download

    path = settings.model_path.resolve()
    if path == root or any(path.is_relative_to(root / name) for name in ("src", "configs", "data")):
        raise TranslationError("Model download path overlaps project source/data.")
    if (path / MANIFEST).exists():
        manifest = validate_model_directory(path, verify_hashes=True)
        if manifest["requested_revision"] != settings.revision:
            raise TranslationError("Existing model revision differs; use another model directory.")
        return {"status": "already_downloaded", "model_path": str(path), **manifest}
    values = local_values(root)
    token = values.get("HF_TOKEN") or values.get("HUGGINGFACE_HUB_TOKEN") or None
    api = HfApi(token=token)
    info = api.model_info(settings.model_id, revision=settings.revision, files_metadata=True)
    write_json(
        path / ".cache/pvb-download-plan.json",
        {
            "commit_sha": info.sha,
            "files": [
                {"name": file.rfilename, "size": file.size}
                for file in info.siblings
                if file.rfilename.endswith(".safetensors")
            ],
        },
    )
    # Fail on the small gated config before attempting multi-GB weight transfers.
    from huggingface_hub import hf_hub_download

    hf_hub_download(settings.model_id, "config.json", revision=info.sha, token=token)
    allowed = ["*.json", "*.safetensors", "*.model", "*.jinja", "*.txt", "README.md", "LICENSE*"]
    snapshot_download(
        settings.model_id,
        revision=info.sha,
        local_dir=path,
        token=token,
        allow_patterns=allowed,
        ignore_patterns=["*.safetensors"] if workers > 2 else None,
        max_workers=2,
    )
    if workers > 2:
        from pvb.translation.model_download import download_weight

        for file in info.siblings:
            if file.rfilename.endswith(".safetensors"):
                download_weight(settings.model_id, info.sha, file, path, token, workers=workers)
    files = []
    upstream = {f.rfilename: f for f in info.siblings}
    for target in sorted(path.rglob("*")):
        rel = target.relative_to(path)
        if not target.is_file() or rel.parts[0] == ".cache" or target.name == MANIFEST:
            continue
        checksum = file_sha256(target)
        remote = upstream.get(rel.as_posix())
        if remote is not None and remote.lfs and remote.lfs.sha256 != checksum:
            raise TranslationError("Downloaded weight checksum differs from Hugging Face LFS.")
        files.append({"path": rel.as_posix(), "size": target.stat().st_size, "sha256": checksum})
    manifest = {
        "model_id": settings.model_id,
        "requested_revision": settings.revision,
        "commit_sha": info.sha,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    write_json(path / MANIFEST, manifest)
    validate_model_directory(path)
    return {"status": "downloaded", "model_path": str(path), **manifest}


def smoke(service, output):
    output.mkdir(parents=True, exist_ok=True)
    service.load()
    tests = []
    for text in SMOKE_TEXTS:
        tests.append(
            {
                "english": text,
                "persian": service.translate(text),
                "metrics": service.last_metrics,
                "errors": [],
            }
        )
        write_json(output / "smoke_tests.json", tests)
    summary = {
        "model_id": service.settings.model_id,
        "model_revision": service.manifest["commit_sha"],
        "python": platform.python_version(),
        "load": service.load_metrics,
        "first_translation_seconds": tests[0]["metrics"]["seconds"],
        "mean_translation_seconds": statistics.mean(t["metrics"]["seconds"] for t in tests),
        "tests": tests,
        "automatic_quality_verdict": None,
        "human_review_required": True,
    }
    write_json(output / "smoke_report.json", summary)
    return summary


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def audit_records(root, ids):
    pointer = root / "runs/portability/latest_completed.json"
    if not pointer.exists():
        return {}, None
    info = json.loads(pointer.read_text())
    # Pointer formats may contain an absolute directory or just the run ID.
    run_id = info.get("run_id")
    if not run_id:
        raise TranslationError("Completed cultural audit pointer has no run ID.")
    directory = root / "runs/portability" / run_id
    rows = read_jsonl(directory / "assessments.jsonl")
    if {r["sample_id"] for r in rows} != ids:
        raise TranslationError("Cultural audit and translation sample IDs differ.")
    return {r["sample_id"]: r for r in rows}, run_id


def translate_dataset(service, root, settings):
    """Immutable source + independent translation, checkpointed after every sample."""
    import fcntl

    source = (root / settings.input).resolve()
    base = (root / settings.output).resolve()
    if source.is_relative_to(base) or any(
        base.is_relative_to(root / name)
        for name in ("src", "configs", "data/raw", "data/normalized")
    ):
        raise TranslationError("Translation output overlaps protected source paths.")
    records = read_jsonl(source)
    ids = {r["sample_id"] for r in records}
    if len(records) != 54 or len(ids) != 54:
        raise TranslationError("Expected exactly 54 unique selected source samples.")
    from pvb.schemas.samples import CANONICAL_FIELDS, BenchmarkSample

    for row in records:
        BenchmarkSample.model_validate({key: row[key] for key in CANONICAL_FIELDS})
    audits, audit_id = audit_records(root, ids)
    manifest = validate_model_directory(service.settings.model_path)
    # The inference implementation is part of run identity; changed code cannot reuse results silently.
    implementation = {
        name: file_sha256(Path(__file__).parent / name)
        for name in ("service.py", "local.py", "local_settings.py")
    }
    identity = {
        "schema_version": "1.0.0",
        "source_sha256": file_sha256(source),
        "model_commit": manifest["commit_sha"],
        "model_manifest_sha256": file_sha256(service.settings.model_path / MANIFEST),
        "settings": service.settings.model_dump(mode="json"),
        "cultural_audit_run_id": audit_id,
        "cultural_audit_sha256": sha256_text(canonical_json(audits)),
        "implementation": implementation,
    }
    run_id = "translategemma-" + sha256_text(canonical_json(identity))[:20]
    output = base / run_id
    output.mkdir(parents=True, exist_ok=True)
    with (base / ".local-writer.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TranslationError("Another local translation run is using this output directory.")
        write_json(output / "run.json", {"run_id": run_id, **identity})
        completed_path = output / "samples.jsonl"
        completed = read_jsonl(completed_path) if completed_path.exists() else []
        done = {r["sample_id"]: r for r in completed}
        if len(done) != len(completed) or not set(done).issubset(ids):
            raise TranslationError("Translation checkpoint has duplicate/unexpected sample IDs.")
        sources = {r["sample_id"]: r for r in records}
        for row in completed:
            original = sources[row["sample_id"]]
            if (
                row["source_record"] != original
                or row["translation_sha256"] != sha256_text(row["prompt"])
                or not row["prompt"].strip()
                or row["model_revision"] != manifest["commit_sha"]
            ):
                raise TranslationError("Translation checkpoint does not match source/model/output.")
        errors = []
        started = time.perf_counter()
        for source_row in records:
            sample_id = source_row["sample_id"]
            if sample_id in done:
                continue
            try:
                translated = service.translate(source_row["original_prompt"])
                prompt_metrics = dict(service.last_metrics)
                context = source_row.get("original_context")
                translated_context = service.translate(context) if context is not None else None
                context_metrics = (
                    dict(service.last_metrics) if context and context.strip() else None
                )
                audit = audits.get(sample_id, {})
                decision = audit.get("cultural_portability")
                label = decision.get("label") if decision else None
                cohort = (
                    "localization_required"
                    if label == "localization_required"
                    else "unassessed_provider_refusal"
                    if audits and decision is None
                    else "translation_portable"
                    if label == "translation_portable"
                    else "uncertain"
                )
                row = {
                    "sample_id": sample_id,
                    "variant": "llm_translation",
                    "translation_engine": "translategemma",
                    "language": "fa",
                    "status": "translated_unreviewed",
                    "prompt": translated,
                    "context": translated_context,
                    "translation_sha256": sha256_text(translated),
                    "context_translation_sha256": sha256_text(translated_context)
                    if translated_context is not None
                    else None,
                    "provider": "local_huggingface_transformers",
                    "model_requested": service.settings.model_id,
                    "model_revision": manifest["commit_sha"],
                    "quantization": "nf4_double_quant_4bit",
                    "human_review_status": "pending",
                    "human_localized": False,
                    "source_record": source_row,
                    "source_prompt_sha256": source_row["prompt_sha256"],
                    "cultural_audit_run_id": audit_id,
                    "cultural_portability": decision,
                    "comparison_cohort": cohort,
                    "translation_metrics": {"prompt": prompt_metrics, "context": context_metrics},
                }
                completed.append(row)
                done[sample_id] = row
                write_jsonl(completed_path, completed)
                print(
                    json.dumps({"completed": len(done), "total": 54, "sample_id": sample_id}),
                    flush=True,
                )
            except TranslationError as exc:
                errors.append({"sample_id": sample_id, "error": str(exc)})
                # Stop resource/model failures instead of making 54 identical failures.
                break
        write_json(output / "errors.json", errors)
        english = [
            {
                "sample_id": r["sample_id"],
                "prompt": r["original_prompt"],
                "context": r.get("original_context"),
                "language": "en",
                "source_record": r,
            }
            for r in records
        ]
        write_jsonl(output / "english.jsonl", english)
        stream = io.StringIO(newline="")
        columns = [
            "sample_id",
            "category",
            "comparison_cohort",
            "english",
            "persian",
            "model",
            "revision",
        ]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in completed:
            writer.writerow(
                {
                    "sample_id": row["sample_id"],
                    "category": row["source_record"]["category"],
                    "comparison_cohort": row["comparison_cohort"],
                    "english": row["source_record"]["original_prompt"],
                    "persian": row["prompt"],
                    "model": row["model_requested"],
                    "revision": row["model_revision"],
                }
            )
        write_text(output / "translations.csv", stream.getvalue())
        write_jsonl(
            output / "embedding_pairs.jsonl",
            [
                {
                    "sample_id": row["sample_id"],
                    "comparison_cohort": row["comparison_cohort"],
                    "english": row["source_record"]["original_prompt"],
                    "raw_persian": row["prompt"],
                    "human_reviewed_persian": None,
                    "human_localized_persian": None,
                    "human_review_status": "pending",
                    "embedding_model": None,
                    "embedding_scores": None,
                }
                for row in completed
            ],
        )
        summary = {
            "run_id": run_id,
            "directory": str(output),
            "status": "completed" if len(done) == 54 else "incomplete",
            "source_count": 54,
            "translated_count": len(done),
            "errors": errors,
            "cohort_counts": dict(Counter(r["comparison_cohort"] for r in completed)),
            "seconds_this_invocation": time.perf_counter() - started,
            "load_metrics": service.load_metrics,
            "human_reviewed_count": 0,
            "embedding_comparison_performed": False,
            "network_requests_during_translation": 0,
            "paid_api_requests": 0,
        }
        write_json(output / "summary.json", summary)
        if len(done) == 54:
            write_json(base / "latest_translategemma.json", summary)
        return summary


def block_network():
    def denied(*args, **kwargs):
        raise RuntimeError("Network access blocked for the offline translation test.")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("check", "download", "smoke", "translate"), default="check"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--block-network", action="store_true")
    parser.add_argument("--download-workers", type=int, choices=range(1, 49), default=2)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    status_path = root / "runs/translation/translategemma_setup_status.json"
    try:
        local_settings = load_local_settings(root)
        if args.block_network:
            if args.mode == "download":
                raise TranslationError("Download cannot run with network blocked.")
            block_network()
        if args.mode == "download":
            result = download(local_settings, root, workers=args.download_workers)
        elif args.mode == "check":
            import importlib.metadata

            import torch

            result = {
                "python": platform.python_version(),
                "settings": local_settings.model_dump(mode="json"),
                "dependencies": {
                    name: importlib.metadata.version(name)
                    for name in (
                        "torch",
                        "transformers",
                        "accelerate",
                        "bitsandbytes",
                        "huggingface-hub",
                        "sentencepiece",
                    )
                },
                "cuda_available": torch.cuda.is_available(),
                "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                "gpu_free_total_bytes": list(torch.cuda.mem_get_info())
                if torch.cuda.is_available()
                else None,
                "local_model_ready": (local_settings.model_path / MANIFEST).is_file(),
            }
        else:
            service = TranslationService(local_settings)
            result = (
                smoke(service, root / "runs/translation/translategemma-smoke")
                if args.mode == "smoke"
                else translate_dataset(service, root, load_settings(root))
            )
        write_json(status_path, {"mode": args.mode, "result": result})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(result.get("status") == "incomplete")
    except Exception as exc:  # noqa: BLE001 -- CLI boundary must redact upstream credentials.
        # Do not print arbitrary upstream HTTP exceptions/headers containing credentials.
        from pydantic import SecretStr

        from pvb.translation.settings import credential_configured

        values = local_values(root)
        if type(exc).__name__ in ("GatedRepoError", "RepositoryNotFoundError"):
            reason = (
                "Model access denied. Accept Gemma terms on Hugging Face and configure HF_TOKEN."
            )
        elif isinstance(exc, TranslationError):
            reason = str(exc)
        else:
            reason = "Local translation failed: " + type(exc).__name__
        for key in (
            "HF_TOKEN",
            "HUGGINGFACE_HUB_TOKEN",
            "GAPGPT_API_KEY",
            "OPENROUTER_API_KEY",
            "GOOGLE_TRANSLATE_API_KEY",
        ):
            secret = values.get(key) or ""
            if credential_configured(SecretStr(secret)):
                reason = reason.replace(secret, "[REDACTED]")
        result = {"mode": args.mode, "status": "blocked", "error": reason}
        write_json(status_path, result)
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
