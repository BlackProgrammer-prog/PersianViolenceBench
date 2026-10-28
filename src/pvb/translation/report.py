"""Offline Persian report of actual local translations; reusable in the main dashboard."""

import html
import json
from collections import Counter
from pathlib import Path

from pvb.extraction.io import write_text
from pvb.translation.settings import ROOT

TITLES = {
    "translation_portable": "قابل انتقال با ترجمه؛ پیش‌بینی مدل",
    "localization_required": "نیازمند بومی‌سازی با نظارت انسانی",
    "unassessed_provider_refusal": "فاقد ارزیابی فرهنگی؛ رد درخواست قبلی API",
}


def section(root=ROOT):
    pointer = root / "runs/translation/latest_translategemma.json"
    if not pointer.exists():
        return ""
    summary = json.loads(pointer.read_text())
    directory = Path(summary["directory"]).resolve()
    if not directory.is_relative_to((root / "runs/translation").resolve()):
        raise ValueError("Translation report input is outside translation runs.")
    rows = [json.loads(line) for line in (directory / "samples.jsonl").read_text().splitlines()]
    if (
        summary["status"] != "completed"
        or len(rows) != 54
        or len({r["sample_id"] for r in rows}) != 54
    ):
        raise ValueError("Translation report requires 54 unique completed samples.")
    data = json.dumps({"rows": rows, "summary": summary, "titles": TITLES}, ensure_ascii=False)
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    counts = Counter(r["comparison_cohort"] for r in rows)
    bars = "".join(
        '<div class="trn-bar-label">'
        + html.escape(title)
        + " · "
        + str(counts[key])
        + '</div><div class="trn-track"><span style="width:'
        + str(100 * counts[key] / 54)
        + '%"></span></div>'
        for key, title in TITLES.items()
    )
    template = (Path(__file__).with_name("translation_report.html")).read_text()
    # Insert untrusted JSON last; strings in the dataset cannot become template markers.
    return template.replace("__BARS__", bars).replace("__TRANSLATION_DATA__", data)


def main():
    content = section()
    if not content:
        raise SystemExit("No completed local translation run found.")
    target = ROOT / "reports/translation_report.html"
    write_text(
        target,
        '<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>ترجمهٔ ۵۴ نمونه | PersianViolenceBench</title><body>" + content + "</body></html>",
    )
    print(json.dumps({"output": str(target), "translated_samples": 54}))


if __name__ == "__main__":
    main()
