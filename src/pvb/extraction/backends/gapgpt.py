"""GapGPT Chat Completions adapter sharing validation and durable accounting."""

import asyncio
import math
from decimal import Decimal

from pvb.extraction.backends.openrouter import ClassificationError, OpenRouterBackend
from pvb.extraction.gapgpt.metadata import read_billing
from pvb.extraction.openrouter.accounting import BudgetExceeded
from pvb.extraction.openrouter.settings import ConfigurationError


class GapGPTBackend(OpenRouterBackend):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.billing_before = {}
        self.billing_charges = {}
        if self.metadata.pricing_origin == "provider_budget":
            # Account usage differences must never overlap our own requests.
            self.semaphore = asyncio.Semaphore(1)

    def provider_routing(self) -> dict:
        return {}

    def payload(self, sample) -> dict:
        payload = super().payload(sample)
        # These are OpenRouter routing controls, not OpenAI-compatible fields.
        payload.pop("reasoning", None)
        payload.pop("temperature")
        payload["max_completion_tokens"] = payload.pop("max_tokens")
        payload["reasoning_effort"] = self.settings.reasoning_effort
        return payload

    def reservation(self) -> float:
        if self.metadata.pricing_origin != "provider_budget":
            return super().reservation()
        remaining = Decimal(str(self.settings.max_cost_usd)) - Decimal(
            str(self.journal.summary()["accounted_cost_usd"])
        )
        if remaining <= 0 or self.budget.stopped:
            raise BudgetExceeded("GapGPT run budget is exhausted.")
        # With unknown token rates, reserve every remaining authorized dollar.
        # Release only a positively measured provider charge; unknown/late
        # billing, interruption and timeout keep the entire reservation.
        amount = float(remaining)
        return math.nextafter(amount, 0.0) if Decimal(str(amount)) > remaining else amount

    async def prepare_request(self, request_id: str) -> None:
        if self.metadata.pricing_origin != "provider_budget":
            return
        try:
            cap, used = await read_billing(self.settings, self.client)
            if used >= cap:
                raise BudgetExceeded("GapGPT provider account budget is exhausted.")
            self.billing_before[request_id] = used
        except ConfigurationError:
            self.stop_code = "billing_unavailable"
            raise ClassificationError("billing_unavailable") from None

    async def complete_request(self, request_id: str) -> None:
        if self.metadata.pricing_origin != "provider_budget":
            return
        before = self.billing_before[request_id]
        # The live gateway meter updates a few seconds after the response.
        # Keep the full reservation while waiting for its positive charge.
        for delay in (0, 0.5, 1, 2, 4, 8):
            if delay:
                await asyncio.sleep(delay)
            try:
                _cap, used = await read_billing(self.settings, self.client)
                if used > before:
                    self.billing_charges[request_id] = float(
                        Decimal(str(used)) - Decimal(str(before))
                    )
                    break
            except ConfigurationError:
                # Billing may transiently fail independently of generation.
                # Retry reads only; never release an unmeasured reservation.
                continue

    def _accounting(self, envelope, reservation: float) -> dict:
        if self.metadata.pricing_origin == "provider_budget":
            usage = envelope.get("usage", {}) if isinstance(envelope, dict) else {}
            usage = usage if isinstance(usage, dict) else {}
            return {
                "input_tokens": usage.get("prompt_tokens")
                if type(usage.get("prompt_tokens")) is int and usage["prompt_tokens"] >= 0
                else None,
                "output_tokens": usage.get("completion_tokens")
                if type(usage.get("completion_tokens")) is int and usage["completion_tokens"] >= 0
                else None,
                "reported_cost_usd": None,
                "estimated_cost_usd": None,
                "accounted_cost_usd": reservation,
                "accounting_basis": "reservation",
            }
        # Bare usage.cost has no established currency in this gateway.
        if isinstance(envelope, dict) and isinstance(envelope.get("usage"), dict):
            usage = envelope["usage"]
            if usage.get("cost_currency") != "USD":
                envelope = {**envelope, "usage": {k: v for k, v in usage.items() if k != "cost"}}
        return super()._accounting(envelope, reservation)

    def _event(self, sample, reserve, envelope, started, error, decision, *, cancelled=False):
        event = super()._event(
            sample, reserve, envelope, started, error, decision, cancelled=cancelled
        )
        charge = self.billing_charges.get(reserve.request_id)
        if charge is not None:
            event = event.model_copy(
                update={
                    "reported_cost_usd": charge,
                    "accounted_cost_usd": charge,
                    "accounting_basis": "provider_meter",
                }
            )
        elif self.metadata.pricing_origin == "provider_budget":
            self.budget.stopped = True
        return event
