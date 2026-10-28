"""Resumable HTTP range fallback for large official HF weights on slow connections."""

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from pvb.extraction.io import write_json
from pvb.translation.service import TranslationError, file_sha256


def download_weight(model_id, revision, file, directory, token, *, workers=16, source_url=None):
    """Only verified ranges from the pinned official repo; never accepts a partial weight."""
    target = directory / file.rfilename
    expected_hash = file.lfs.sha256
    if target.exists() and target.stat().st_size == file.size:
        if file_sha256(target) == expected_hash:
            return
        raise TranslationError("Existing weight file checksum mismatch.")
    if not 1 <= workers <= 48:
        raise TranslationError("Download workers must be between 1 and 48.")
    staging = directory / ".cache/pvb-ranges"
    staging.mkdir(parents=True, exist_ok=True)
    name = file.rfilename
    partial = staging / (name + ".partial")
    state_path = staging / (name + ".json")
    chunk = 8 * 1024**2
    identity = {"revision": revision, "name": name, "size": file.size, "sha256": expected_hash}
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {"identity": identity, "done": {}}
    )
    if state["identity"] != identity:
        raise TranslationError("Partial download belongs to a different model revision.")
    descriptor = os.open(partial, os.O_RDWR | os.O_CREAT, 0o600)
    os.ftruncate(descriptor, file.size)
    lock = threading.Lock()
    url = source_url or f"https://huggingface.co/{model_id}/resolve/{revision}/{name}"
    headers = {"Authorization": "Bearer " + token} if token else {}
    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)
    ranges = list(range(0, file.size, chunk))
    # Validate saved ranges; an interrupted write is downloaded again, not trusted by size.
    for start, saved_hash in list(state["done"].items()):
        length = min(chunk, file.size - int(start))
        if hashlib.sha256(os.pread(descriptor, length, int(start))).hexdigest() != saved_hash:
            del state["done"][start]
    try:
        with httpx.Client(
            follow_redirects=True, limits=limits, timeout=httpx.Timeout(120, connect=30)
        ) as client:

            def fetch(start):
                end = min(start + chunk, file.size) - 1
                for attempt in range(12):
                    try:
                        with client.stream(
                            "GET", url, headers={**headers, "Range": f"bytes={start}-{end}"}
                        ) as response:
                            if (
                                response.status_code != 206
                                or response.headers.get("content-range")
                                != f"bytes {start}-{end}/{file.size}"
                            ):
                                raise TranslationError(
                                    "Weight server did not return the exact requested range."
                                )
                            offset = start
                            digest = hashlib.sha256()
                            for block in response.iter_bytes(chunk_size=256 * 1024):
                                if offset + len(block) > end + 1:
                                    raise TranslationError(
                                        "Weight range exceeded its expected size."
                                    )
                                written = os.pwrite(descriptor, block, offset)
                                if written != len(block):
                                    raise TranslationError(
                                        "Incomplete disk write while downloading weights."
                                    )
                                offset += len(block)
                                digest.update(block)
                            if offset != end + 1:
                                raise TranslationError("Weight range was interrupted.")
                        with lock:
                            state["done"][str(start)] = digest.hexdigest()
                            # Sync data before recording that a range can be reused after interruption.
                            os.fdatasync(descriptor)
                            write_json(state_path, state)
                            count = len(state["done"])
                            if count % 16 == 0 or count == len(ranges):
                                print(
                                    json.dumps(
                                        {
                                            "weight": name,
                                            "chunks": count,
                                            "total_chunks": len(ranges),
                                        }
                                    ),
                                    flush=True,
                                )
                        return
                    except (httpx.HTTPError, TranslationError):
                        if attempt == 11:
                            raise TranslationError(
                                "Official weight range download failed after retries."
                            ) from None
                        time.sleep(min(2**attempt, 30))

            remaining = [start for start in ranges if str(start) not in state["done"]]
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for task in as_completed([pool.submit(fetch, start) for start in remaining]):
                    task.result()
        os.fdatasync(descriptor)
    finally:
        os.close(descriptor)
    if file_sha256(partial) != expected_hash:
        raise TranslationError("Complete downloaded weight failed official LFS checksum.")
    os.replace(partial, target)
    print(json.dumps({"weight": name, "status": "verified"}), flush=True)
