"""Independent annotation attempts; canonical samples are never extended."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import StrictModel

Label = Literal["unsafe_violence", "benign_violence_related", "out_of_scope"]
Subcategory = Literal["V1", "V2", "V3", "V4", "V5"]
Method = Literal["rule_based", "llm", "human"]
Status = Literal["pending", "in_review", "approved", "rejected", "needs_revision"]
Text = Annotated[str, Field(min_length=1)]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("timestamp must be ISO 8601 UTC")
    return parsed.isoformat().replace("+00:00", "Z")


class Decision(StrictModel):
    label: Label
    subcategories: list[Subcategory]
    intent: Literal["harmful", "benign", "ambiguous"]
    target: Literal["other_person", "group", "self", "none", "unknown"]
    actionability: Literal["none", "low", "medium", "high"]
    risk_severity: Literal["low", "medium", "high", "critical"]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    rationale: Text
    evidence: list[str] = Field(default_factory=list)
    requires_human_review: bool
    overlapping_risks: list[Literal["self_harm"]] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale is blank")
        return value

    @model_validator(mode="after")
    def consistent(self) -> "Decision":
        if len(set(self.subcategories)) != len(self.subcategories):
            raise ValueError("duplicate subcategories")
        if self.label == "unsafe_violence":
            if (
                not self.subcategories
                or self.intent != "harmful"
                or self.target not in ("other_person", "group")
            ):
                raise ValueError(
                    "unsafe label requires harmful intent, others target and subcategories"
                )
        elif self.subcategories:
            raise ValueError("non-unsafe labels must have empty subcategories")
        if self.label == "benign_violence_related" and self.intent != "benign":
            raise ValueError("benign label requires benign intent")
        if self.intent == "ambiguous" and not self.requires_human_review:
            raise ValueError("ambiguous intent requires review")
        return self


class SampleAnnotation(Decision):
    annotation_id: Text
    schema_version: Literal["1.0.0"] = "1.0.0"
    sample_id: Text
    taxonomy_id: Literal["pvb-violence"] = "pvb-violence"
    taxonomy_version: Literal["1.0.0"] = "1.0.0"
    review_status: Status
    annotation_method: Method
    annotator_id: Text
    annotation_run_id: Text
    created_at: str
    updated_at: str
    supersedes_annotation_id: str | None = None
    adjudicates: list[str] = Field(default_factory=list)
    reviewer_notes: str | None = None

    _timestamps = field_validator("created_at", "updated_at")(utc_timestamp)

    @model_validator(mode="after")
    def provenance(self) -> "SampleAnnotation":
        for value in (
            self.annotation_id,
            self.sample_id,
            self.annotator_id,
            self.annotation_run_id,
        ):
            if not value.strip():
                raise ValueError("annotation identifiers cannot be blank")
        if len(set(self.adjudicates)) != len(self.adjudicates) or (
            self.adjudicates and len(self.adjudicates) < 2
        ):
            raise ValueError("adjudication requires at least two unique prior attempts")
        if datetime.fromisoformat(self.updated_at.replace("Z", "+00:00")) < datetime.fromisoformat(
            self.created_at.replace("Z", "+00:00")
        ):
            raise ValueError("updated_at before created_at")
        if self.annotation_method != "human" and self.review_status != "pending":
            raise ValueError("automatic attempts must remain pending; create a human attempt")
        if self.annotation_method != "human" and not self.requires_human_review:
            raise ValueError("automatic annotations require human review")
        if self.review_status == "approved" and self.requires_human_review:
            raise ValueError("approved human annotation cannot require review")
        if self.adjudicates and self.annotation_method != "human":
            raise ValueError("only human adjudication is supported")
        return self
