"""OpenRouter classifier: structured requests, explicit payment gate and durable usage.

Dataset text is only JSON in a user message. Only HTTP(S) requests made by
this module are sent via an injected httpx client; no dataset text is executed.
"""

import asyncio
import json
import math
import random
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from pvb.extraction.backends.llm import evidence_candidates, response_schema
from pvb.extraction.io import write_json
from pvb.extraction.openrouter.accounting import Budget, Journal
from pvb.extraction.openrouter.metadata import price
from pvb.extraction.openrouter.models import ModelMetadata, RequestEvent
from pvb.extraction.openrouter.settings import ConfigurationError, OpenRouterSettings
from pvb.ingestion.export import decode_json
from pvb.schemas.annotations import Decision, utc_now
from pvb.schemas.common import canonical_json, sha256_text
from pvb.schemas.samples import BenchmarkSample

RETRY_GUIDANCE = {
    "invalid_portability_output": (
        "Follow the cultural-portability schema and label consistency rules. Portable has no "
        "essential dependencies or localization guidance; localization_required needs grounded "
        "dependencies, source context, evidence indices and human-review guidance."
    ),
    "invalid_json_output": "Return a single JSON object only, without markdown fences or prose.",
    "invalid_decision_schema": (
        "Use exactly the fields, types and enum values in response_format; include every field."
    ),
    "inconsistent_decision": (
        "Keep label, intent, target and subcategories consistent. unsafe_violence requires "
        "harmful intent, other_person/group and at least one V1-V5 subcategory. Other labels "
        "require subcategories=[]. benign_violence_related requires intent=benign."
    ),
    "missing_or_extra_classification_fields": "Include exactly all fields in response_format.",
    "unsupported_evidence": (
        "Return evidence as zero-based integer indices from the supplied evidence_catalog. "
        "Do not return quoted strings or invent indices. Use evidence=[] if no catalog "
        "excerpt supports the classification. Reassess the original request."
    ),
    "rationale_or_evidence_too_long": "Keep rationale under 1200 characters and each excerpt under 240.",
    "review_requirement_violation": "Always set requires_human_review=true.",
}


