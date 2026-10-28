"""StrongREJECT records, with no invented original IDs or split."""

from pathlib import Path

from pvb.schemas.common import record_hash, sample_identity, sha256_text
from pvb.schemas.samples import BenchmarkSample

from .base import IngestionError, read_records, required_text

COLUMNS = ("category", "source", "forbidden_prompt")


def adapt(record: dict[str, str], split: str = "unspecified") -> BenchmarkSample:
    required_text(record, ("category", "source", "forbidden_prompt"))
    raw_hash = record_hash(record)
    return BenchmarkSample.model_validate(
        {
            "schema_version": "1.0.0",
            "sample_id": sample_identity("strongreject", split, raw_hash),
            "dataset_name": "strongreject",
            "dataset_split": split,
            "source_record_id": None,
            "original_language": "en",
            "original_prompt": record["forbidden_prompt"],
            "original_context": None,
            "source_category": record["category"],
            "functional_category": None,
            "source_tags": [],
            "source_metadata": {
                "metadata_schema_version": "1.0.0",
                "source_type": "strongreject",
                "prompt_source": record["source"],
            },
            "raw_record_sha256": raw_hash,
            "prompt_sha256": sha256_text(record["forbidden_prompt"]),
        }
    )


def load(path: Path, split: str = "unspecified") -> list[BenchmarkSample]:
    result = []
    seen = set()
    for line, record in read_records(path, COLUMNS):
        try:
            sample = adapt(record, split)
            if sample.sample_id in seen:
                raise ValueError(f"duplicate content/sample ID {sample.sample_id}")
            seen.add(sample.sample_id)
            result.append(sample)
        except ValueError as exc:
            raise IngestionError(f"{path}: line {line}: {exc}") from exc
    return result
