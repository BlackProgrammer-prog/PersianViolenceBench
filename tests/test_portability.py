import asyncio
import json

import httpx
import pytest
import yaml
from pydantic import SecretStr, ValidationError

from pvb.extraction.backends.openrouter import ClassificationError
from pvb.extraction.gapgpt.metadata import parse_metadata
from pvb.extraction.gapgpt.settings import GapGPTSettings
from pvb.extraction.openrouter.accounting import Journal
from pvb.ingestion.adapters.strongreject import adapt
from pvb.portability.__main__ import execute
from pvb.portability.backend import PortabilityBackend, response_schema
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.portability import PortabilityDecision


def decision(label="translation_portable"):
    return {
        "label": label,
        "dependency_dimensions": [],
        "source_context_summary": None,
        "rationale": "معنای کلی درخواست بدون زمینهٔ محلی خاص قابل ارزیابی است.",
        "localization_guidance": None,
        "invariants_to_preserve": ["حفظ نوع قصد و رابطهٔ هدف"],
        "evidence": [],
        "confidence": 0.8,
        "requires_human_review": True,
        "translation_tested": False,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"requires_human_review": False},
        {"translation_tested": True},
        {"label": "localization_required"},
        {"label": "uncertain"},
        {"dependency_dimensions": ["legal_institutional"]},
        {"localization_guidance": "Needs localization"},
        {"invariants_to_preserve": []},
    ],
)
def test_inconsistent_or_overclaimed_cultural_decisions_are_rejected(change):
    with pytest.raises(ValidationError):
        PortabilityDecision.model_validate({**decision(), **change})


@pytest.mark.parametrize("label", ["translation_portable", "localization_required", "uncertain"])
def test_cultural_labels_remain_independent_and_cache_provenance_is_typed(
    tmp_path, synthetic_sample, label
):
    sample = synthetic_sample("A synthetic request referring to a named local institution.")
    settings = GapGPTSettings(
        credential=SecretStr("gap-portability-test-secret"),
        max_retries=0,
        input_usd_per_million=2,
        output_usd_per_million=12,
        request_usd=0,
        pricing_source="https://example.org/fixture-price",
    )
    metadata = parse_metadata({"data": [{"id": settings.model}]}, settings)
    wire = decision(label)
    if label == "localization_required":
        wire.update(
            dependency_dimensions=["legal_institutional"],
            source_context_summary="اشارهٔ صریح به یک نهاد محلی",
            localization_guidance="بازبین آشنا به زمینه، هم‌ارزی نقش نهاد را بررسی کند.",
            evidence=[0],
        )
    if label == "uncertain":
        wire.update(
            localization_guidance="بازبین بررسی کند آیا اشارهٔ محلی برای فهم درخواست ضروری است."
        )
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["response_format"]["json_schema"]["name"] == "cultural_portability"
        assert payload["response_format"]["json_schema"]["schema"] == response_schema(sample)
        assert "original_violence_category" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "model": metadata.canonical_slug,
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(wire)}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 100,
                    "cost": 0.001,
                    "cost_currency": "USD",
                },
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            backend = PortabilityBackend(
                settings=settings,
                metadata=metadata,
                client=client,
                prompt="Review cultural portability only.",
                taxonomy={"version": "fixture", "target_context": "fa-IR"},
                prompt_version="fixture",
                run_id="pvb-portability-fixture",
                journal=Journal(tmp_path / "run"),
                cache_dir=tmp_path / "cache",
                requests_per_minute=60000,
                paid_authorized=True,
            )
            result = await backend.classify(sample)
            assert result.label == label
            assert (await backend.classify(sample)) == result
            event = backend.journal.events[-1]
            assert event.decision is None and event.portability_decision == result
            assert event.outcome == "classified"
            reloaded = Journal(tmp_path / "run")
            assert reloaded.events[-1].portability_decision.label == label
            if label == "localization_required":
                assert result.evidence == [sample.original_prompt]

    asyncio.run(run())
    assert len(calls) == 1


def test_paid_portability_gate_runs_before_loading_inputs(tmp_path):
    with pytest.raises(ValueError, match="confirm-paid-run"):
        asyncio.run(execute(tmp_path / "missing.yaml"))


