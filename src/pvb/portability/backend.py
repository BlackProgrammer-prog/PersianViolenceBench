"""Cultural assessment using the existing paid request, cache and budget lifecycle."""

from pydantic import ValidationError

from pvb.extraction.backends.gapgpt import GapGPTBackend
from pvb.extraction.backends.llm import evidence_candidates
from pvb.extraction.backends.openrouter import ClassificationError
from pvb.ingestion.export import decode_json
from pvb.schemas.portability import PortabilityDecision


def response_schema(sample):
    schema = PortabilityDecision.model_json_schema()
    schema["required"] = list(schema["properties"])
    choices = evidence_candidates(sample)
    schema["properties"]["evidence"]["items"] = {
        "type": "integer",
        "minimum": 0,
        "maximum": max(0, len(choices) - 1),
    }
    schema["properties"]["evidence"]["description"] = (
        "Zero-based indices into evidence_catalog, not quotation strings."
    )
    if not choices:
        schema["properties"]["evidence"]["maxItems"] = 0
    return schema


class PortabilityBackend(GapGPTBackend):
    def payload(self, sample):
        payload = super().payload(sample)
        payload["response_format"]["json_schema"] = {
            "name": "cultural_portability",
            "strict": True,
            "schema": response_schema(sample),
        }
        return payload

    def is_abstention(self, decision):
        # An explicit uncertainty label is a completed cultural assessment.
        return False

    def event_assessment(self, decision):
        return {"portability_decision": decision}

    def _parse(self, envelope, sample, *, from_cache=False):
        if not isinstance(envelope, dict):
            raise ClassificationError("invalid_response_envelope", True)
        if "error" in envelope:
            code = envelope["error"].get("code") if isinstance(envelope["error"], dict) else None
            status = code if type(code) is int else None
            if status == 403:
                # Upstream refusal inside HTTP 200 is sample-scoped; gateway
                # HTTP 403 authentication/access errors still stop globally.
                raise ClassificationError("provider_refusal")
            raise ClassificationError(
                "provider_error", status in (408, 429, 500, 502, 503, 504), status
            )
        if envelope.get("model") not in (self.settings.model, self.metadata.canonical_slug):
            raise ClassificationError("unexpected_model")
        try:
            choice = envelope["choices"][0]
            message = choice["message"]
            if message.get("refusal") or choice.get("finish_reason") in ("content_filter", "error"):
                raise ClassificationError("provider_refusal")
            if choice.get("finish_reason") != "stop":
                raise ClassificationError("incomplete_generation", True)
            text = message["content"]
            if not isinstance(text, str) or self.settings.redact(text) != text:
                raise ClassificationError("sensitive_response_rejected")
            try:
                raw = decode_json(text)
            except ValueError:
                raise ClassificationError("invalid_json_output", True) from None
            if not isinstance(raw, dict) or set(raw) != set(PortabilityDecision.model_fields):
                raise ClassificationError("missing_or_extra_classification_fields", True)
            if not from_cache:
                indices = raw["evidence"]
                candidates = evidence_candidates(sample)
                if not isinstance(indices, list) or any(
                    type(i) is not int or not 0 <= i < len(candidates) for i in indices
                ):
                    raise ClassificationError("unsupported_evidence", True)
                raw = {**raw, "evidence": [candidates[i] for i in indices]}
            decision = PortabilityDecision.model_validate(raw)
            if any(
                not any(e in src for src in (sample.original_prompt, sample.original_context or ""))
                for e in decision.evidence
            ):
                raise ClassificationError("unsupported_evidence", True)
            return decision
        except (KeyError, TypeError, IndexError, ValueError, ValidationError):
            raise ClassificationError("invalid_portability_output", True) from None
