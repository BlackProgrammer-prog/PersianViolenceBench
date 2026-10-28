"""Local inference contracts and source/checkpoint integrity; no model/network in unit tests."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pvb.extraction.io import write_json, write_jsonl
from pvb.translation.local import audit_records, translate_dataset
from pvb.translation.local_settings import LocalTranslationSettings
from pvb.translation.service import (
    MANIFEST,
    TranslationError,
    TranslationService,
    file_sha256,
    validate_model_directory,
)
from pvb.translation.settings import TranslationSettings


def model_directory(tmp_path):
    path = tmp_path / "model"
    path.mkdir()
    files = []
    for name in ("config.json", "tokenizer_config.json", "tokenizer.json", "model.safetensors"):
        target = path / name
        target.write_bytes(b"fixture-not-real-weights")
        files.append({"path": name, "size": target.stat().st_size, "sha256": file_sha256(target)})
    write_json(
        path / MANIFEST,
        {
            "model_id": "google/translategemma-4b-it",
            "commit_sha": "test-only-commit",
            "files": files,
        },
    )
    return path


def test_model_download_manifest_detects_missing_corrupt_and_escaping_files(tmp_path):
    path = model_directory(tmp_path)
    validate_model_directory(path, verify_hashes=True)
    weights = path / "model.safetensors"
    old = weights.read_bytes()
    weights.write_bytes(b"x" * len(old))
    with pytest.raises(TranslationError, match="checksum"):
        validate_model_directory(path, verify_hashes=True)
    weights.unlink()
    with pytest.raises(TranslationError, match="incomplete"):
        validate_model_directory(path)
    weights.write_bytes(old)
    manifest = json.loads((path / MANIFEST).read_text())
    manifest["files"][0]["path"] = "../outside"
    write_json(path / MANIFEST, manifest)
    with pytest.raises(TranslationError, match="incomplete"):
        validate_model_directory(path)


def test_empty_input_does_not_load_or_download_model(tmp_path):
    service = TranslationService(LocalTranslationSettings(model_path=tmp_path / "missing"))
    assert service.translate("") == ""
    assert service.translate(" \n") == " \n"
    assert service._model is None
    with pytest.raises(TypeError):
        service.translate(None)
    with pytest.raises(TranslationError, match="download"):
        service.load()


class Tensor:
    def __init__(self, tokens):
        self.tokens = tokens
        self.shape = (1, len(tokens))

    def __getitem__(self, key):
        return self.tokens[key]


class Inputs(dict):
    def to(self, device):
        return self


def fake_inference_service(tmp_path, *, token_limit=False):
    service = TranslationService(LocalTranslationSettings(model_path=tmp_path, max_new_tokens=16))
    captured = {}

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Processor:
        def apply_chat_template(self, messages, **kwargs):
            captured["messages"] = messages
            captured["template_options"] = kwargs
            return Inputs(input_ids=Tensor([11, 12, 13]))

        def decode(self, tokens, **kwargs):
            captured["decoded_tokens"] = list(tokens)
            return "ترجمهٔ آزمایشی"

    class Model:
        device = "cuda:0"
        generation_config = SimpleNamespace(eos_token_id=[2])

        def generate(self, **kwargs):
            captured["generation"] = kwargs
            return [[11, 12, 13] + ([9] * 16 if token_limit else [21, 22, 2])]

    service._model, service._processor = Model(), Processor()
    service._torch = SimpleNamespace(
        cuda=SimpleNamespace(reset_peak_memory_stats=lambda: None, synchronize=lambda: None),
        inference_mode=Context,
    )
    service.memory = dict
    return service, captured


def test_official_template_and_only_new_tokens_decoded(tmp_path):
    service, captured = fake_inference_service(tmp_path)
    assert service.translate("Original question?") == "ترجمهٔ آزمایشی"
    content = captured["messages"][0]["content"]
    assert content == [
        {
            "type": "text",
            "source_lang_code": "en",
            "target_lang_code": "fa",
            "text": "Original question?",
        }
    ]
    assert captured["decoded_tokens"] == [21, 22, 2]
    assert captured["generation"]["do_sample"] is False
    assert service.last_metrics["truncated"] is False


def test_token_limits_reject_partial_output_and_never_truncate_input(tmp_path):
    service, _captured = fake_inference_service(tmp_path, token_limit=True)
    # Stub the CUDA exception class because this test has no PyTorch installation requirement.
    service._torch.cuda.OutOfMemoryError = type("FakeOOM", (RuntimeError,), {})
    with pytest.raises(TranslationError, match="partial"):
        service.translate("Question?")
    service.settings = LocalTranslationSettings(model_path=tmp_path, max_input_tokens=64)
    original = service._processor.apply_chat_template
    service._processor.apply_chat_template = lambda *a, **kw: Inputs(
        input_ids=Tensor(list(range(65)))
    )
    with pytest.raises(TranslationError, match="not silently truncated"):
        service.translate("Long question")
    service._processor.apply_chat_template = original


def test_completed_dataset_preserves_source_and_resumes_without_inference(
    tmp_path, synthetic_sample
):
    path = model_directory(tmp_path)
    records = []
    for i in range(54):
        sample = synthetic_sample(f"Synthetic benchmark question {i}?")
        records.append({**sample.model_dump(mode="json"), "category": "other_violence"})
    write_jsonl(tmp_path / "source.jsonl", records)
    calls = []

    class Service:
        settings = LocalTranslationSettings(model_path=path)
        load_metrics = None

        def __init__(self):
            self.last_metrics = {"seconds": 0.01}

        def translate(self, text):
            calls.append(text)
            return "متن آزمایشی «" + text + "»"

    settings = TranslationSettings(input="source.jsonl", output="results")
    summary = translate_dataset(Service(), tmp_path, settings)
    assert summary["translated_count"] == 54 and len(calls) == 54
    result_path = Path(summary["directory"]) / "samples.jsonl"
    outputs = [json.loads(line) for line in result_path.read_text().splitlines()]
    assert [r["source_record"] for r in outputs] == records
    assert all(r["variant"] == "llm_translation" for r in outputs)
    pairs = [
        json.loads(line)
        for line in (Path(summary["directory"]) / "embedding_pairs.jsonl").read_text().splitlines()
    ]
    assert [r["raw_persian"] for r in pairs] == [r["prompt"] for r in outputs]
    assert all(r["human_reviewed_persian"] is None and r["embedding_scores"] is None for r in pairs)
    assert all(
        r["human_localized"] is False and r["human_review_status"] == "pending" for r in outputs
    )
    assert translate_dataset(Service(), tmp_path, settings)["translated_count"] == 54
    assert len(calls) == 54
    outputs[0]["prompt"] = "Changed output"
    write_jsonl(result_path, outputs)
    with pytest.raises(TranslationError, match="checkpoint"):
        translate_dataset(Service(), tmp_path, settings)


def test_audit_requires_same_sample_set(tmp_path):
    directory = tmp_path / "runs/portability"
    write_json(directory / "latest_completed.json", {"run_id": "fixture"})
    write_jsonl(directory / "fixture/assessments.jsonl", [{"sample_id": "wrong"}])
    with pytest.raises(TranslationError, match="differ"):
        audit_records(tmp_path, {"expected"})


def test_range_download_verifies_content_and_does_not_reuse_changed_weights(tmp_path, monkeypatch):
    import pvb.translation.model_download as module
    from pvb.translation.model_download import download_weight

    payload = b"unit-test-weight-fixture"
    digest = hashlib.sha256(payload).hexdigest()
    file = SimpleNamespace(
        rfilename="model.safetensors", size=len(payload), lfs=SimpleNamespace(sha256=digest)
    )
    requests = []

    class Response:
        status_code = 206

        def __init__(self):
            self.headers = {"content-range": f"bytes 0-{len(payload) - 1}/{len(payload)}"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self, **kwargs):
            yield payload

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, **kwargs):
            requests.append(kwargs)
            return Response()

    monkeypatch.setattr(module.httpx, "Client", Client)
    download_weight(
        "google/translategemma-4b-it", "test-commit", file, tmp_path, "test-token", workers=1
    )
    assert (tmp_path / file.rfilename).read_bytes() == payload
    assert requests[0]["headers"]["Range"] == f"bytes=0-{len(payload) - 1}"
    download_weight(
        "google/translategemma-4b-it", "test-commit", file, tmp_path, "test-token", workers=1
    )
    assert len(requests) == 1
    (tmp_path / file.rfilename).write_bytes(b"x" * len(payload))
    with pytest.raises(TranslationError, match="checksum"):
        download_weight(
            "google/translategemma-4b-it", "test-commit", file, tmp_path, "test-token", workers=1
        )
