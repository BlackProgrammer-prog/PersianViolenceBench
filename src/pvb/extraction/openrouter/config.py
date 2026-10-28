"""Phase 3 paths and research controls; credentials belong only in root .env."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field

from pvb.schemas.annotations import Text
from pvb.schemas.common import DatasetName, StrictModel


class RunConfig(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    root: str = ".."
    input: str = "data/normalized/benchmark_samples.jsonl"
    sources: str = "data/normalized/benchmark_sources.jsonl"
    taxonomy: str = "configs/taxonomy.yaml"
    prompt: str = "configs/prompts/violence_classifier_v1.txt"
    prompt_version: str = "violence-classifier-1.1.0"
    output: str = "runs/phase3"
    cache: str = "runs/phase3/cache"
    database: str = "data/nexoradb"
    rules_annotations: str = "data/extracted/annotations.jsonl"
    seed: int = 20261024
    requests_per_minute: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 30.0
    low_confidence_threshold: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.7
    source_violence_categories: dict[DatasetName, list[Text]] = Field(
        default_factory=lambda: {"strongreject": ["Violence"], "harmbench": []}
    )
    selected_sample_ids: list[Text] | None = None


def load_config(path: Path) -> tuple[RunConfig, Path]:
    config = RunConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    root = (path.resolve().parent / config.root).resolve()
    protected = [
        (root / config.input).resolve(),
        (root / config.sources).resolve(),
        (root / config.taxonomy).resolve(),
        (root / config.prompt).resolve(),
    ]
    for value in (config.output, config.cache, config.database):
        target = (root / value).resolve()
        if any(p == target or p.is_relative_to(target) for p in protected) or any(
            target.is_relative_to((root / d).resolve())
            for d in ("data/raw", "data/normalized", "configs", "src", "docs")
        ):
            raise ValueError("Phase 3 output/cache/database overlaps protected paths")
    return config, root
