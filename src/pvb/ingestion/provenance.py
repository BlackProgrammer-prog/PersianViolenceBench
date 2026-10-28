"""Verify optional Git provenance using existing local upstream objects only."""

import hashlib
import logging
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .config import SourceConfig

LOGGER = logging.getLogger(__name__)


def verified_commit(source: SourceConfig, root: Path, file_hash: str) -> str | None:
    """Require a matching upstream origin, commit object, and byte-identical blob.

    Never fetch, download, change a checkout, or infer a revision from today's main.
    The local upstream checkout is a trusted provenance input, not a signed attestation.
    """
    if source.retrieved_commit is None:
        return None
    try:
        if source.commit_repository is None:
            raise ValueError("commit_repository is required to verify a supplied revision")
        repository = root / source.commit_repository
        url = urlparse(source.source_url)
        if url.hostname != "raw.githubusercontent.com":
            raise ValueError(
                "local Git verification currently supports raw.githubusercontent.com URLs"
            )
        owner, name, _revision, blob_path = url.path.lstrip("/").split("/", 3)

        def git(*arguments: str) -> bytes:
            result = subprocess.run(
                ["git", "-C", str(repository), *arguments],
                check=True,
                capture_output=True,
                timeout=30,
            )
            return result.stdout

        origin = git("remote", "get-url", "origin").decode("utf-8").strip().removesuffix(".git")
        if origin not in (f"https://github.com/{owner}/{name}", f"git@github.com:{owner}/{name}"):
            raise ValueError("local repository origin does not match the configured upstream")
        commit = source.retrieved_commit
        resolved = git("rev-parse", "--verify", f"{commit}^{{commit}}").decode("ascii").strip()
        if resolved != commit:
            raise ValueError("requested revision does not identify the exact commit")
        if hashlib.sha256(git("show", f"{commit}:{blob_path}")).hexdigest() != file_hash:
            raise ValueError("raw bytes differ from the upstream commit blob")
        return commit
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        LOGGER.warning(
            "%s/%s: upstream commit could not be verified; recording null: %s",
            source.dataset_name,
            source.dataset_split,
            exc,
        )
        return None
