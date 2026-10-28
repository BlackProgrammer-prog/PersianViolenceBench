import pytest

from pvb.ingestion.normalize import collect
from pvb.storage.memory import InMemoryRepository


def test_idempotent_ingest_and_filters(snapshot):
    samples, sources = collect(snapshot[0])
    repo = InMemoryRepository()
    repo.ingest(sources, samples)
    repo.ingest(sources, samples)
    repo.upsert_samples(samples)
    repo.upsert_sample(samples[0])
    repo.upsert_source(sources[0])
    assert len(repo.list_samples()) == 2
    assert len(repo.list_sources()) == 2
    assert repo.get_sample(samples[0].sample_id) == samples[0]
    assert repo.get_source(sources[0].source_id) == sources[0]
    assert repo.get_sample("absent") is None
    assert repo.get_source("absent") is None
    assert (
        len(
            repo.list_samples(
                dataset_name="harmbench",
                dataset_split="validation",
                source_category="original category",
            )
        )
        == 1
    )
    assert repo.list_samples(source_category="absent") == []


def test_getters_isolate_mutable_lists(snapshot):
    samples, sources = collect(snapshot[0])
    repo = InMemoryRepository()
    repo.ingest(sources, samples)
    samples[0].source_tags.append("mutation")
    returned = repo.get_sample(samples[0].sample_id)
    assert "mutation" not in returned.source_tags
    returned.source_tags.append("another")
    assert "another" not in repo.get_sample(returned.sample_id).source_tags


def test_batch_failures_are_atomic(snapshot):
    samples, sources = collect(snapshot[0])
    repo = InMemoryRepository()
    with pytest.raises(ValueError, match="register source"):
        repo.upsert_samples(samples)
    assert repo.list_samples() == []
    repo.ingest(sources, samples)
    with pytest.raises(ValueError, match="count"):
        repo.ingest(sources, samples[:1])
    assert len(repo.list_samples()) == 2
    with pytest.raises(ValueError, match="duplicate sample ID"):
        repo.upsert_samples([samples[0], samples[0]])
    assert len(repo.list_samples()) == 2


def test_ingest_replaces_only_selected_namespace(snapshot, hb_record):
    from pvb.ingestion.adapters.harmbench import adapt
    from pvb.schemas.common import source_identity

    samples, sources = collect(snapshot[0])
    repo = InMemoryRepository()
    repo.ingest(sources, samples)
    original_source = next(s for s in sources if s.dataset_name == "harmbench")
    new_hash = "a" * 64
    new_source = original_source.model_copy(
        update={
            "sha256": new_hash,
            "source_id": source_identity(
                "harmbench", "validation", original_source.source_url, new_hash
            ),
        }
    )
    new_sample = adapt({**hb_record, "Behavior": "changed source snapshot"}, "validation")
    with pytest.raises(ValueError, match="different source snapshot"):
        repo.upsert_source(new_source)
    repo.ingest([new_source], [new_sample])
    assert len(repo.list_samples()) == 2
    assert repo.get_sample(new_sample.sample_id) == new_sample
    old_sample = next(s for s in samples if s.dataset_name == "harmbench")
    assert repo.get_sample(old_sample.sample_id) is None
    assert repo.get_source(original_source.source_id) is None
    assert len(repo.list_samples(dataset_name="strongreject")) == 1
