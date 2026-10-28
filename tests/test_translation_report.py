import json
import re

from pvb.translation.report import section


def test_translation_report_keeps_untrusted_text_as_json_data(tmp_path):
    directory = tmp_path / "runs/translation/completed-fixture"
    directory.mkdir(parents=True)
    pointer = tmp_path / "runs/translation/latest_translategemma.json"
    pointer.write_text(json.dumps({"directory": str(directory), "status": "completed"}))
    attack = "</script><img src=x onerror=alert(1)> __BARS__"
    rows = [
        {"sample_id": str(i), "prompt": attack, "comparison_cohort": "translation_portable"}
        for i in range(54)
    ]
    (directory / "samples.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    document = section(tmp_path)
    payload = re.search(
        r'<script id="trn-data" type="application/json">(.*?)</script>', document, re.DOTALL
    ).group(1)
    assert "<" not in payload and ">" not in payload
    assert json.loads(payload)["rows"][0]["prompt"] == attack
    assert "<img src=x" not in document
