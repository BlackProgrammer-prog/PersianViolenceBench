"""Strict records for model preflight and immutable API accounting events."""

from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from pvb.schemas.annotations import Decision, Text, utc_timestamp
from pvb.schemas.common import StrictModel
from pvb.schemas.portability import PortabilityDecision
from pvb.schemas.samples import SHA256

Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]


class ModelMetadata(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    model_id: Text
    canonical_slug: str | None = None
    retrieved_at: str
    source: Text
    context_length: Annotated[int, Field(gt=0)]
    supported_parameters: list[str]
    input_usd_per_token: Money | None
    output_usd_per_token: Money | None
    request_usd: Money | None
    eligible_provider_tags: list[str]
    endpoint_details: list[dict[str, JsonValue]]
    account_restrictions: Literal["unknown"] = "unknown"
    structured_generation_tested: bool = False
    pricing_origin: Literal["provider_metadata", "operator_configured", "provider_budget"] = (
        "provider_metadata"
    )

    @model_validator(mode="after")
    def pricing_contract(self):
        rates = (self.input_usd_per_token, self.output_usd_per_token, self.request_usd)
        if self.pricing_origin == "provider_budget":
            if any(rate is not None for rate in rates):
                raise ValueError("billing-based budget must not invent token prices")
        elif any(rate is None for rate in rates):
            raise ValueError("token-price accounting requires complete rates")
        return self

    _time = field_validator("retrieved_at")(utc_timestamp)


class RequestEvent(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: Text
    run_id: Text
    sample_id: Text
    fingerprint: SHA256
    request_id: Text
    kind: Literal["reserved", "settled", "cache_hit"]
    created_at: str
    attempt_index: Count
    reserved_usd: Money = 0.0
    outcome: Literal["classified", "abstained", "failed", "cancelled"] | None = None
    error_code: str | None = None
    http_status: int | None = None
    retryable: bool = False
    retry_after_seconds: Money | None = None
    latency_seconds: Money | None = None
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    reported_cost_usd: Money | None = None
    estimated_cost_usd: Money | None = None
    accounted_cost_usd: Money = 0.0
    accounting_basis: Literal[
        "reported", "provider_meter", "token_estimate", "reservation", "cache", "pending"
    ] = "pending"
    model_returned: str | None = None
    routed_provider: str | None = None
    generation_id: str | None = None
    cache_origin_run_id: str | None = None
    cache_origin_event_id: str | None = None
    decision: Decision | None = None
    portability_decision: PortabilityDecision | None = None

    _time = field_validator("created_at")(utc_timestamp)

    @model_validator(mode="after")
    def consistent(self):
        if self.kind == "reserved" and (
            self.outcome is not None or self.accounting_basis != "pending"
        ):
            raise ValueError("reservation cannot have an outcome")
        if self.kind != "reserved" and self.outcome is None:
            raise ValueError("finished event requires an outcome")
        if (
            self.outcome == "classified"
            and self.decision is None
            and self.portability_decision is None
        ):
            raise ValueError("classified event requires a decision")
        if self.decision is not None and self.portability_decision is not None:
            raise ValueError("request event must contain only one assessment type")
        if self.decision is not None and not self.decision.requires_human_review:
            raise ValueError("automatic decisions require human review")
        return self


class SampleResult(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    sample_id: Text
    fingerprint: SHA256
    status: Literal["classified", "abstained", "failed", "not_scheduled", "interrupted"]
    annotation_id: str | None = None
    reason: str | None = None
    event_id: str | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "classified") != (self.annotation_id is not None):
            raise ValueError("classification requires exactly one annotation reference")
        return self
