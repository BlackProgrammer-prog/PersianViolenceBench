import pytest

from pvb.extraction.pipeline import annotation_for
from pvb.extraction.quality import audit, grouped_summary
from pvb.ingestion.normalize import collect
from pvb.schemas.annotations import Decision
from pvb.storage.memory import InMemoryRepository


def test_quality_missing_runs_unknown_duplicates(snapshot, run, decision_data):
    samples, _ = collect(snapshot[0])
    a = annotation_for(samples[0], Decision(**decision_data), run, "rules")
    assert not audit(samples, [a], [])["passed"]
    assert not audit(samples, [a, a], [run])["passed"]
    assert not audit([], [a], [run])["passed"]
    assert audit(samples, [a], [run], accounted_unclassified={samples[1].sample_id})["passed"]
    assert not audit(samples, [a], [run], accounted_unclassified={"unknown"})["passed"]
    assert grouped_summary(samples, [a])["annotation_method"] == {"rule_based": 1}


def test_missing_context(synthetic_sample):
    sample = synthetic_sample("context fixture")
    sample = sample.model_copy(update={"functional_category": "contextual"})
    report = audit([sample], [], [], accounted_unclassified={sample.sample_id})
    assert not report["passed"] and any("context" in e for e in report["errors"])


def test_annotation_storage_contract(snapshot, run, decision_data):
    samples, sources = collect(snapshot[0])
    repo = InMemoryRepository()
    a = annotation_for(samples[0], Decision(**decision_data), run, "rule")
    with pytest.raises(ValueError):
        repo.add_annotations([a])
    repo.ingest(sources, samples)
    repo.save_run(run)
    repo.add_annotations([a])
    repo.add_annotations([a])
    assert len(repo.list_annotations(samples[0].sample_id)) == 1
    clone = repo.list_annotations()[0]
    clone.subcategories.append("V1")
    assert "V1" not in repo.list_annotations()[0].subcategories
    with pytest.raises(ValueError, match="immutable"):
        repo.add_annotations([a.model_copy(update={"rationale": "changed"})])
    with pytest.raises(ValueError):
        repo.add_annotations([a, a])
    with pytest.raises(ValueError, match="provenance"):
        repo.save_run(run.model_copy(update={"configuration": {"changed": True}}))
    assert repo.get_run(run.run_id) == run
    assert repo.get_run("absent") is None
    assert repo.list_runs() == [run]


def test_run_completion_and_orphan_prevention(snapshot, run, decision_data, hb_record):
    from pvb.ingestion.adapters.harmbench import adapt
    from pvb.schemas.annotation_runs import AnnotationRun
    from pvb.schemas.common import source_identity

    samples, sources = collect(snapshot[0])
    repo = InMemoryRepository()
    repo.ingest(sources, samples)
    repo.save_run(run)
    a = annotation_for(samples[0], Decision(**decision_data), run, "rule")
    repo.add_annotations([a])
    completed = AnnotationRun.model_validate(
        {
            **run.model_dump(),
            "status": "completed",
            "completed_at": "2026-10-24T01:00:00Z",
            "success_count": 1,
            "abstention_count": 1,
        }
    )
    repo.save_run(completed)
    repo.save_run(completed)
    with pytest.raises(ValueError, match="immutable"):
        repo.save_run(completed.model_copy(update={"configuration": {"changed": True}}))
    source = next(s for s in sources if s.dataset_name == samples[0].dataset_name)
    # Replace the annotated namespace only; the historical attempt must remain linked.
    if source.dataset_name == "harmbench":
        new_hash = "b" * 64
        new_source = source.model_copy(
            update={
                "sha256": new_hash,
                "source_id": source_identity(
                    source.dataset_name, source.dataset_split, source.source_url, new_hash
                ),
            }
        )
        new_sample = adapt({**hb_record, "Behavior": "new snapshot"}, "validation")
        with pytest.raises(ValueError, match="orphan"):
            repo.ingest([new_source], [new_sample])
    assert repo.list_annotations() == [a]
