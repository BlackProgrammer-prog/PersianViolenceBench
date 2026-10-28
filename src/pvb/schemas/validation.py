"""Collection invariants shared by ingestion and persistence."""

from .samples import BenchmarkSample


def check_unique(samples: list[BenchmarkSample]) -> None:
    ids: set[str] = set()
    original_ids: set[tuple[str, str, str]] = set()
    for sample in samples:
        if sample.sample_id in ids:
            raise ValueError(f"duplicate sample ID: {sample.sample_id}")
        ids.add(sample.sample_id)
        if sample.source_record_id is not None:
            key = (sample.dataset_name, sample.dataset_split, sample.source_record_id)
            if key in original_ids:
                raise ValueError(f"duplicate source record ID: {key}")
            original_ids.add(key)
