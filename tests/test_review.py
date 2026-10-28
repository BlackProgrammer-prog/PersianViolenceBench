import csv

import pytest

from pvb.extraction.agreement import agreement, kappa
from pvb.extraction.pipeline import annotation_for
from pvb.extraction.review import export_review, import_review
from pvb.ingestion.normalize import collect
from pvb.schemas.annotations import Decision, SampleAnnotation


def completed_csv(path, samples, annotations):
    export_review(path, samples, annotations)
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    row = rows[0]
    row.update(
        reviewer_label="out_of_scope",
        reviewer_subcategories="",
        reviewer_intent="benign",
        reviewer_target="none",
        reviewer_actionability="none",
        reviewer_risk_severity="low",
        reviewer_rationale="Reviewed synthetic unrelated input.",
        reviewer_confidence="0.8",
        reviewer_id="reviewer-A",
        reviewer_notes="Synthetic review fixture.",
        review_status="approved",
    )
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows, fields


def test_review_round_trip(tmp_path, snapshot, decision_data, run):
    samples, _ = collect(snapshot[0])
    previous = [annotation_for(samples[0], Decision(**decision_data), run, "rules")]
    path = tmp_path / "review.csv"
    completed_csv(path, samples, previous)
    annotations, human_run = import_review(path, samples, previous)
    assert len(annotations) == 1
    a = annotations[0]
    assert a.annotation_method == "human" and a.annotator_id == "reviewer-A"
    assert a.review_status == "approved" and not a.requires_human_review
    assert a.supersedes_annotation_id == previous[0].annotation_id
    assert human_run.method == "human"
    assert import_review(path, samples, previous)[0][0].annotation_id == a.annotation_id
    assert previous[0].review_status == "pending"


@pytest.mark.parametrize(
    "change",
    [
        {"reviewer_label": "bad"},
        {"reviewer_confidence": "2"},
        {"sample_id": "unknown"},
        {"original_prompt": "changed"},
        {"reviewer_rationale": ""},
        {"reviewer_intent": ""},
        {"reviewer_id": ""},
        {"reviewer_subcategories": "V6"},
        {"adjudicates": "absent"},
        {"proposed_annotation_id": "absent"},
    ],
)
def test_review_invalid_rows(tmp_path, snapshot, change):
    samples, _ = collect(snapshot[0])
    path = tmp_path / "review.csv"
    rows, fields = completed_csv(path, samples, [])
    rows[0].update(change)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError):
        import_review(path, samples, [])


def test_independent_export(tmp_path, snapshot, decision_data, run):
    samples, _ = collect(snapshot[0])
    previous = [annotation_for(samples[0], Decision(**decision_data), run, "rule")]
    path = tmp_path / "independent.csv"
    export_review(path, samples, previous, independent=True)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert all(not r["proposed_label"] and not r["proposed_annotation_id"] for r in rows)


def test_agreement_no_fabricated_scores():
    assert kappa([], []) is None
    assert kappa(["x"], ["x"]) is None
    assert kappa(["x", "x"], ["x", "x"]) is None
    assert kappa(["a", "b"], ["a", "b"]) == 1.0
    assert kappa(["a", "b"], ["b", "a"]) == -1.0
    assert agreement([], "A", "B")["paired_count"] == 0
    with pytest.raises(ValueError):
        agreement([], "A", "A")


def test_disagreement_and_adjudication(tmp_path, snapshot, decision_data, run):
    samples, _ = collect(snapshot[0])
    base = annotation_for(samples[0], Decision(**decision_data), run, "rule")
    humans = [
        SampleAnnotation.model_validate(
            {
                **base.model_dump(),
                "annotation_id": f"human-{i}",
                "annotation_method": "human",
                "annotator_id": name,
                "review_status": "approved",
                "requires_human_review": False,
            }
        )
        for i, name in enumerate(("A", "B"))
    ]
    humans[1] = SampleAnnotation.model_validate({**humans[1].model_dump(), "subcategories": ["V3"]})
    report = agreement(humans, "A", "B")
    assert report["disagreement_sample_ids"] == [samples[0].sample_id]
    assert report["label_kappa"] is None
    path = tmp_path / "adjudication.csv"
    rows, fields = completed_csv(path, samples, [])
    rows[0]["adjudicates"] = "human-0|human-1"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)
    adjudicated, _ = import_review(path, samples, humans)
    assert adjudicated[0].adjudicates == ["human-0", "human-1"]
    assert len(humans) == 2
