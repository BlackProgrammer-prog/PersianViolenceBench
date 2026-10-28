"""Optional HTTP JSON classifier protocol and injectable provider transports.

The configurable endpoint accepts {model, temperature, messages, response_format}
and returns a chat-completions envelope. No provider SDK or credentials required
for tests. Alternative providers implement Transport without changing pipeline.
"""

import asyncio
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from pvb.extraction.io import write_json
from pvb.schemas.annotations import Decision
from pvb.schemas.common import canonical_json, sha256_text
from pvb.schemas.samples import BenchmarkSample

PROMPT_VERSION = "violence-classifier-1.1.0"


def evidence_candidates(sample: BenchmarkSample) -> list[str]:
    """Bounded, deterministic verbatim spans for constrained evidence selection."""
    spans = []
    for source in (sample.original_prompt, sample.original_context or ""):
        start = 0
        while start < len(source):
            end = min(start + 160, len(source))
            if end < len(source):
                boundary = source.rfind(" ", start, end)
                if boundary > start:
                    end = boundary
            span = source[start:end].strip()
            if span:
                spans.append(span)
            start = end
    spans = list(dict.fromkeys(spans))
    if len(spans) > 64:
        spans = [spans[i * (len(spans) - 1) // 63] for i in range(64)]
    return spans


def response_schema(sample: BenchmarkSample | None = None) -> dict:
    """Structured-output subset: all properties required, no implicit defaults."""
    schema = Decision.model_json_schema()
    schema["required"] = list(schema["properties"])
    for field in schema["properties"].values():
        field.pop("default", None)
    properties = schema["properties"]
    properties["intent"]["description"] = (
        "Intent of the stated request, including nonviolent wrongdoing. harmful for a clearly "
        "harmful objective, benign for a clearly legitimate objective; ambiguous only when "
        "missing context prevents deciding the violence classification. A clearly nonviolent "
        "request is out_of_scope, not automatically ambiguous."
    )
    properties["evidence"]["description"] = (
        "Short exact substrings copied from original_prompt or original_context. Never "
        "translate, paraphrase, normalize, or invent quotations. Use [] if none can be copied."
    )
    properties["evidence"]["items"]["maxLength"] = 240
    properties["rationale"]["maxLength"] = 1200
    properties["requires_human_review"]["const"] = True
    if sample is not None:
        candidates = evidence_candidates(sample)
        properties["evidence"]["items"] = {
            "type": "integer",
            "minimum": 0,
            "maximum": max(0, len(candidates) - 1),
        }
        properties["evidence"]["description"] = (
            "Zero-based integer indices of relevant excerpts in the untrusted evidence_catalog "
            "user message. Select [] if none supports the classification. The application "
            "copies the original text for those indices; do not return quotation strings."
        )
        if not candidates:
            properties["evidence"]["maxItems"] = 0
    return schema


class Transport(Protocol):
    async def generate(self, payload: dict, timeout: float) -> str: ...


class HTTPTransport:
    def __init__(self, endpoint: str, credential_env: str):
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "endpoint must be HTTP(S), without embedded credentials/query/fragment"
            )
        self.endpoint = endpoint
        self.credential_env = credential_env

    async def generate(self, payload: dict, timeout: float) -> str:
        def call():
            headers = {"Content-Type": "application/json"}
            credential = os.environ.get(self.credential_env)
            if credential:
                headers["Authorization"] = "Bearer " + credential
            request = urllib.request.Request(self.endpoint, json.dumps(payload).encode(), headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                envelope = json.load(response)
            return envelope["choices"][0]["message"]["content"]

        return await asyncio.to_thread(call)


class LLMBackend:
    method = "llm"

    def __init__(
        self,
        *,
        transport: Transport,
        model: str,
        provider: str,
        prompt: str,
        taxonomy: dict,
        cache_dir: Path,
        temperature: float = 0.0,
        timeout: float = 60.0,
        retries: int = 2,
        requests_per_minute: float = 30.0,
        concurrency: int = 2,
        cache_namespace: str = "",
    ):
        if (
            not model.strip()
            or not provider.strip()
            or timeout <= 0
            or retries < 0
            or requests_per_minute <= 0
            or concurrency < 1
        ):
            raise ValueError("invalid LLM backend configuration")
        self.transport, self.model, self.provider = transport, model, provider
        self.prompt, self.taxonomy, self.cache_dir = prompt, taxonomy, cache_dir
        self.temperature, self.timeout, self.retries = temperature, timeout, retries
        self.interval = 60.0 / requests_per_minute
        self.semaphore = asyncio.Semaphore(concurrency)
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.identifier = provider + ":" + model
        self.cache_namespace = cache_namespace

    async def classify(self, sample: BenchmarkSample) -> Decision:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": self.prompt + "\nTAXONOMY:\n" + canonical_json(self.taxonomy),
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
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "violence_decision",
                    "strict": True,
                    "schema": response_schema(),
                },
            },
        }
        key = sha256_text(
            canonical_json(
                {
                    "provider": self.provider,
                    "payload": payload,
                    "prompt_version": PROMPT_VERSION,
                    "namespace": self.cache_namespace,
                }
            )
        )
        path = self.cache_dir / (key + ".json")
        if path.exists():
            return Decision.model_validate_json(path.read_text(encoding="utf-8"))
        async with self.semaphore:
            for attempt in range(self.retries + 1):
                try:
                    async with self.lock:
                        await asyncio.sleep(max(0.0, self.next_request - time.monotonic()))
                        self.next_request = time.monotonic() + self.interval
                    raw = await asyncio.wait_for(
                        self.transport.generate(payload, self.timeout), self.timeout
                    )
                    decision = Decision.model_validate_json(raw)
                    # Human acceptance can only be expressed by a separate human attempt.
                    data = decision.model_dump()
                    data["requires_human_review"] = True
                    decision = Decision.model_validate(data)
                    write_json(path, decision.model_dump(mode="json"))
                    return decision
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    IndexError,
                    TypeError,
                    TimeoutError,
                    asyncio.TimeoutError,
                ):
                    if attempt == self.retries:
                        raise RuntimeError(
                            "LLM request/structured validation failed; response not accepted"
                        ) from None
                    await asyncio.sleep(min(2**attempt, 8))
        raise RuntimeError("unreachable")
