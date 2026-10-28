import json
import re
from html.parser import HTMLParser

import pytest

from pvb.extraction.visual_report import build_report
from pvb.ingestion.adapters.strongreject import adapt


def fixture_files(tmp_path):
    injection = (
        "</script><script>globalThis.pwned=true</script> __TOTAL__ <img src=x onerror=alert(1)>"
    )
    sample = adapt({"category": "Violence", "source": "custom", "forbidden_prompt": injection})
    normalized = tmp_path / "data/normalized"
    normalized.mkdir(parents=True)
    (normalized / "benchmark_samples.jsonl").write_text(sample.model_dump_json() + "\n")
    (normalized / "benchmark_sources.jsonl").write_text("")
    run = tmp_path / "run"
    run.mkdir()
    summary = {
        "combined_category_counts": {"other_violence": 1},
        "provider_account_usage_after_usd": 0.1,
        "provider_account_cap_usd": 2,
        "remaining_provider_credit_usd": 1.9,
        "provider_account_increase_usd": 0.1,
        "new_run_metered_cost_usd": 0.1,
    }
    (run / "all54_summary.json").write_text(json.dumps(summary))
    record = {
        **sample.model_dump(mode="json"),
        "category": "other_violence",
        "processing_status": "classified",
        "annotation": {
            "label": "out_of_scope",
            "rationale": injection,
            "review_status": "pending",
            "subcategories": [],
        },
    }
    (run / "all54_categorized_samples.jsonl").write_text(json.dumps(record) + "\n")
    return run, injection


def test_report_embeds_untrusted_text_as_data_without_template_interpretation(tmp_path):
    run, injection = fixture_files(tmp_path)
    output = tmp_path / "report.html"
    result = build_report(tmp_path, run, output)
    document = output.read_text()
    encoded = re.search(
        r'<script id="report-data" type="application/json">(.*?)</script>', document, re.DOTALL
    ).group(1)
    payload = json.loads(encoded)
    assert payload["records"][0]["original_prompt"] == injection
    assert payload["records"][0]["annotation"]["rationale"] == injection
    assert "<" not in encoded and ">" not in encoded
    assert payload["corpus"]["total"] == result["reviewed_samples"] == 1

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts = 0
            self.images = 0

        def handle_starttag(self, tag, attrs):
            self.scripts += tag == "script"
            self.images += tag == "img"

    parser = Parser()
    parser.feed(document)
    assert parser.scripts == 2 and parser.images == 0


def test_report_refuses_conflicting_summary_counts(tmp_path):
    run, _ = fixture_files(tmp_path)
    path = run / "all54_summary.json"
    summary = json.loads(path.read_text())
    summary["combined_category_counts"]["other_violence"] = 2
    path.write_text(json.dumps(summary))
    output = tmp_path / "report.html"
    with pytest.raises(ValueError, match="reconcile"):
        build_report(tmp_path, run, output)
    assert not output.exists()
