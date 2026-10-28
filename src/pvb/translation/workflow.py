"""Run setup, a fresh-process offline smoke test, and all 54 translations in order."""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pvb.extraction.io import write_json
from pvb.translation.local_settings import load_local_settings
from pvb.translation.settings import ROOT


def process_identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if stat[0] == "Z" else stat[19]
    except FileNotFoundError:
        return None


def update_download_progress(state, model_path):
    plan_path = model_path / ".cache/pvb-download-plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        total = sum(file["size"] for file in plan["files"])
        received = 0
        for file in plan["files"]:
            target = model_path / file["name"]
            checkpoint = model_path / ".cache/pvb-ranges" / (file["name"] + ".json")
            if target.exists() and target.stat().st_size == file["size"]:
                received += file["size"]
            elif checkpoint.exists():
                saved = json.loads(checkpoint.read_text())
                received += sum(
                    min(8 * 1024**2, file["size"] - int(start)) for start in saved["done"]
                )
        state.update(
            updated_at=datetime.now(timezone.utc).isoformat(),
            checkpointed_model_bytes=received,
            expected_model_bytes=total,
            download_percent=round(100 * received / total, 2) if total else None,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-pid", type=int, action="append", default=[])
    parser.add_argument("--translate-only", action="store_true")
    args = parser.parse_args(argv)
    model_path = load_local_settings().model_path
    directory = ROOT / "runs/translation"
    directory.mkdir(parents=True, exist_ok=True)
    status_path = directory / "translategemma_workflow_status.json"
    state = {"started_at": datetime.now(timezone.utc).isoformat(), "stages": [], "paid_requests": 0}
    with (directory / ".translategemma-workflow.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("A TranslateGemma workflow is already running.", flush=True)
            return 1
        pending = {pid: process_identity(pid) for pid in args.wait_pid}
        state.update(status="waiting_for_existing_setup", waiting_pids=list(pending))
        write_json(status_path, state)
        while any(
            identity is not None and process_identity(pid) == identity
            for pid, identity in pending.items()
        ):
            update_download_progress(state, model_path)
            write_json(status_path, state)
            time.sleep(5)
        installer = directory / "install_locked_wheels.py"
        dependency_command = (
            [sys.executable, str(installer)]
            if installer.exists()
            else ["uv", "sync", "--extra", "local-translation"]
        )
        stages = [
            ("dependencies", dependency_command),
            (
                "download",
                [
                    sys.executable,
                    "-m",
                    "pvb.translation.local",
                    "--mode",
                    "download",
                    "--download-workers",
                    "8",
                ],
            ),
            (
                "offline_smoke",
                [
                    sys.executable,
                    "-m",
                    "pvb.translation.local",
                    "--mode",
                    "smoke",
                    "--block-network",
                ],
            ),
            (
                "translate_54",
                [
                    sys.executable,
                    "-m",
                    "pvb.translation.local",
                    "--mode",
                    "translate",
                    "--block-network",
                ],
            ),
        ]
        if args.translate_only:
            from pvb.translation.service import validate_model_directory

            smoke_path = directory / "translategemma-smoke/smoke_report.json"
            smoke = json.loads(smoke_path.read_text())
            manifest = validate_model_directory(model_path)
            if smoke["model_revision"] != manifest["commit_sha"] or len(smoke["tests"]) != 5:
                raise ValueError("A successful smoke report for the local model is required.")
            state["verified_smoke_report"] = str(smoke_path)
            stages = [stage for stage in stages if stage[0] == "translate_54"]
        environment = dict(os.environ, HF_HUB_DISABLE_XET="1", PYTHONUNBUFFERED="1")
        environment.setdefault("UV_HTTP_TIMEOUT", "120")
        environment.setdefault("UV_CONCURRENT_DOWNLOADS", "4")
        for name, command in stages:
            step = {
                "name": name,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "running",
            }
            state["stages"].append(step)
            state.update(status="running", current_stage=name, waiting_pids=[])
            write_json(status_path, state)
            print(json.dumps({"stage": name, "status": "running"}), flush=True)
            process = subprocess.Popen(command, cwd=ROOT, env=environment)
            while process.poll() is None:
                update_download_progress(state, model_path)
                write_json(status_path, state)
                time.sleep(5)
            code = process.returncode
            step.update(
                status="completed" if code == 0 else "failed",
                returncode=code,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            if code:
                state.update(status="blocked", current_stage=name)
                write_json(status_path, state)
                return code
        state.update(
            status="completed",
            current_stage=None,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        write_json(status_path, state)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