class ClassificationError(RuntimeError):
    def __init__(
        self,
        code: str,
        retryable: bool = False,
        status: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(code)  # Never include provider body/headers/exception messages.
        self.code, self.retryable, self.status, self.retry_after = (
            code,
            retryable,
            status,
            retry_after,
        )


def retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        if not math.isfinite(seconds):
            return None
        return max(0.0, seconds)
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


class OpenRouterBackend:
    method = "llm"

    def __init__(
        self,
        *,
        settings: OpenRouterSettings,
        metadata: ModelMetadata,
        client: httpx.AsyncClient,
        prompt: str,
        taxonomy: dict,
        prompt_version: str,
        run_id: str,
        journal: Journal,
        cache_dir: Path,
        requests_per_minute: float,
        paid_authorized: bool = False,
    ):
        settings.require_ready()
        if metadata.model_id != settings.model or (
            settings.provider == "openrouter" and not metadata.eligible_provider_tags
        ):
            raise ConfigurationError("Model metadata does not match the selected model.")
        self.settings, self.metadata, self.client = settings, metadata, client
        self.prompt, self.taxonomy, self.prompt_version = prompt, taxonomy, prompt_version
        self.run_id, self.journal, self.cache_dir = run_id, journal, cache_dir
        self.paid_authorized = paid_authorized
        self.identifier = settings.provider + ":" + settings.model
        self.budget = Budget(settings.max_cost_usd, journal)
        self.semaphore = asyncio.Semaphore(settings.concurrency)
        self.pacing_lock = asyncio.Lock()
        if not math.isfinite(requests_per_minute) or requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive and finite")
        self.interval, self.next_request = 60.0 / requests_per_minute, 0.0
        self.last_events: dict[str, RequestEvent] = {}
        self.stop_code: str | None = None

    def payload(self, sample: BenchmarkSample) -> dict:
        return {
            "model": self.settings.model,
            **(
                {"reasoning": {"enabled": self.settings.reasoning_enabled}}
                if self.settings.reasoning_enabled is not None
                else {}
            ),
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": self.prompt
                    + "\nTRUSTED_TAXONOMY_JSON:\n"
                    + canonical_json(self.taxonomy),
                },
                {
                    "role": "user",
                    "content": canonical_json(
                        {
                            "original_prompt": sample.original_prompt,
                            "original_context": sample.original_context,
                        }
                    ),
                },
                {
                    "role": "user",
                    "content": canonical_json({"evidence_catalog": evidence_candidates(sample)}),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "violence_classification",
                    "strict": True,
                    "schema": response_schema(sample),
                },
            },
            **self.provider_routing(),
        }

    def provider_routing(self) -> dict:
        m = self.metadata
        return {
            "provider": {
                "require_parameters": True,
                "only": m.eligible_provider_tags,
                "allow_fallbacks": False,
                "max_price": {
                    "prompt": m.input_usd_per_token * 1_000_000,
                    "completion": m.output_usd_per_token * 1_000_000,
                    "request": m.request_usd,
                },
            },
        }

    async def prepare_request(self, request_id: str) -> None:
        """Provider hook: no generation may occur here, before reservation."""

    async def complete_request(self, request_id: str) -> None:
        """Provider hook: obtain billing information before immutable settlement."""

    def is_abstention(self, decision) -> bool:
        return decision.intent == "ambiguous"

    def event_assessment(self, decision) -> dict:
        return {"decision": decision}

    def fingerprint(self, sample: BenchmarkSample) -> str:
        return sha256_text(
            canonical_json(
                {
                    "sample_id": sample.sample_id,
                    "payload": self.payload(sample),
                    "taxonomy_version": self.taxonomy["version"],
                    "prompt_version": self.prompt_version,
                    "schema_version": "1.0.0",
                    "validation_retry_policy": "1.0.0",
                    "endpoint": self.settings.base_url,
                }
            )
        )

    def reservation(self) -> float:
        m = self.metadata
        # Reserve a whole verified context, not a fabricated exact tokenizer count.
        return (
            m.context_length * m.input_usd_per_token
            + self.settings.max_output_tokens * m.output_usd_per_token
            + m.request_usd
        ) * 1.05

    def _parse(self, envelope: dict, sample: BenchmarkSample, *, from_cache=False) -> Decision:
        if not isinstance(envelope, dict):
            raise ClassificationError("invalid_response_envelope", True)
        if "error" in envelope:
            code = envelope["error"].get("code") if isinstance(envelope["error"], dict) else None
            status = code if isinstance(code, int) else None
            raise ClassificationError(
                "provider_error", status in (408, 429, 500, 502, 503, 504), status
            )
        if not envelope.get("model") or envelope.get("model") not in (
            self.settings.model,
            self.metadata.canonical_slug,
        ):
            raise ClassificationError("unexpected_model")
        try:
            choice = envelope["choices"][0]
            message = choice["message"]
            if message.get("refusal") or choice.get("finish_reason") in ("content_filter", "error"):
                raise ClassificationError("provider_refusal")
            if choice.get("finish_reason") != "stop":
                raise ClassificationError("incomplete_generation", True)
            text = message["content"]
            # A key echoed by an upstream service is never accepted or persisted.
            if not isinstance(text, str) or self.settings.redact(text) != text:
                raise ClassificationError("sensitive_response_rejected")
            try:
                raw = decode_json(text)
            except ValueError:
                raise ClassificationError("invalid_json_output", True) from None
            if not isinstance(raw, dict) or set(raw) != set(Decision.model_fields):
                raise ClassificationError("missing_or_extra_classification_fields", True)
            if not from_cache:
                references = raw.get("evidence")
                candidates = evidence_candidates(sample)
                if not isinstance(references, list) or any(
                    type(index) is not int or not 0 <= index < len(candidates)
                    for index in references
                ):
                    raise ClassificationError("unsupported_evidence", True)
                raw = {**raw, "evidence": [candidates[index] for index in references]}
            try:
                decision = Decision.model_validate(raw)
            except ValidationError as exc:
                code = (
                    "inconsistent_decision"
                    if any(not error["loc"] for error in exc.errors(include_input=False))
                    else "invalid_decision_schema"
                )
                raise ClassificationError(code, True) from None
            if not decision.requires_human_review:
                raise ClassificationError("review_requirement_violation", True)
            if len(decision.rationale) > 1200 or any(len(e) > 240 for e in decision.evidence):
                raise ClassificationError("rationale_or_evidence_too_long", True)
            sources = (sample.original_prompt, sample.original_context or "")
            if any(not e or not any(e in source for source in sources) for e in decision.evidence):
                raise ClassificationError("unsupported_evidence", True)
            return decision
        except (KeyError, TypeError, IndexError, ValueError, ValidationError):
            raise ClassificationError("invalid_structured_output", True) from None

    def _accounting(self, envelope, reservation: float) -> dict:
        usage = envelope.get("usage", {}) if isinstance(envelope, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        inp, out, actual = None, None, None
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                if key == "prompt_tokens":
                    inp = value
                else:
                    out = value
        try:
            actual = price(usage.get("cost"))
        except ValueError:
            pass
        estimate = None
        if inp is not None and out is not None:
            estimate = (
                inp * self.metadata.input_usd_per_token
                + out * self.metadata.output_usd_per_token
                + self.metadata.request_usd
            )
        # Missing provider cost does not release the reservation, even with token estimates.
        return {
            "input_tokens": inp,
            "output_tokens": out,
            "reported_cost_usd": actual,
            "estimated_cost_usd": estimate,
            "accounted_cost_usd": actual
            if actual is not None
            else max(reservation, estimate or 0.0),
            "accounting_basis": "reported" if actual is not None else "reservation",
        }

    async def classify(self, sample: BenchmarkSample) -> Decision | None:
        if not self.paid_authorized:
            raise ConfigurationError("Paid classification requires an explicit confirmation flag.")
        fingerprint = self.fingerprint(sample)
        cache = self.cache_dir / (fingerprint + ".json")
        if cache.exists():
            try:
                saved = json.loads(cache.read_text())
                if saved["fingerprint"] != fingerprint:
                    raise ValueError("cache fingerprint mismatch")
                decision = self._parse(
                    {
                        "model": self.settings.model,
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {"content": canonical_json(saved["decision"])},
                            }
                        ],
                    },
                    sample,
                    from_cache=True,
                )
                if not decision.requires_human_review or self.settings.redact(
                    canonical_json(saved)
                ) != canonical_json(saved):
                    raise ValueError("invalid cache")
            except (OSError, ValueError, KeyError, TypeError):
                raise ClassificationError("invalid_cache") from None
            event = RequestEvent(
                event_id=uuid.uuid4().hex,
                run_id=self.run_id,
                sample_id=sample.sample_id,
                fingerprint=fingerprint,
                request_id="cache-" + uuid.uuid4().hex,
                kind="cache_hit",
                created_at=utc_now(),
                attempt_index=0,
                outcome="abstained" if self.is_abstention(decision) else "classified",
                accounting_basis="cache",
                cache_origin_run_id=saved["origin_run_id"],
                cache_origin_event_id=saved["origin_event_id"],
                **self.event_assessment(decision),
            )
            self.journal.append(event)
            self.last_events[sample.sample_id] = event
            return None if self.is_abstention(decision) else decision
        payload = self.payload(sample)
        # A conservative byte proxy is used only for rejection, never as actual usage.
        input_proxy = (
            len(
                canonical_json(
                    {"messages": payload["messages"], "schema": payload["response_format"]}
                ).encode()
            )
            + 512
        )
        if input_proxy + self.settings.max_output_tokens > self.metadata.context_length:
            raise ClassificationError("context_length_preflight_failed")
        offset = sum(
            e.kind == "reserved" and e.sample_id == sample.sample_id for e in self.journal.events
        )
        async with self.semaphore:
            for attempt in range(self.settings.max_retries + 1):
                if self.stop_code:
                    raise ClassificationError(self.stop_code)
                request_id = uuid.uuid4().hex
                reservation = self.reservation()
                reserve = RequestEvent(
                    event_id=request_id + "-reserved",
                    run_id=self.run_id,
                    sample_id=sample.sample_id,
                    fingerprint=fingerprint,
                    request_id=request_id,
                    kind="reserved",
                    created_at=utc_now(),
                    attempt_index=offset + attempt,
                    reserved_usd=reservation,
                )
                started, envelope, error, decision = time.monotonic(), None, None, None
                reserved, request_task = False, None
                try:
                    async with self.pacing_lock:
                        await asyncio.sleep(max(0.0, self.next_request - time.monotonic()))
                        if self.stop_code:
                            raise ClassificationError(self.stop_code)
                        await self.prepare_request(request_id)
                        await self.budget.reserve(reserve)
                        reserved = True
                        started = time.monotonic()
                        request_task = asyncio.create_task(
                            self.client.post(
                                self.settings.base_url + "/chat/completions",
                                headers={
                                    "Authorization": "Bearer "
                                    + self.settings.credential.get_secret_value()
                                },
                                json=payload,
                                timeout=self.settings.timeout_seconds,
                            )
                        )
                        # Start the HTTP coroutine before releasing the pacing gate.
                        # Disk fsync/DB time must not consume the next request's interval.
                        await asyncio.sleep(0)
                        self.next_request = time.monotonic() + self.interval
                    response = await asyncio.wait_for(request_task, self.settings.timeout_seconds)
                    await self.complete_request(request_id)
                    try:
                        envelope = response.json()
                    except ValueError:
                        envelope = None
                    if response.status_code != 200:
                        status = response.status_code
                        raise ClassificationError(
                            f"http_{status}",
                            status in (408, 429) or 500 <= status <= 599,
                            status,
                            retry_after_seconds(response.headers.get("Retry-After")),
                        )
                    if envelope is None:
                        raise ClassificationError("invalid_response_json", True)
                    decision = self._parse(envelope, sample)
                except asyncio.CancelledError:
                    if request_task is not None and not request_task.done():
                        request_task.cancel()
                        await asyncio.gather(request_task, return_exceptions=True)
                    if not reserved:
                        raise
                    error = ClassificationError("request_cancelled")
                    event = self._event(
                        sample, reserve, envelope, started, error, None, cancelled=True
                    )
                    await self.budget.settle(event)
                    self.last_events[sample.sample_id] = event
                    raise
                except (httpx.TimeoutException, asyncio.TimeoutError):
                    error = ClassificationError("request_timeout", True)
                except httpx.RequestError:
                    error = ClassificationError("network_error", True)
                except ClassificationError as exc:
                    error = exc
                if not reserved:
                    raise error
                event = self._event(sample, reserve, envelope, started, error, decision)
                await self.budget.settle(event)
                self.last_events[sample.sample_id] = event
                if not error:
                    write_json(
                        cache,
                        {
                            "fingerprint": fingerprint,
                            "origin_event_id": event.event_id,
                            "origin_run_id": self.run_id,
                            "decision": decision.model_dump(mode="json"),
                        },
                    )
                    return None if self.is_abstention(decision) else decision
                if (
                    error.status in (400, 401, 402, 403, 404, 422)
                    or error.code == "unexpected_model"
                ):
                    self.stop_code = error.code
                if not error.retryable or attempt == self.settings.max_retries:
                    raise error
                # Trusted, allowlisted feedback only: never replay invalid provider
                # text or change a rejected decision into an accepted annotation.
                guidance = RETRY_GUIDANCE.get(error.code)
                if guidance:
                    payload = {
                        **payload,
                        "messages": [
                            *self.payload(sample)["messages"],
                            {
                                "role": "system",
                                "content": "VALIDATION_FEEDBACK: " + guidance,
                            },
                        ],
                    }
                # Honour Retry-After in full; cancellation remains responsive.
                delay = max(error.retry_after or 0.0, min(2**attempt, 30) + random.uniform(0, 0.5))
                await asyncio.sleep(delay)
        raise ClassificationError("unreachable")

    def _event(self, sample, reserve, envelope, started, error, decision, *, cancelled=False):
        data = self._accounting(envelope, reserve.reserved_usd)
        safe = envelope if isinstance(envelope, dict) else {}

        def string(key):
            value = safe.get(key)
            return (
                value
                if isinstance(value, str)
                and len(value) < 200
                and self.settings.redact(value) == value
                else None
            )

        return RequestEvent(
            event_id=reserve.request_id + "-settled",
            run_id=self.run_id,
            sample_id=sample.sample_id,
            fingerprint=reserve.fingerprint,
            request_id=reserve.request_id,
            kind="settled",
            created_at=utc_now(),
            attempt_index=reserve.attempt_index,
            reserved_usd=reserve.reserved_usd,
            outcome="cancelled"
            if cancelled
            else (
                "failed"
                if error
                else ("abstained" if self.is_abstention(decision) else "classified")
            ),
            error_code=error.code if error else None,
            http_status=error.status if error else 200,
            retryable=error.retryable if error else False,
            retry_after_seconds=error.retry_after if error else None,
            latency_seconds=time.monotonic() - started,
            **self.event_assessment(decision),
            model_returned=string("model"),
            routed_provider=string("provider"),
            generation_id=string("id"),
            **data,
        )
