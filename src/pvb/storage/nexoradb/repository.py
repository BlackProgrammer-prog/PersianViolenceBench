"""Transactional repository using verified native API, never query-string interpolation.

Single adapter owner per RocksDB path. Stage/validate the complete candidate
state through the reference implementation before native transaction mutation.
Small benchmark snapshots are read into memory; this is not a large-data adapter.
"""

import json
from pathlib import Path

from pvb.extraction.openrouter.models import RequestEvent
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.common import canonical_json
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord
from pvb.storage.memory import InMemoryRepository

ENTITIES = {
    "classification_request_events": (RequestEvent, "event_id"),
    "benchmark_sources": (SourceRecord, "source_id"),
    "benchmark_samples": (BenchmarkSample, "sample_id"),
    "annotation_runs": (AnnotationRun, "run_id"),
    "sample_annotations": (SampleAnnotation, "annotation_id"),
}


class NexoraError(RuntimeError):
    pass


def checked(result):
    if not result.success:
        raise NexoraError(result.error_msg)
    return result.data


class NexoraRepository:
    def __init__(self, path: Path):
        import nexoradb

        if nexoradb.__version__ != "0.2.1":
            raise NexoraError("only verified NexoraDataBase 0.2.1 is supported")
        self.engine = nexoradb.DocEngine(str(path))
        if not self.engine.is_healthy():
            raise NexoraError("native engine is unhealthy")
        for collection in ENTITIES:
            if not self.engine.collection_exists(collection):
                checked(self.engine.create_collection(collection))

    def _rows(self, collection):
        model, id_field = ENTITIES[collection]
        rows = json.loads(checked(self.engine.find_many(collection)))
        result = []
        for row in rows:
            identity = row.pop("_id")
            if identity != row[id_field]:
                raise NexoraError("native document identity mismatch")
            result.append(model.model_validate(row))
        return result

    def _state(self):
        repo = InMemoryRepository()
        for source in self._rows("benchmark_sources"):
            repo.upsert_source(source)
        repo.upsert_samples(self._rows("benchmark_samples"))
        for run in self._rows("annotation_runs"):
            repo.save_run(run)
        # Reference chains may span imports; reconstruct in dependency order.
        pending = self._rows("sample_annotations")
        while pending:
            ready = [
                a
                for a in pending
                if all(
                    ref in repo._annotations
                    for ref in ([a.supersedes_annotation_id] if a.supersedes_annotation_id else [])
                    + a.adjudicates
                )
            ]
            if not ready:
                raise NexoraError("annotation history has unresolved/cyclic references")
            repo.add_annotations(ready)
            done = {a.annotation_id for a in ready}
            pending = [a for a in pending if a.annotation_id not in done]
        events = self._rows("classification_request_events")
        repo.add_request_events(
            sorted(events, key=lambda e: (e.kind == "settled", e.created_at, e.event_id))
        )
        return repo

    @staticmethod
    def _documents(repo):
        groups = {
            "classification_request_events": repo.list_request_events(),
            "benchmark_sources": repo.list_sources(),
            "benchmark_samples": repo.list_samples(),
            "annotation_runs": repo.list_runs(),
            "sample_annotations": repo.list_annotations(),
        }
        return {
            collection: {
                getattr(row, ENTITIES[collection][1]): row.model_dump(mode="json") for row in rows
            }
            for collection, rows in groups.items()
        }

    def _mutate(self, operation):
        before = self._state()
        old = self._documents(before)
        operation(before)  # Complete validation before native writes.
        new = self._documents(before)
        tx = self.engine.begin_transaction()
        if tx is None:
            raise NexoraError("could not begin native transaction")
        try:
            for collection in ENTITIES:
                for identity in sorted(old[collection].keys() - new[collection].keys()):
                    checked(self.engine.delete_by_id_tx(tx, collection, identity))
                for identity, document in new[collection].items():
                    if old[collection].get(identity) == document:
                        continue
                    if identity in old[collection]:
                        checked(self.engine.delete_by_id_tx(tx, collection, identity))
                    checked(
                        self.engine.insert_one_tx(
                            tx, collection, canonical_json({"_id": identity, **document})
                        )
                    )
        except (NexoraError, OSError, RuntimeError, ValueError):
            checked(self.engine.rollback_transaction(tx))
            raise
        checked(self.engine.commit_transaction(tx))
        # Execute actual read-after-write, including full metadata and Unicode.
        if self._documents(self._state()) != new:
            raise NexoraError("read-after-write state mismatch")

    def ingest(self, sources, samples):
        self._mutate(lambda repo: repo.ingest(sources, samples))

    def upsert_source(self, source):
        self._mutate(lambda repo: repo.upsert_source(source))

    def upsert_sample(self, sample):
        self.upsert_samples([sample])

    def upsert_samples(self, samples):
        self._mutate(lambda repo: repo.upsert_samples(samples))

    def get_sample(self, sample_id):
        return self._state().get_sample(sample_id)

    def get_source(self, source_id):
        return self._state().get_source(source_id)

    def list_sources(self):
        return self._rows("benchmark_sources")

    def list_samples(self, **filters):
        return self._state().list_samples(**filters)

    def save_run(self, run):
        self._mutate(lambda repo: repo.save_run(run))

    def get_run(self, run_id):
        return self._state().get_run(run_id)

    def list_runs(self):
        return self._rows("annotation_runs")

    def add_annotations(self, annotations):
        self._mutate(lambda repo: repo.add_annotations(annotations))

    def list_annotations(self, sample_id=None):
        return self._state().list_annotations(sample_id)

    def add_request_events(self, events):
        self._mutate(lambda repo: repo.add_request_events(events))

    def list_request_events(self, run_id=None):
        return self._state().list_request_events(run_id)
