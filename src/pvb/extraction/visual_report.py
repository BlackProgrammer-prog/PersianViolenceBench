"""Build a standalone, offline Persian report from recorded benchmark artifacts."""

import argparse
import html
import json
import math
from collections import Counter
from pathlib import Path

from pvb.extraction.io import write_text
from pvb.ingestion.export import load_jsonl
from pvb.schemas.samples import BenchmarkSample
from pvb.schemas.sources import SourceRecord

COLORS = ["#087e8b", "#e6a23c", "#5267c6", "#31445d", "#9c6db0"]
CATEGORY_NAMES = {
    "chemical_biological": "شیمیایی و زیستی",
    "harmful": "آسیب‌رسان؛ دستهٔ عام",
    "copyright": "حق نشر",
    "illegal": "فعالیت غیرقانونی",
    "cybercrime_intrusion": "جرایم سایبری و نفوذ",
    "harassment_bullying": "آزار و قلدری",
    "misinformation_disinformation": "اطلاعات نادرست و گمراه‌سازی",
    "Hate, harassment and discrimination": "نفرت، آزار و تبعیض",
    "Illegal goods and services": "کالاها و خدمات غیرقانونی",
    "Non-violent crimes": "جرایم غیرخشونت‌آمیز",
    "Sexual content": "محتوای جنسی",
    "Violence": "خشونت؛ تعریف منبع",
    "Disinformation and deception": "اطلاعات نادرست و فریب",
}
V_NAMES = {
    "V1": "تشویق و تحریک",
    "V2": "تهدید جسمی",
    "V3": "برنامه‌ریزی حمله",
    "V4": "دستورالعمل عملیاتی",
    "V5": "تسهیل و کمک",
}


def fa(value):
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def esc(value):
    return html.escape(str(value), quote=True)


def donut(items, center, caption, *, category_buttons=False):
    total = sum(value for _, value, _ in items)
    circumference = 2 * math.pi * 85
    offset = 0
    circles, legend = [], []
    for index, (label, value, category) in enumerate(items):
        color = COLORS[index % len(COLORS)]
        length = circumference * value / total if total else 0
        circles.append(
            f'<circle cx="120" cy="120" r="85" fill="none" stroke="{color}" '
            f'stroke-width="24" stroke-dasharray="{length:.4f} {circumference:.4f}" '
            f'stroke-dashoffset="{-offset:.4f}" transform="rotate(-90 120 120)">'
            f"<title>{esc(label)}: {fa(value)}</title></circle>"
        )
        offset += length
        percentage = 100 * value / total if total else 0
        tag = "button" if category_buttons else "div"
        attrs = f' type="button" data-category="{esc(category)}"' if category_buttons else ""
        legend.append(
            f'<{tag} class="legend-item"{attrs}><span class="legend-dot" style="--dot:{color}"></span>'
            f"<span>{esc(label)}</span><strong>{fa(value)}</strong>"
            f"<small>{fa(f'{percentage:.1f}')}%</small></{tag}>"
        )
    return (
        '<div class="donut-layout"><svg viewBox="0 0 240 240" class="donut" role="img" '
        f'aria-label="{esc(caption)}"><title>{esc(caption)}</title>'
        '<circle cx="120" cy="120" r="85" fill="none" stroke="#edf1f3" stroke-width="24"/>'
        + "".join(circles)
        + f'<text x="120" y="118" text-anchor="middle" class="donut-number">{fa(center)}</text>'
        f'<text x="120" y="146" text-anchor="middle" class="donut-caption">{esc(caption)}</text>'
        '</svg><div class="legend">' + "".join(legend) + "</div></div>"
    )


