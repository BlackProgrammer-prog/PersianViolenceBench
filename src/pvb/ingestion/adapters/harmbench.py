"""HarmBench text behavior records."""

from pathlib import Path

from pvb.schemas.common import parse_tags, record_hash, sample_identity, sha256_text
from pvb.schemas.samples import BenchmarkSample

from .base import IngestionError, read_records, required_text

COLUMNS = (
    "Behavior",
    "FunctionalCategory",
    "SemanticCategory",
    "Tags",
    "ContextString",
    "BehaviorID",
)


def adapt(record: dict[str, str], split: str) -> BenchmarkSample:
    required_text(record, ("Behavior", "BehaviorID", "SemanticCategory", "FunctionalCategory"))
    raw_hash = record_hash(record)
    return BenchmarkSample.model_validate(
        {
            "schema_version": "1.0.0",
            "sample_id": sample_identity("harmbench", split, raw_hash),
            "dataset_name": "harmbench",
            "dataset_split": split,
            "source_record_id": record["BehaviorID"],
            "original_language": "en",
            "original_prompt": record["Behavior"],
            "original_context": record["ContextString"] or None,
            "source_category": record["SemanticCategory"],
            "functional_category": record["FunctionalCategory"],
            "source_tags": parse_tags(record["Tags"]),
            "source_metadata": {
                "metadata_schema_version": "1.0.0",
                "source_type": "harmbench",
                "behavior_id": record["BehaviorID"],
                "semantic_category": record["SemanticCategory"],
                "functional_category": record["FunctionalCategory"],
                "tags_raw": record["Tags"],
                "context_string": record["ContextString"],
            },
            "raw_record_sha256": raw_hash,
            "prompt_sha256": sha256_text(record["Behavior"]),
        }
    )


def load(path: Path, split: str) -> list[BenchmarkSample]:
    result = []
    seen = set()
    for line, record in read_records(path, COLUMNS):
        try:
            sample = adapt(record, split)
            if sample.source_record_id in seen:
                raise ValueError(f"duplicate BehaviorID {sample.source_record_id!r}")
            seen.add(sample.source_record_id)
            result.append(sample)
        except ValueError as exc:
            raise IngestionError(f"{path}: line {line}: {exc}") from exc
    return result
