from pvb.extraction.rules import VERSION, classify_rules
from pvb.schemas.samples import BenchmarkSample


class RuleBasedBackend:
    method = "rule_based"
    identifier = VERSION

    async def classify(self, sample: BenchmarkSample):
        return classify_rules(sample)
