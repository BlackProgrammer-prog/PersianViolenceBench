"""Optional PAID smoke; excluded from pytest's default testpaths.

Requires both explicit test-file selection and PVB_ALLOW_PAID_SMOKE=YES.
Credentials and exact model still load from the root .env. Never run implicitly.
"""

import asyncio
import os
from pathlib import Path

import pytest

from pvb.extraction.openrouter.runner import execute
from pvb.extraction.openrouter.settings import load_settings


def test_authorized_live_structured_smoke():
    if os.environ.get("PVB_ALLOW_PAID_SMOKE") != "YES":
        pytest.skip("paid smoke is disabled; explicit PVB_ALLOW_PAID_SMOKE=YES required")
    report = asyncio.run(
        execute(Path("configs/openrouter.yaml"), load_settings(), mode="smoke", confirm_paid=True)
    )
    assert report["successfully_classified"] + report["abstentions"] == 1
    assert report["quality"]["passed"]
