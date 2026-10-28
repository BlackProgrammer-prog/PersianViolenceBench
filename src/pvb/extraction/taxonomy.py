"""Strict official taxonomy loader."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import model_validator

from pvb.schemas.annotations import Label, Subcategory, Text
from pvb.schemas.common import StrictModel


class Taxonomy(StrictModel):
    schema_version: Literal["1.0.0"]
    taxonomy_id: Literal["pvb-violence"]
    version: Literal["1.0.0"]
    definition: Text
    labels: list[Label]
    subcategories: dict[Subcategory, Text]
    rules: list[Text]

    @model_validator(mode="after")
    def complete(self) -> "Taxonomy":
        if (
            set(self.labels) != {"unsafe_violence", "benign_violence_related", "out_of_scope"}
            or len(self.labels) != 3
        ):
            raise ValueError("official labels required exactly once")
        if set(self.subcategories) != {"V1", "V2", "V3", "V4", "V5"} or not self.rules:
            raise ValueError("official subcategories and rules required")
        return self


def load_taxonomy(path: Path) -> Taxonomy:
    return Taxonomy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
