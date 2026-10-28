"""Independent, provisional assessment of cross-cultural translation portability."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from pvb.schemas.common import StrictModel

PortabilityLabel = Literal["translation_portable", "localization_required", "uncertain"]
Dependency = Literal[
    "language_pragmatics",
    "legal_institutional",
    "social_norms",
    "political_historical",
    "local_resources",
    "group_identity_context",
    "other",
]
ShortText = Annotated[str, Field(min_length=1, max_length=600)]


class PortabilityDecision(StrictModel):
    label: PortabilityLabel
    dependency_dimensions: list[Dependency]
    source_context_summary: ShortText | None
    rationale: Annotated[str, Field(min_length=1, max_length=1200)]
    localization_guidance: ShortText | None
    invariants_to_preserve: Annotated[list[ShortText], Field(min_length=1, max_length=5)]
    evidence: list[Annotated[str, Field(min_length=1, max_length=160)]]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    requires_human_review: Literal[True]
    translation_tested: Literal[False]

    @model_validator(mode="after")
    def consistent(self):
        if len(set(self.dependency_dimensions)) != len(self.dependency_dimensions):
            raise ValueError("duplicate dependency dimensions")
        if self.label == "translation_portable" and (
            self.dependency_dimensions or self.localization_guidance is not None
        ):
            raise ValueError("portable decisions cannot require localization")
        if self.label == "localization_required" and not (
            self.dependency_dimensions
            and self.source_context_summary
            and self.localization_guidance
            and self.evidence
        ):
            raise ValueError("localization requires grounded dependencies and human guidance")
        if self.label == "uncertain" and not self.localization_guidance:
            raise ValueError("uncertainty requires a human-review question")
        return self
