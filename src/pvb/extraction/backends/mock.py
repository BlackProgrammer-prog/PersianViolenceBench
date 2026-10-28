"""Explicit test fixture backend; never selected by the production CLI."""

from pvb.schemas.annotations import Decision
from pvb.schemas.samples import BenchmarkSample


class MockBackend:
    method = "llm"
    identifier = "test-fixture-only"

    def __init__(self, decisions: dict[str, Decision | None]):
        self.decisions = decisions

    async def classify(self, sample: BenchmarkSample) -> Decision | None:
        return self.decisions[sample.sample_id]
