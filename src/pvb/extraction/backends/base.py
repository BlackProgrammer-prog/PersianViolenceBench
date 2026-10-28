"""None is an explicit abstention, never an out-of-scope label."""

from typing import Protocol

from pvb.schemas.annotations import Decision, Method
from pvb.schemas.samples import BenchmarkSample


class AnnotationBackend(Protocol):
    method: Method
    identifier: str

    async def classify(self, sample: BenchmarkSample) -> Decision | None: ...
