"""Verify the exact gateway model; never substitute first-party OpenAI prices."""

from decimal import Decimal, InvalidOperation

import httpx

from pvb.extraction.openrouter.metadata import price
from pvb.extraction.openrouter.models import ModelMetadata
from pvb.extraction.openrouter.settings import ConfigurationError
from pvb.schemas.annotations import utc_now

OFFICIAL_MODEL_DOC = "https://developers.openai.com/api/docs/models/gpt-5.6-terra"


class PricingUnavailable(ConfigurationError):
    """A verified provider account cap can substitute for unavailable rates."""


async def read_billing(settings, client) -> tuple[float, float]:
    """OpenAI-compatible billing: hard limit in USD, usage in USD cents."""
    headers = {"Authorization": "Bearer " + settings.credential.get_secret_value()}
    try:
        subscription = await client.get(
            settings.base_url + "/dashboard/billing/subscription", headers=headers, timeout=30
        )
        usage = await client.get(
            settings.base_url + "/dashboard/billing/usage", headers=headers, timeout=30
        )
        if subscription.status_code != 200 or usage.status_code != 200:
            raise ValueError("billing unavailable")
        cap = price(subscription.json()["hard_limit_usd"])
        used = price(Decimal(str(usage.json()["total_usage"])) / 100)
        if not 0 < cap <= settings.max_cost_usd:
            raise ValueError("provider cap exceeds authorized budget")
        return cap, used
    except (httpx.HTTPError, KeyError, TypeError, ValueError, InvalidOperation):
        raise ConfigurationError(
            "GapGPT billing is unavailable or its account cap exceeds PVB_API_MAX_COST_USD. "
            "No new generation permitted."
        ) from None


def parse_metadata(catalog, settings, *, provider_budget_verified=False) -> ModelMetadata:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        raise ConfigurationError("Invalid GapGPT model catalog shape. No generation was attempted.")
    rows = [r for r in catalog["data"] if isinstance(r, dict) and r.get("id") == settings.model]
    if len(rows) != 1:
        raise ConfigurationError("Selected exact model is unavailable in the GapGPT catalog.")
    row = rows[0]
    parameters = row.get("supported_parameters")
    if parameters is not None and (
        not isinstance(parameters, list) or not all(isinstance(p, str) for p in parameters)
    ):
        raise ConfigurationError("Invalid GapGPT supported-parameter metadata.")
    # The named model's native contract is documented by OpenAI. The gateway's
    # actual adherence is checked on every response, not claimed from its listing.
    if (
        parameters is not None and not {"structured_outputs", "response_format"} <= set(parameters)
    ) or (parameters is None and settings.model != "gpt-5.6-terra"):
        raise ConfigurationError(
            "GapGPT structured-output capability is not established for this model."
        )
    origin = "provider_metadata"
    pricing = row.get("pricing")
    # Only an explicitly denominated USD-per-token contract is interpretable.
    if (
        isinstance(pricing, dict)
        and pricing.get("currency") == "USD"
        and pricing.get("unit") == "token"
    ):
        try:
            inp, out, request = (price(pricing[k]) for k in ("prompt", "completion", "request"))
            if any(
                price(v) > 0
                for k, v in pricing.items()
                if k not in {"prompt", "completion", "request", "currency", "unit"}
            ):
                raise ValueError("unsupported surcharge")
        except (KeyError, TypeError, ValueError):
            raise ConfigurationError(
                "Invalid or unsupported GapGPT pricing. No generation was attempted."
            ) from None
    else:
        if (
            settings.input_usd_per_million is None
            or settings.output_usd_per_million is None
            or settings.request_usd is None
            or not settings.pricing_source
        ):
            if provider_budget_verified:
                inp = out = request = None
                origin = "provider_budget"
            else:
                raise PricingUnavailable(
                    "GapGPT catalog does not provide supported USD pricing. Set verified gateway "
                    "rates GAPGPT_INPUT_USD_PER_MILLION, GAPGPT_OUTPUT_USD_PER_MILLION, "
                    "GAPGPT_REQUEST_USD and GAPGPT_PRICING_SOURCE in .env, or use a verified "
                    "provider account cap within PVB_API_MAX_COST_USD. OpenAI list prices "
                    "are not assumed to be GapGPT billing rates. No generation was attempted."
                ) from None
        else:
            try:
                inp = price(Decimal(str(settings.input_usd_per_million)) / 1_000_000)
                out = price(Decimal(str(settings.output_usd_per_million)) / 1_000_000)
            except ValueError:
                raise ConfigurationError("GapGPT pricing cannot be represented safely.") from None
            request = settings.request_usd
            origin = "operator_configured"
    # Local cap is deliberately below the native context window; a smaller
    # gateway-declared limit takes precedence when present and valid.
    context = settings.context_limit_tokens
    declared = row.get("context_length")
    if declared is not None:
        if not isinstance(declared, int) or isinstance(declared, bool) or declared <= 0:
            raise ConfigurationError("Invalid GapGPT context length.")
        context = min(context, declared)
    if settings.max_output_tokens >= context:
        raise ConfigurationError("GapGPT output limit leaves no room for the input context.")
    return ModelMetadata(
        model_id=settings.model,
        canonical_slug="openai/gpt-5.6-terra"
        if settings.model == "gpt-5.6-terra"
        else settings.model,
        retrieved_at=utc_now(),
        source=settings.base_url + "/models",
        context_length=context,
        supported_parameters=sorted(
            set(parameters or ["structured_outputs", "response_format"])
            & {
                "structured_outputs",
                "response_format",
                "max_completion_tokens",
                "reasoning_effort",
            }
        ),
        input_usd_per_token=inp,
        output_usd_per_token=out,
        request_usd=request,
        eligible_provider_tags=[],
        endpoint_details=[
            {
                "capability_reference": OFFICIAL_MODEL_DOC
                if settings.model == "gpt-5.6-terra"
                else None,
                "gateway_generation_verified": False,
                "pricing_source": settings.pricing_source
                if origin == "operator_configured"
                else settings.base_url + "/models",
                "routing_price_caps_supported": False,
                "provider_budget_ceiling_usd": settings.max_cost_usd
                if origin == "provider_budget"
                else None,
                "billing_source": settings.base_url + "/dashboard/billing/usage"
                if origin == "provider_budget"
                else None,
                "serial_requests_required": origin == "provider_budget",
            }
        ],
        pricing_origin=origin,
    )


async def preflight(settings, client: httpx.AsyncClient) -> ModelMetadata:
    settings.require_ready()
    try:
        response = await client.get(
            settings.base_url + "/models",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + settings.credential.get_secret_value(),
            },
            timeout=settings.timeout_seconds,
        )
        if response.status_code != 200:
            raise ConfigurationError(
                f"GapGPT model catalog returned HTTP {response.status_code}. "
                "Check GAPGPT_API_KEY, account access and service availability. No generation was attempted."
            )
        catalog = response.json()
        try:
            return parse_metadata(catalog, settings)
        except PricingUnavailable:
            cap, used = await read_billing(settings, client)
            if used >= cap:
                raise ConfigurationError(
                    "GapGPT account budget is exhausted. No generation was attempted."
                ) from None
            return parse_metadata(catalog, settings, provider_budget_verified=True)
    except ConfigurationError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise ConfigurationError(
            "GapGPT metadata is unavailable or invalid. No generation was attempted."
        ) from None
