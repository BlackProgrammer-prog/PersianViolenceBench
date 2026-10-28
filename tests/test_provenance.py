import hashlib
import subprocess

from pvb.ingestion.config import SourceConfig
from pvb.ingestion.provenance import verified_commit


def source(**kwargs):
    return SourceConfig(
        dataset_name="harmbench",
        dataset_split="test",
        path="raw.csv",
        source_url="https://raw.githubusercontent.com/owner/repo/main/data/raw.csv",
        **kwargs,
    )


def test_unverified_revision_is_null(tmp_path, caplog):
    config = source(retrieved_commit="a" * 40)
    assert verified_commit(config, tmp_path, "b" * 64) is None
    assert "could not be verified; recording null" in caplog.text


def test_verified_local_upstream_commit(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()

    def git(*args):
        return (
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
            .stdout.decode()
            .strip()
        )

    git("init")
    git("remote", "add", "origin", "https://github.com/owner/repo.git")
    (repo / "data").mkdir()
    raw = b"exact upstream bytes\r\n"
    (repo / "data/raw.csv").write_bytes(raw)
    git("add", "data/raw.csv")
    git(
        "-c",
        "user.name=PVB Test",
        "-c",
        "user.email=pvb@example.org",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "fixture",
    )
    commit = git("rev-parse", "HEAD")
    config = source(retrieved_commit=commit, commit_repository="upstream")
    assert verified_commit(config, tmp_path, hashlib.sha256(raw).hexdigest()) == commit
    assert verified_commit(config, tmp_path, "f" * 64) is None
    git("remote", "set-url", "origin", "https://github.com/wrong/repo.git")
    assert verified_commit(config, tmp_path, hashlib.sha256(raw).hexdigest()) is None
