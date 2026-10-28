"""Official model catalog and per-model endpoint metadata; never inference."""

import math
from decimal import Decimal, InvalidOperation

import httpx

from pvb.extraction.openrouter.models import ModelMetadata
from pvb.extraction.openrouter.settings import ConfigurationError, OpenRouterSettings
from pvb.schemas.annotations import utc_now

REQUIRED_PARAMETERS = {"structured_outputs", "response_format", "temperature", "max_tokens"}


def price(value) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("missing price")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid price") from None
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("invalid price")
    converted = float(parsed)
    if not math.isfinite(converted) or (parsed > 0 and converted == 0):
        raise ValueError("price cannot be represented safely")
    return converted


def parse_metadata(catalog: dict, endpoints: dict, model: str, base_url: str) -> ModelMetadata:
    if (
        not isinstance(catalog, dict)
        or not isinstance(catalog.get("data"), list)
        or not all(isinstance(row, dict) for row in catalog["data"])
    ):
        raise ConfigurationError("Invalid model catalog shape.")
    if not isinstance(endpoints, dict) or not isinstance(endpoints.get("data"), dict):
        raise ConfigurationError("Invalid endpoint metadata shape.")
    if not isinstance(endpoints["data"].get("endpoints"), list) or not all(
        isinstance(row, dict) for row in endpoints["data"]["endpoints"]
    ):
        raise ConfigurationError("Invalid endpoint list shape.")
    rows = [row for row in catalog["data"] if row.get("id") == model]
    if len(rows) != 1:
        raise ConfigurationError("Selected exact model is unavailable in the OpenRouter catalog.")
    row = rows[0]
    data = endpoints["data"]
    if not data.get("id") or data.get("id") not in (model, row.get("canonical_slug")):
        raise ConfigurationError("Endpoint metadata identifies a different model.")
    eligible, details = [], []
    for endpoint in data.get("endpoints", []):
        parameters = endpoint.get("supported_parameters", [])
        reason = None
        try:
            prices = endpoint["pricing"]
            inp, out = (price(prices[k]) for k in ("prompt", "completion"))
            # Free variants can omit the per-request price. Keep missing paid
            # pricing fail-closed and still validate any explicit request price.
            free_variant = model.endswith(":free") and inp == out == 0
            request = price(prices.get("request", "0") if free_variant else prices["request"])
            if "input_cache_read" in prices:
                inp = max(inp, price(prices["input_cache_read"]))
            # No image, tool, cache-write or other unaccounted surcharge accepted.
            if any(
                price(v) > 0
                for k, v in prices.items()
                if k not in ("prompt", "completion", "request", "input_cache_read")
            ):
                reason = "unsupported_additional_pricing"
            context = endpoint["context_length"]
            if not isinstance(context, int) or isinstance(context, bool) or context <= 0:
                reason = "unknown_context_length"
            # Health codes change independently of capabilities (free providers
            # have published both -2 and -5). For verified zero-cost variants,
            # let the generation API determine availability rather than guessing
            # the meaning of undocumented health codes. Paid pricing stays gated.
            status = endpoint.get("status")
            zero_cost_attempt = free_variant and inp == out == request == 0
            if (
                not isinstance(status, int)
                or isinstance(status, bool)
                or (status != 0 and not zero_cost_attempt)
            ):
                reason = "endpoint_status_not_verified_available"
            if not REQUIRED_PARAMETERS <= set(parameters):
                reason = "required_parameters_not_verified"
            if not endpoint.get("tag"):
                reason = "missing_provider_tag"
            if not reason:
                eligible.append((endpoint, inp, out, request))
        except (KeyError, TypeError, ValueError):
            reason = "unknown_or_invalid_pricing"
        details.append(
            {
                "provider_tag": endpoint.get("tag"),
                "provider_name": endpoint.get("provider_name"),
                "status": endpoint.get("status"),
                "supported_parameters": parameters,
                "eligible": reason is None,
                "exclusion_reason": reason,
                "context_length": endpoint.get("context_length"),
                "max_completion_tokens": endpoint.get("max_completion_tokens"),
                "max_prompt_tokens": endpoint.get("max_prompt_tokens"),
            }
        )
    if not eligible:
        reasons = sorted({d["exclusion_reason"] for d in details if d["exclusion_reason"]})
        raise ConfigurationError(
            "No available endpoint has verified strict-output parameters and supported pricing. "
            "No paid call permitted. Exclusions: " + (", ".join(reasons) or "no_endpoints")
        )
    return ModelMetadata(
        model_id=model,
        canonical_slug=row.get("canonical_slug"),
        retrieved_at=utc_now(),
        source=base_url + "/models/" + model + "/endpoints",
        context_length=min(
            min(e["context_length"], e.get("max_prompt_tokens") or e["context_length"])
            for e, *_ in eligible
        ),
        supported_parameters=sorted(set(row.get("supported_parameters", []))),
        input_usd_per_token=max(p for _, p, _, _ in eligible),
        output_usd_per_token=max(p for _, _, p, _ in eligible),
        request_usd=max(p for _, _, _, p in eligible),
        eligible_provider_tags=sorted({e["tag"] for e, *_ in eligible}),
        endpoint_details=details,
    )


