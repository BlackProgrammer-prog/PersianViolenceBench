"""Isolated, validated in-memory reference implementation (single-threaded)."""

from collections import Counter
from collections.abc import Sequence

from pvb.extraction.openrouter.models import RequestEvent
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.common import DatasetName, DatasetSplit
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord
from pvb.schemas.validation import check_unique


def clone_sample(sample: BenchmarkSample) -> BenchmarkSample:
    return BenchmarkSample.model_validate(sample.model_dump())


def clone_source(source: SourceRecord) -> SourceRecord:
    return SourceRecord.model_validate(source.model_dump())


class InMemoryRepository:
    def __init__(self) -> None:
        self._request_events: dict[str, RequestEvent] = {}
        self._runs: dict[str, AnnotationRun] = {}
        self._annotations: dict[str, SampleAnnotation] = {}
        self._sources: dict[str, SourceRecord] = {}
        self._samples: dict[str, BenchmarkSample] = {}

    def upsert_source(self, source: SourceRecord) -> None:
        source = clone_source(source)
        key = (source.dataset_name, source.dataset_split)
        if any(
            (s.dataset_name, s.dataset_split) == key and s.source_id != source.source_id
            for s in self._sources.values()
        ):
            raise ValueError("a different source snapshot already exists; use ingest to replace it")
        self._sources[source.source_id] = source

    def upsert_sample(self, sample: BenchmarkSample) -> None:
        self.upsert_samples([sample])

    def upsert_samples(self, samples: Sequence[BenchmarkSample]) -> None:
        validated = [clone_sample(sample) for sample in samples]
        check_unique(validated)
        namespaces = {(s.dataset_name, s.dataset_split) for s in self._sources.values()}
        if any((s.dataset_name, s.dataset_split) not in namespaces for s in validated):
            raise ValueError("register source before inserting samples")
        candidate = dict(self._samples)
        candidate.update({s.sample_id: s for s in validated})
        check_unique(list(candidate.values()))
        self._samples = candidate

    def get_sample(self, sample_id: str) -> BenchmarkSample | None:
        sample = self._samples.get(sample_id)
        return clone_sample(sample) if sample is not None else None

    def get_source(self, source_id: str) -> SourceRecord | None:
        source = self._sources.get(source_id)
        return clone_source(source) if source is not None else None

    def list_sources(self) -> list[SourceRecord]:
        return [clone_source(self._sources[key]) for key in sorted(self._sources)]

    def list_samples(
        self,
        *,
        dataset_name: DatasetName | None = None,
        dataset_split: DatasetSplit | None = None,
        source_category: str | None = None,
    ) -> list[BenchmarkSample]:
        return [
            clone_sample(s)
            for _, s in sorted(self._samples.items())
            if (dataset_name is None or s.dataset_name == dataset_name)
            and (dataset_split is None or s.dataset_split == dataset_split)
            and (source_category is None or s.source_category == source_category)
        ]

    def ingest(self, sources: Sequence[SourceRecord], samples: Sequence[BenchmarkSample]) -> None:
        staged = InMemoryRepository()
        for source in sources:
            if source.source_id in staged._sources:
                raise ValueError("duplicate source ID in ingest batch")
            staged.upsert_source(source)
        staged.upsert_samples(samples)
        counts = Counter((s.dataset_name, s.dataset_split) for s in staged._samples.values())
        for source in staged._sources.values():
            if counts[(source.dataset_name, source.dataset_split)] != source.record_count:
                raise ValueError("source count does not match ingest batch")
        namespaces = {(s.dataset_name, s.dataset_split) for s in staged._sources.values()}
        retained_sources = {
            k: s
            for k, s in self._sources.items()
            if (s.dataset_name, s.dataset_split) not in namespaces
        }
        retained_samples = {
            k: s
            for k, s in self._samples.items()
            if (s.dataset_name, s.dataset_split) not in namespaces
        }
        candidate_ids = set(retained_samples) | set(staged._samples)
        if any(a.sample_id not in candidate_ids for a in self._annotations.values()) or any(
            e.sample_id not in candidate_ids for e in self._request_events.values()
        ):
            raise ValueError("snapshot replacement would orphan historical annotations")
        self._sources = {**retained_sources, **staged._sources}
        self._samples = {**retained_samples, **staged._samples}

    def save_run(self, run: AnnotationRun) -> None:
        run = AnnotationRun.model_validate(run.model_dump())
        old = self._runs.get(run.run_id)
        if old and old != run:
            if old.status not in ("running", "partial"):
                raise ValueError("finished run is immutable")
            immutable = set(AnnotationRun.model_fields) - {
                "completed_at",
                "status",
                "success_count",
                "failure_count",
                "abstention_count",
            }
            if any(getattr(old, key) != getattr(run, key) for key in immutable):
                raise ValueError("run provenance is immutable")
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> AnnotationRun | None:
        run = self._runs.get(run_id)
        return AnnotationRun.model_validate(run.model_dump()) if run else None

    def list_runs(self) -> list[AnnotationRun]:
        return [self.get_run(key) for key in sorted(self._runs)]

    def add_annotations(self, annotations: Sequence[SampleAnnotation]) -> None:
        staged = dict(self._annotations)
        validated = [SampleAnnotation.model_validate(a.model_dump()) for a in annotations]
        if len({a.annotation_id for a in validated}) != len(validated):
            raise ValueError("duplicate annotation IDs in batch")
        for a in validated:
            run = self._runs.get(a.annotation_run_id)
            if a.sample_id not in self._samples or run is None:
                raise ValueError("annotation requires existing sample and run")
            if run.method != a.annotation_method or run.taxonomy_version != a.taxonomy_version:
                raise ValueError("annotation/run provenance mismatch")
            old = staged.get(a.annotation_id)
            if old and old != a:
                raise ValueError("historical annotation is immutable")
            for ref in (
                [a.supersedes_annotation_id] if a.supersedes_annotation_id else []
            ) + a.adjudicates:
                prior = staged.get(ref)
                if prior is None or prior.sample_id != a.sample_id or ref == a.annotation_id:
                    raise ValueError("invalid historical annotation reference")
            staged[a.annotation_id] = a
        self._annotations = staged

    def list_annotations(self, sample_id: str | None = None) -> list[SampleAnnotation]:
        return [
            SampleAnnotation.model_validate(a.model_dump())
            for _, a in sorted(self._annotations.items())
            if sample_id is None or a.sample_id == sample_id
        ]

    def add_request_events(self, events: Sequence[RequestEvent]) -> None:
        candidate = dict(self._request_events)
        for raw in events:
            event = RequestEvent.model_validate(raw.model_dump())
            run = self._runs.get(event.run_id)
            if run is None or run.method != "llm" or event.sample_id not in self._samples:
                raise ValueError("request event requires existing LLM run and sample")
            old = candidate.get(event.event_id)
            if old is not None and old != event:
                raise ValueError("request event history is immutable")
            if event.kind == "settled":
                reserve = next(
                    (
                        e
                        for e in candidate.values()
                        if e.request_id == event.request_id and e.kind == "reserved"
                    ),
                    None,
                )
                if (
                    reserve is None
                    or reserve.run_id != event.run_id
                    or reserve.sample_id != event.sample_id
                    or reserve.fingerprint != event.fingerprint
                ):
                    raise ValueError("settlement requires matching reservation")
                if any(
                    e.request_id == event.request_id
                    and e.kind == "settled"
                    and e.event_id != event.event_id
                    for e in candidate.values()
                ):
                    raise ValueError("request already settled")
            candidate[event.event_id] = event
        self._request_events = candidate

    def list_request_events(self, run_id: str | None = None) -> list[RequestEvent]:
        return [
            RequestEvent.model_validate(e.model_dump())
            for _, e in sorted(self._request_events.items())
            if run_id is None or e.run_id == run_id
        ]
