import pytest

from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import Decision, SampleAnnotation
from pvb.schemas.samples import BenchmarkSample


@pytest.fixture
def decision_data():
    return {
        "label": "unsafe_violence",
        "subcategories": ["V3", "V4"],
        "intent": "harmful",
        "target": "other_person",
        "actionability": "medium",
        "risk_severity": "high",
        "confidence": 0.0,
        "rationale": "Synthetic request for physical harm to others.",
        "evidence": [],
        "requires_human_review": True,
    }


@pytest.fixture
def run():
    return AnnotationRun(
        run_id="run-test",
        method="rule_based",
        configuration={},
        input_dataset_fingerprint="a" * 64,
        started_at="2026-10-24T00:00:00Z",
        status="running",
        sample_count=1,
    )


def test_canonical_schema_unchanged():
    assert len(BenchmarkSample.model_fields) == 14


@pytest.mark.parametrize(
    "change",
    [
        {"label": "Violence"},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"subcategories": ["V6"]},
        {"subcategories": ["V1", "V1"]},
        {"subcategories": []},
        {"target": "self"},
        {"intent": "benign"},
        {"rationale": "   "},
        {"label": "out_of_scope"},
        {"label": "benign_violence_related"},
        {"confidence": "0.5"},
        {"unknown": "field"},
    ],
)
def test_invalid_decision(decision_data, change):
    with pytest.raises(ValueError):
        Decision.model_validate({**decision_data, **change})


def test_ambiguous_must_require_review(decision_data):
    with pytest.raises(ValueError):
        Decision.model_validate(
            {
                **decision_data,
                "label": "out_of_scope",
                "subcategories": [],
                "intent": "ambiguous",
                "requires_human_review": False,
            }
        )


def test_annotation_metadata(decision_data, run):
    from types import SimpleNamespace

    from pvb.extraction.pipeline import annotation_for

    a = annotation_for(
        SimpleNamespace(sample_id="sample"), Decision(**decision_data), run, "rule-v1"
    )
    assert (
        a.annotation_id
        == annotation_for(
            SimpleNamespace(sample_id="sample"), Decision(**decision_data), run, "rule-v1"
        ).annotation_id
    )
    assert SampleAnnotation.model_validate_json(a.model_dump_json()) == a
    for update in (
        {"review_status": "approved"},
        {"requires_human_review": False},
        {"created_at": "2026-10-24T00:00:00"},
        {"created_at": "2026-10-24T01:00:00+01:00"},
        {"updated_at": "2025-01-01T00:00:00Z"},
        {"annotation_method": "unknown"},
    ):
        with pytest.raises(ValueError):
            SampleAnnotation.model_validate({**a.model_dump(), **update})


@pytest.mark.parametrize(
    "update",
    [
        {"method": "llm"},
        {"sample_count": -1},
        {"success_count": 2},
        {"status": "completed"},
        {"configuration": {"api_key": "do-not-store"}},
        {"configuration": {"nested": [{"password": "secret"}]}},
        {"completed_at": "2020-01-01T00:00:00Z"},
    ],
)
def test_invalid_run(run, update):
    with pytest.raises(ValueError):
        AnnotationRun.model_validate({**run.model_dump(), **update})