def bars(counts, *, names=None, color="#087e8b", denominator=None):
    maximum = max(1, max(counts.values(), default=1))
    rows = []
    for name, value in sorted(counts.items(), key=lambda p: (-p[1], p[0])):
        label = names.get(name, name) if names else name
        tone = "#e6a23c" if name == "Violence" else color
        percent = f" · {fa(f'{100 * value / denominator:.1f}')}٪" if denominator else ""
        rows.append(
            '<div class="bar-row">'
            f'<div class="bar-label"><span>{esc(label)}</span><b>{fa(value)}<small>{percent}</small></b></div>'
            f'<div class="bar-track"><span style="width:{100 * value / maximum:.2f}%;background:{tone}"></span></div>'
            + (f'<div class="raw-label" dir="ltr">{esc(name)}</div>' if label != name else "")
            + "</div>"
        )
    return "".join(rows)


def build_report(root: Path, run_directory: Path, output: Path, *, as_of="2026-10-26"):
    samples = load_jsonl(root / "data/normalized/benchmark_samples.jsonl", BenchmarkSample)
    sources = load_jsonl(root / "data/normalized/benchmark_sources.jsonl", SourceRecord)
    summary = json.loads((run_directory / "all54_summary.json").read_text())
    records = [
        json.loads(line)
        for line in (run_directory / "all54_categorized_samples.jsonl").read_text().splitlines()
    ]
    canonical = {s.sample_id: s for s in samples}
    if len({row["sample_id"] for row in records}) != len(records):
        raise ValueError("Duplicate reviewed sample IDs")
    for row in records:
        sample = canonical[row["sample_id"]]
        if sample.dataset_name != "strongreject" or sample.source_category != "Violence":
            raise ValueError("Reviewed scope must be explicit StrongREJECT/Violence")
        if row["processing_status"] != "classified":
            raise ValueError("Report requires completed reviewed decisions")
        if row["original_prompt"] != sample.original_prompt:
            raise ValueError("Report text differs from canonical source")
        expected = (
            "other_violence"
            if row["annotation"]["label"] == "out_of_scope"
            else row["annotation"]["label"]
        )
        if row["category"] != expected:
            raise ValueError("Category mapping differs from the recorded decision")
    counts = Counter(row["category"] for row in records)
    if dict(counts) != summary["combined_category_counts"]:
        raise ValueError("Reviewed counts and summary do not reconcile")
    source_violence_total = sum(
        s.dataset_name == "strongreject" and s.source_category == "Violence" for s in samples
    )
    if len(records) != source_violence_total:
        raise ValueError("Reviewed records do not cover the entire source violence category")
    datasets = Counter(s.dataset_name for s in samples)
    category_counts = {
        name: Counter(s.source_category for s in samples if s.dataset_name == name)
        for name in ("harmbench", "strongreject")
    }
    origin_counts = Counter(
        row["source_metadata"].get("prompt_source", "unspecified") for row in records
    )
    subcategories = Counter(
        v
        for row in records
        if row["category"] == "unsafe_violence"
        for v in row["annotation"]["subcategories"]
    )
    review_pending = sum(row["annotation"]["review_status"] != "approved" for row in records)
    payload = {
        "as_of": as_of,
        "summary": summary,
        "records": records,
        "corpus": {
            "total": len(samples),
            "dataset_counts": dict(datasets),
            "category_counts": {key: dict(value) for key, value in category_counts.items()},
            "split_counts": dict(Counter(s.dataset_split for s in samples)),
            "language_counts": dict(Counter(s.original_language for s in samples)),
        },
        "sources": [s.model_dump(mode="json") for s in sources],
    }
    data = (
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    source_cards = []
    for source in sources:
        source_cards.append(
            '<div class="source-record">'
            f'<strong dir="ltr">{esc(source.dataset_name)} / {esc(source.dataset_split)}</strong>'
            f"<span>{fa(source.record_count)} نمونه</span>"
            f'<a href="{esc(source.source_url)}" target="_blank" rel="noopener noreferrer">فایل اصلی ↗</a>'
            f'<code dir="ltr">SHA256: {esc(source.sha256)}</code>'
            "<small>commit بازیابی‌شده: "
            + esc(source.retrieved_commit or "در registry ثبت نشده")
            + "</small></div>"
        )
    replacements = {
        "__DATA__": data,
        "__DATE__": esc(as_of),
        "__TOTAL__": fa(len(samples)),
        "__REVIEWED__": fa(len(records)),
        "__ACCEPTED__": fa(counts["unsafe_violence"]),
        "__OTHER__": fa(counts["other_violence"]),
        "__PENDING__": fa(review_pending),
        "__NEW__": fa(summary.get("reviewed_new_samples", len(records))),
        "__PREVIOUS__": fa(summary.get("previously_reviewed_samples", 0)),
        "__CATEGORY_COUNT__": fa(sum(len(value) for value in category_counts.values())),
        "__HB_COUNT__": fa(datasets["harmbench"]),
        "__SR_COUNT__": fa(datasets["strongreject"]),
        "__HB_VAL__": fa(
            sum(s.dataset_name == "harmbench" and s.dataset_split == "validation" for s in samples)
        ),
        "__HB_TEST__": fa(
            sum(s.dataset_name == "harmbench" and s.dataset_split == "test" for s in samples)
        ),
        "__CORPUS_DONUT__": donut(
            [
                ("HarmBench", datasets["harmbench"], "harmbench"),
                ("StrongREJECT", datasets["strongreject"], "strongreject"),
            ],
            len(samples),
            "نمونه در ورودی",
        ),
        "__RESULT_DONUT__": donut(
            [
                ("مطابق تعریف پروژه", counts["unsafe_violence"], "unsafe_violence"),
                ("سایر خشونت‌های منبع", counts["other_violence"], "other_violence"),
            ],
            len(records),
            "نمونهٔ بررسی‌شده",
            category_buttons=True,
        ),
        "__HB_BARS__": bars(
            category_counts["harmbench"], names=CATEGORY_NAMES, denominator=datasets["harmbench"]
        ),
        "__SR_BARS__": bars(
            category_counts["strongreject"],
            names=CATEGORY_NAMES,
            color="#5267c6",
            denominator=datasets["strongreject"],
        ),
        "__ORIGIN_BARS__": bars(origin_counts, color="#5267c6", denominator=len(records)),
        "__V_BARS__": bars(
            {v: subcategories[v] for v in V_NAMES},
            names={v: v + " · " + label for v, label in V_NAMES.items()},
        ),
        "__SOURCE_RECORDS__": "".join(source_cards),
        "__USAGE__": fa(f"{summary['provider_account_usage_after_usd']:.4f}"),
        "__CAP__": fa(f"{summary['provider_account_cap_usd']:.2f}"),
        "__REMAINING__": fa(f"{summary['remaining_provider_credit_usd']:.4f}"),
        "__NET__": fa(f"{summary['provider_account_increase_usd']:.4f}"),
        "__METER__": fa(f"{summary['new_run_metered_cost_usd']:.4f}"),
        "__BUDGET_WIDTH__": str(
            min(
                100,
                100
                * summary["provider_account_usage_after_usd"]
                / summary["provider_account_cap_usd"],
            )
        ),
    }
    template = Path(__file__).with_name("templates") / "visual_report.html"
    document = template.read_text()
    for key, value in replacements.items():
        if key != "__DATA__":
            document = document.replace(key, value)
    # Untrusted dataset strings must never be interpreted as template markers.
    document = document.replace("__DATA__", data)
    from pvb.translation.report import section as translation_section

    translations = translation_section(root.resolve())
    if translations:
        document = document.replace("</main>", translations + "</main>", 1)
        document = document.replace("</nav>", '<a href="#translations">ترجمه‌ها</a></nav>', 1)
    write_text(output, document)
    return {
        "output": str(output),
        "corpus_samples": len(samples),
        "reviewed_samples": len(records),
        "category_counts": dict(counts),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/benchmark_visual_report.html"))
    parser.add_argument("--as-of", default="2026-10-26")
    args = parser.parse_args()
    print(
        json.dumps(
            build_report(args.root, args.run, args.output, as_of=args.as_of), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