def metadata_http_error(response: httpx.Response, endpoint: str) -> ConfigurationError:
    """Allowlisted diagnostics only: never echo upstream bodies, URLs or headers."""
    hints = {
        401: "Authentication rejected. Check OPENROUTER_API_KEY in the root .env file.",
        402: "The account cannot access this endpoint. Check account access with OpenRouter.",
        403: "Access is forbidden by OpenRouter or an intervening network/security policy. Check service access and account permissions. This response alone does not establish whether the API key is valid.",
        404: "Metadata endpoint or exact model identifier was not found. Check OPENROUTER_MODEL.",
        429: "Metadata requests are rate limited. Retry the preflight later.",
    }
    hint = hints.get(
        response.status_code,
        "The metadata service is unavailable or rejected the request. Retry preflight after checking service access.",
    )
    return ConfigurationError(
        f"OpenRouter {endpoint} metadata request returned HTTP {response.status_code}. "
        + hint
        + " No generation was attempted."
    )


async def preflight(settings: OpenRouterSettings, client: httpx.AsyncClient) -> ModelMetadata:
    if not settings.model or any(
        "MODEL" in issue or "BASE_URL" in issue for issue in settings.issues()
    ):
        raise ConfigurationError(
            "Configure an exact OPENROUTER_MODEL and the official OPENROUTER_BASE_URL first."
        )
    try:
        headers = {"Accept": "application/json"}
        if settings.credential_configured:
            headers["Authorization"] = "Bearer " + settings.credential.get_secret_value()
        catalog = await client.get(
            settings.base_url + "/models", headers=headers, timeout=settings.timeout_seconds
        )
        if catalog.status_code != 200:
            raise metadata_http_error(catalog, "catalog (/models)")
        endpoints = await client.get(
            settings.base_url + "/models/" + settings.model + "/endpoints",
            headers=headers,
            timeout=settings.timeout_seconds,
        )
        if endpoints.status_code != 200:
            raise metadata_http_error(endpoints, "selected-model endpoints")
        metadata = parse_metadata(
            catalog.json(), endpoints.json(), settings.model, settings.base_url
        )
        for endpoint in metadata.endpoint_details:
            if (
                endpoint["eligible"]
                and endpoint["max_completion_tokens"] is not None
                and endpoint["max_completion_tokens"] < settings.max_output_tokens
            ):
                raise ConfigurationError(
                    "Configured output limit exceeds an eligible endpoint capability."
                )
        return metadata
    except ConfigurationError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise ConfigurationError(
            "OpenRouter metadata is unavailable, unsupported or invalid. No generation was attempted."
        ) from None
