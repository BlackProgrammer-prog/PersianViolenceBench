import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from pvb.extraction.backends.gapgpt import GapGPTBackend
from pvb.extraction.gapgpt.metadata import parse_metadata, preflight
from pvb.extraction.gapgpt.settings import GapGPTSettings, load_settings
from pvb.extraction.openrouter.accounting import BudgetExceeded, Journal
from pvb.extraction.openrouter.runner import workload
from pvb.extraction.openrouter.settings import ConfigurationError
from pvb.extraction.pipeline import main
from pvb.schemas.annotations import Decision


def catalog(**changes):
    return {"data": [{"id": "gpt-5.6-terra", **changes}]}


def configured(**changes):
    return GapGPTSettings(credential=SecretStr("gap-fixture-secret"), **changes)


def operator_pricing(**changes):
    return configured(
        input_usd_per_million=2,
        output_usd_per_million=12,
        request_usd=0,
        pricing_source="https://api.gapgpt.app/fixture-pricing",
        **changes,
    )


def test_gapgpt_credentials_do_not_fall_back_to_openrouter(tmp_path):
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=other-provider-secret\n")
    settings = load_settings(tmp_path, environ={})
    assert settings.provider == "gapgpt" and settings.model == "gpt-5.6-terra"
    assert not settings.credential_configured
    with pytest.raises(ConfigurationError, match="GAPGPT_API_KEY"):
        settings.require_ready()


def test_gapgpt_settings_separate_key_and_specific_overrides(tmp_path):
    secret = "gap-fixture-secret"
    (tmp_path / ".env").write_text(
        "GAPGPT_API_KEY=" + secret + "\nGAPGPT_MODEL=gpt-5.6-terra\n"
        "OPENROUTER_API_KEY=other-provider-secret\nPVB_API_CONCURRENCY=5\n"
        "GAPGPT_CONCURRENCY=2\nGAPGPT_REASONING_EFFORT=high\n"
        "GAPGPT_INPUT_USD_PER_MILLION=\nPVB_CLASSIFICATION_REASONING_ENABLED=false\n"
    )
    settings = load_settings(tmp_path, environ={})
    settings.require_ready()
    assert settings.credential.get_secret_value() == secret
    assert settings.concurrency == 2 and settings.reasoning_effort == "high"
    assert settings.reasoning_enabled is None and settings.input_usd_per_million is None
    assert secret not in repr(settings) + json.dumps(settings.public())
    assert settings.redact(secret) == "[REDACTED]"


@pytest.mark.parametrize("url", ["https://attacker.invalid/v1", "http://api.gapgpt.app/v1"])
def test_gapgpt_refuses_credential_redirection(url):
    with pytest.raises(ConfigurationError, match="GAPGPT_BASE_URL"):
        configured(base_url=url).require_ready()


def test_gapgpt_does_not_invent_gateway_prices():
    with pytest.raises(ConfigurationError, match="OpenAI list prices"):
        parse_metadata(catalog(), configured())


def test_operator_rates_are_labeled_and_do_not_claim_verification():
    metadata = parse_metadata(catalog(), operator_pricing())
    assert metadata.input_usd_per_token == 0.000002
    assert metadata.output_usd_per_token == 0.000012
    assert metadata.pricing_origin == "operator_configured"
    assert not metadata.structured_generation_tested
    assert not workload([], lambda s: {}, metadata, 600)["pricing_verified"]


def test_explicit_provider_pricing_and_context_limit():
    metadata = parse_metadata(
        catalog(
            context_length=16000,
            pricing={
                "currency": "USD",
                "unit": "token",
                "prompt": "0.000003",
                "completion": "0.000014",
                "request": "0",
            },
        ),
        configured(),
    )
    assert metadata.context_length == 16000
    assert metadata.input_usd_per_token == 0.000003
    assert metadata.pricing_origin == "provider_metadata"


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": None},
        {"completion": "NaN"},
        {"request": "-1"},
        {"unaccounted_fee": "1"},
    ],
)
def test_invalid_explicit_pricing_cannot_be_overridden(changes):
    pricing = {
        "currency": "USD",
        "unit": "token",
        "prompt": "0.1",
        "completion": "0.2",
        "request": "0",
        **changes,
    }
    with pytest.raises(ConfigurationError, match="pricing"):
        parse_metadata(catalog(pricing=pricing), operator_pricing())


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "different-model"},
        {"supported_parameters": [None]},
        {"context_length": True},
    ],
)
def test_invalid_or_wrong_model_metadata_rejected(changes):
    with pytest.raises(ConfigurationError):
        parse_metadata(catalog(**changes), operator_pricing())


def test_other_model_requires_capability_metadata():
    with pytest.raises(ConfigurationError, match="capability"):
        parse_metadata(catalog(id="fixture-model"), operator_pricing(model="fixture-model"))


