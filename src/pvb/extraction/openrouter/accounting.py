"""Durable reservation accounting: uncertain charges remain reserved on resume."""

import asyncio
from decimal import Decimal
from pathlib import Path

from pvb.extraction.io import write_json
from pvb.extraction.openrouter.models import RequestEvent


class BudgetExceeded(RuntimeError):
    pass


class Journal:
    def __init__(self, directory: Path, repository=None):
        self.directory, self.repository = directory, repository
        self.events: list[RequestEvent] = []
        if (directory / "events").exists():
            self.events = [
                RequestEvent.model_validate_json(p.read_text())
                for p in sorted((directory / "events").glob("*.json"))
            ]
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("duplicate journal event IDs")
        if repository:
            repository.add_request_events(
                sorted(self.events, key=lambda e: (e.kind == "settled", e.created_at, e.event_id))
            )

    def append(self, event: RequestEvent) -> None:
        path = self.directory / "events" / (event.event_id + ".json")
        if path.exists():
            if RequestEvent.model_validate_json(path.read_text()) != event:
                raise ValueError("request event history conflict")
            return
        # Filesystem journal first: survives a DB write failure before HTTP dispatch.
        write_json(path, event.model_dump(mode="json"))
        self.events.append(event)
        if self.repository:
            self.repository.add_request_events([event])

    def summary(self) -> dict:
        reserved = {e.request_id: e for e in self.events if e.kind == "reserved"}
        settled = {e.request_id: e for e in self.events if e.kind == "settled"}
        if len(reserved) != sum(e.kind == "reserved" for e in self.events):
            raise ValueError("multiple reservations for a request")
        if len(settled) != sum(e.kind == "settled" for e in self.events):
            raise ValueError("multiple settlements for a request")
        if settled.keys() - reserved.keys():
            raise ValueError("settlement without reservation")
        pending = [e for key, e in reserved.items() if key not in settled]
        finished = sorted(settled.values(), key=lambda e: (e.created_at, e.event_id))
        return {
            "request_attempts": len(reserved),
            "successful_requests": sum(e.outcome in ("classified", "abstained") for e in finished),
            "failed_requests": sum(e.outcome == "failed" for e in finished),
            "cancelled_requests": sum(e.outcome == "cancelled" for e in finished),
            "unresolved_requests": len(pending),
            "cached_requests": sum(e.kind == "cache_hit" for e in self.events),
            "retry_count": sum(e.attempt_index > 0 for e in reserved.values()),
            "input_tokens_reported": sum(e.input_tokens or 0 for e in finished),
            "output_tokens_reported": sum(e.output_tokens or 0 for e in finished),
            "requests_missing_token_usage": sum(
                e.input_tokens is None or e.output_tokens is None for e in finished
            )
            + len(pending),
            "reported_cost_usd": sum(e.reported_cost_usd or 0 for e in finished),
            "requests_missing_reported_cost": sum(e.reported_cost_usd is None for e in finished)
            + len(pending),
            "estimated_cost_usd": sum(e.estimated_cost_usd or 0 for e in finished),
            "accounted_cost_usd": float(
                sum((Decimal(str(e.accounted_cost_usd)) for e in finished), Decimal(0))
                + sum((Decimal(str(e.reserved_usd)) for e in pending), Decimal(0))
            ),
            "outstanding_reservations_usd": sum(e.reserved_usd for e in pending),
            "latencies_seconds": [
                e.latency_seconds for e in finished if e.latency_seconds is not None
            ],
            "actual_cost_complete": not pending
            and all(e.reported_cost_usd is not None for e in finished),
        }


class Budget:
    def __init__(self, limit: float, journal: Journal):
        self.limit, self.journal = Decimal(str(limit)), journal
        self.lock = asyncio.Lock()
        self.stopped = False

    async def reserve(self, event: RequestEvent) -> None:
        async with self.lock:
            spent = Decimal(str(self.journal.summary()["accounted_cost_usd"]))
            if self.stopped or spent + Decimal(str(event.reserved_usd)) > self.limit:
                self.stopped = True
                raise BudgetExceeded(
                    "Budget cannot cover another request reservation; new requests stopped."
                )
            self.journal.append(event)

    async def settle(self, event: RequestEvent) -> None:
        async with self.lock:
            self.journal.append(event)
            if Decimal(str(self.journal.summary()["accounted_cost_usd"])) >= self.limit:
                self.stopped = True
