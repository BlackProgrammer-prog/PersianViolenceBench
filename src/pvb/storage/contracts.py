"""Document persistence contracts; no database-specific assumptions."""

from collections.abc import Sequence
from typing import Protocol

from pvb.extraction.openrouter.models import RequestEvent
from pvb.schemas.annotation_runs import AnnotationRun
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.common import DatasetName, DatasetSplit
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord


class BenchmarkRepository(Protocol):
    """All upserts replace by deterministic ID; retries preserve record counts.

    A sample requires a registered source for its dataset/split. Implementations
    must validate batches before mutation and return detached validated records.
    A complete ingest replaces the supplied namespaces atomically, rejects
    multiple active snapshots per namespace, and retains unrelated namespaces.
    """

    def upsert_source(self, source: SourceRecord) -> None: ...

    def upsert_sample(self, sample: BenchmarkSample) -> None: ...

    def get_sample(self, sample_id: str) -> BenchmarkSample | None: ...

    def get_source(self, source_id: str) -> SourceRecord | None: ...

    def list_sources(self) -> list[SourceRecord]: ...

    def list_samples(
        self,
        *,
        dataset_name: DatasetName | None = None,
        dataset_split: DatasetSplit | None = None,
        source_category: str | None = None,
    ) -> list[BenchmarkSample]: ...

    def upsert_samples(self, samples: Sequence[BenchmarkSample]) -> None: ...

    def ingest(
        self, sources: Sequence[SourceRecord], samples: Sequence[BenchmarkSample]
    ) -> None: ...


class AnnotationRepository(Protocol):
    """Append-only attempts. Identical retries are idempotent, conflicts fail.

    Run progress updates may only finish the same run; provenance is immutable.
    Annotation references (sample, run, superseded/adjudicated attempts) must exist.
    """

    def save_run(self, run: "AnnotationRun") -> None: ...

    def get_run(self, run_id: str) -> "AnnotationRun | None": ...

    def list_runs(self) -> list["AnnotationRun"]: ...

    def add_annotations(self, annotations: Sequence["SampleAnnotation"]) -> None: ...

    def list_annotations(self, sample_id: str | None = None) -> list["SampleAnnotation"]: ...


class RequestEventRepository(Protocol):
    """Append-only HTTP attempt accounting, separate from annotation labels."""

    def add_request_events(self, events: Sequence[RequestEvent]) -> None: ...

    def list_request_events(self, run_id: str | None = None) -> list[RequestEvent]: ...