def test_gapgpt_preflight_only_gets_exact_catalog():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and request.url == "https://api.gapgpt.app/v1/models"
        assert request.headers["Authorization"] == "Bearer gap-fixture-secret"
        return httpx.Response(200, json=catalog())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await preflight(operator_pricing(), client)

    assert asyncio.run(run()).model_id == "gpt-5.6-terra"
    assert len(requests) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_gapgpt_preflight_errors_never_expose_response(status):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(status, text="gap-fixture-secret")
            )
        ) as client:
            return await preflight(configured(), client)

    with pytest.raises(ConfigurationError) as exc:
        asyncio.run(run())
    assert str(status) in str(exc.value) and "gap-fixture-secret" not in str(exc.value)


def test_gapgpt_config_check_dispatch_without_network(monkeypatch, capsys):
    monkeypatch.setattr("pvb.extraction.gapgpt.settings.load_settings", lambda: GapGPTSettings())
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda *a, **k: pytest.fail("network forbidden"))
    assert main(["--backend=gapgpt", "--mode", "config-check"]) == 1
    assert "GAPGPT_API_KEY" in capsys.readouterr().out


def test_preflight_can_verify_account_cap_without_inventing_prices():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=catalog())
        if request.url.path.endswith("/subscription"):
            return httpx.Response(200, json={"hard_limit_usd": 2})
        return httpx.Response(200, json={"total_usage": 0})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await preflight(configured(), client)

    metadata = asyncio.run(run())
    assert len(requests) == 3
    assert metadata.pricing_origin == "provider_budget"
    assert (
        metadata.input_usd_per_token
        is metadata.output_usd_per_token
        is metadata.request_usd
        is None
    )
    estimate = workload([], lambda s: {}, metadata, 600)
    assert estimate["estimated_cost_usd"] is None and not estimate["pricing_verified"]


@pytest.mark.parametrize("cap, used", [(3, 0), (2, 200), (None, 0)])
def test_provider_cap_must_fit_budget_and_have_remaining_credit(cap, used):
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=catalog())
        if request.url.path.endswith("/subscription"):
            return httpx.Response(200, json={"hard_limit_usd": cap})
        return httpx.Response(200, json={"total_usage": used})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await preflight(configured(), client)

    with pytest.raises(ConfigurationError):
        asyncio.run(run())


@pytest.mark.parametrize("billing_mode", ["measured", "late", "delayed", "unavailable"])
def test_metered_budget_releases_only_measured_charges(
    tmp_path, synthetic_sample, decision_data, billing_mode, monkeypatch
):
    original_sleep = asyncio.sleep

    async def fast_sleep(delay):
        await original_sleep(0)

    monkeypatch.setattr("pvb.extraction.backends.gapgpt.asyncio.sleep", fast_sleep)
    settings = configured()
    metadata = parse_metadata(catalog(), settings, provider_budget_verified=True)
    state = {"cents": 0, "posts": 0, "usage_reads": 0}

    def handler(request):
        if request.method == "POST":
            state["posts"] += 1
            state["usage_reads"] = 0
            if billing_mode in ("measured", "late"):
                state["cents"] += 1
            return httpx.Response(
                200,
                json={
                    "id": "test-generation",
                    "model": metadata.canonical_slug,
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": Decision(**decision_data).model_dump_json()},
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 100, "cost": 9000},
                },
            )
        if request.url.path.endswith("/subscription"):
            return httpx.Response(200, json={"hard_limit_usd": 2})
        if billing_mode == "unavailable" and state["posts"]:
            return httpx.Response(503)
        state["usage_reads"] += 1
        amount = state["cents"]
        if billing_mode == "late" and state["posts"] and state["usage_reads"] == 1:
            amount -= 1
        return httpx.Response(200, json={"total_usage": amount})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            backend = GapGPTBackend(
                settings=settings,
                metadata=metadata,
                client=client,
                prompt="Classify the request.",
                taxonomy={"version": "1.0.0"},
                prompt_version="fixture",
                run_id="pvb-gap-fixture",
                journal=Journal(tmp_path / "journal"),
                cache_dir=tmp_path / "cache",
                requests_per_minute=60000,
                paid_authorized=True,
            )
            assert await backend.classify(synthetic_sample("First synthetic sample."))
            if billing_mode in ("measured", "late"):
                assert await backend.classify(synthetic_sample("Second synthetic sample."))
                assert state["posts"] == 2
                assert backend.journal.summary()["reported_cost_usd"] == 0.02
                assert backend.journal.summary()["accounted_cost_usd"] == 0.02
                assert all(
                    e.accounting_basis == "provider_meter"
                    for e in backend.journal.events
                    if e.kind == "settled"
                )
            else:
                with pytest.raises(BudgetExceeded):
                    await backend.classify(synthetic_sample("Second synthetic sample."))
                assert state["posts"] == 1
                assert backend.journal.summary()["accounted_cost_usd"] == 2
                assert backend.journal.summary()["requests_missing_reported_cost"] == 1

    asyncio.run(run())