def test_portability_parser_rejects_evidence_not_from_input(tmp_path, synthetic_sample):
    sample = synthetic_sample("An original fixture.")
    settings = GapGPTSettings(credential=SecretStr("gap-fixture-key"))
    metadata = parse_metadata(
        {"data": [{"id": settings.model}]}, settings, provider_budget_verified=True
    )
    backend = PortabilityBackend(
        settings=settings,
        metadata=metadata,
        client=None,
        prompt="Classify.",
        taxonomy={"version": "fixture"},
        prompt_version="fixture",
        run_id="fixture",
        journal=Journal(tmp_path),
        cache_dir=tmp_path / "cache",
        requests_per_minute=18,
        paid_authorized=True,
    )
    raw = {**decision(), "evidence": [999]}
    envelope = {
        "model": settings.model,
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}],
    }
    with pytest.raises(ClassificationError, match="unsupported_evidence"):
        backend._parse(envelope, sample)


@pytest.mark.parametrize("refuse_second", [False, True])
def test_paid_review_exports_independent_labels_and_resume_avoids_duplicate_calls(
    tmp_path, project_root, decision_data, run, refuse_second
):
    rows = []
    for i in range(3):
        sample = adapt(
            {
                "category": "Violence",
                "source": "custom",
                "forbidden_prompt": f"Synthetic cultural-review case {i}.",
            }
        )
        original_label = "out_of_scope" if i == 1 else "unsafe_violence"
        annotation = SampleAnnotation(
            **{**decision_data, "label": original_label, "subcategories": [] if i == 1 else ["V2"]},
            annotation_id=f"original-{i}",
            sample_id=sample.sample_id,
            review_status="pending",
            annotation_method="llm",
            annotator_id="original-model",
            annotation_run_id=run.run_id,
            created_at=run.started_at,
            updated_at=run.started_at,
        )
        rows.append(
            {
                **sample.model_dump(mode="json"),
                "category": "other_violence" if i == 1 else "unsafe_violence",
                "classification_label": original_label,
                "annotation": annotation.model_dump(mode="json"),
            }
        )
    source = tmp_path / "source.jsonl"
    source.write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / ".env").write_text(
        "GAPGPT_API_KEY=portability-fixture-secret\nPVB_API_MAX_RETRIES=0\n"
    )
    config = {
        "root": str(tmp_path),
        "input": "source.jsonl",
        "output": "reviews",
        "prompt": str(project_root / "configs/prompts/cultural_portability_v1.txt"),
        "prompt_version": "cultural-portability-1.0.0",
        "expected_samples": 3,
        "requests_per_minute": 60000.0,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    state = {"cents": 0, "posts": 0}

    def handler(request):
        if request.method == "GET":
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "gpt-5.6-terra"}]})
            if request.url.path.endswith("/subscription"):
                return httpx.Response(200, json={"hard_limit_usd": 2})
            return httpx.Response(200, json={"total_usage": state["cents"]})
        labels = ["translation_portable", "localization_required", "uncertain"]
        d = decision(labels[state["posts"]])
        if d["label"] == "localization_required":
            d.update(
                dependency_dimensions=["legal_institutional"],
                source_context_summary="زمینهٔ صریح محلی",
                localization_guidance="هم‌ارزی نقش نهاد با بازبینی انسانی بررسی شود.",
                evidence=[0],
            )
        if d["label"] == "uncertain":
            d["localization_guidance"] = "ابهام زمینه با متخصص بررسی شود."
        state["posts"] += 1
        state["cents"] += 1
        if refuse_second and state["posts"] == 2:
            return httpx.Response(
                200, json={"error": {"code": 403}, "usage": {"cost": 0.01, "cost_currency": "USD"}}
            )
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-5.6-terra",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(d)}}],
            },
        )

    async def perform(resume=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await execute(path, confirmed=True, resume=resume, client=client)

    summary = asyncio.run(perform())
    assert summary["status_counts"] == (
        {"assessed": 2, "manual_review_required": 1} if refuse_second else {"assessed": 3}
    )
    assert summary["label_counts"] == {
        "translation_portable": 1,
        "localization_required": 0 if refuse_second else 1,
        "uncertain": 1,
    }
    assert summary["actual_translations_evaluated"] is False
    directory = tmp_path / "reviews" / summary["run_id"]
    saved = [
        json.loads(line) for line in (directory / "assessments.jsonl").read_text().splitlines()
    ]
    assert [r["annotation"] for r in saved] == [r["annotation"] for r in rows]
    assert (directory / "portability_review.csv").exists() and (
        directory / "portability_report.html"
    ).exists()
    if refuse_second:
        assert saved[1]["cultural_portability"] is None
        assert summary["manual_review_due_provider_refusal"] == 1
    resumed = asyncio.run(perform(summary["run_id"]))
    assert resumed["label_counts"] == summary["label_counts"] and state["posts"] == 3
