"""Offline HTML view of the independently recorded portability annotations."""

import html
import json

from pvb.extraction.io import write_text

TITLES = {
    "translation_portable": "قابل انتقال با ترجمهٔ وفادار",
    "localization_required": "نیازمند بومی‌سازی با نظارت انسانی",
    "uncertain": "نیازمند بررسی بیشتر",
}
COLORS = {
    "translation_portable": "#087e8b",
    "localization_required": "#c48720",
    "uncertain": "#69778f",
}


def write_report(directory):
    summary = json.loads((directory / "summary.json").read_text())
    records = [
        json.loads(line) for line in (directory / "assessments.jsonl").read_text().splitlines()
    ]
    e = lambda value: html.escape(str(value if value is not None else "—"), quote=True)
    cards = "".join(
        f'<article style="border-top:4px solid {COLORS[label]}"><strong>{summary["label_counts"][label]}</strong><span>{title}</span>'
        f'<div class="track"><i style="width:{100 * summary["label_counts"][label] / max(1, len(records))}%;background:{COLORS[label]}"></i></div></article>'
        for label, title in TITLES.items()
    )
    rows = []
    for index, row in enumerate(records, 1):
        d = row.get("cultural_portability") or {}
        label = d.get(
            "label",
            "manual_review_required"
            if row["portability_status"] == "manual_review_required"
            else "incomplete",
        )
        previous = "مطابق تعریف خشونت" if row["category"] == "unsafe_violence" else "سایر خشونت‌ها"
        details = (
            '<details><summary>متن اصلی و متادیتا</summary><pre dir="ltr">'
            + e(row["original_prompt"])
            + "</pre>"
            + (
                '<pre dir="ltr">' + e(row["original_context"]) + "</pre>"
                if row["original_context"]
                else ""
            )
            + '<h4>شواهد متن اصلی</h4><pre dir="ltr">'
            + e("\n\n".join(d.get("evidence", [])))
            + "</pre>"
            + "<h4>ویژگی‌هایی که باید حفظ شوند</h4><p>"
            + e("؛ ".join(d.get("invariants_to_preserve", [])))
            + "</p>"
            + '<h4>متادیتای منبع</h4><pre dir="ltr">'
            + e(
                json.dumps(
                    {
                        "sample_id": row["sample_id"],
                        "dataset_name": row["dataset_name"],
                        "dataset_split": row["dataset_split"],
                        "source_category": row["source_category"],
                        "source_metadata": row["source_metadata"],
                        "portability_run_id": row.get("portability_run_id"),
                        "original_annotation_id": row["annotation"]["annotation_id"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            + "</pre></details>"
        )
        rows.append(
            f'<tr data-label="{e(label)}"><td>{index}</td><td><div class="english" dir="ltr">{e(row["original_prompt"][:140])}</div>{details}</td>'
            f"<td>{e(previous)}<small>{e(row['source_metadata'].get('prompt_source'))}</small></td>"
            f'<td><b style="color:{COLORS.get(label, "#69778f")}">{e(TITLES.get(label, "ارجاع مستقیم به انسان" if label == "manual_review_required" else "ارزیابی کامل نشده"))}</b><small>{e(", ".join(d.get("dependency_dimensions", [])))}</small></td>'
            f"<td>{e(d.get('rationale'))}<small>زمینهٔ منبع: {e(d.get('source_context_summary'))}</small></td>"
            f"<td>{e(d.get('localization_guidance'))}</td></tr>"
        )
    options = "".join(
        f'<option value="{label}">{title}</option>' for label, title in TITLES.items()
    )
    if summary.get("manual_review_due_provider_refusal"):
        options += (
            '<option value="manual_review_required">ارجاع مستقیم به انسان؛ عدم پذیرش API</option>'
        )
    markup = """<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ارزیابی انتقال‌پذیری فرهنگی بنچمارک</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f3f5f3;color:#172b3b;font:14px/1.9 Tahoma,sans-serif}main{max-width:1500px;margin:auto;padding:32px 24px}h1{font-size:30px;margin:0 0 10px}header p{color:#61707e;max-width:1050px}.meta{font-size:12px;color:#647582}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:26px 0}article{padding:22px;background:#fff;border-radius:15px;border:1px solid #dfe7e7}article strong{font-size:38px;display:block}article span{font-size:13px}.track{height:7px;background:#edf1f2;border-radius:5px;margin-top:16px;overflow:hidden}.track i{display:block;height:100%}.notice{background:#fff3da;border:1px solid #ead5a9;border-radius:12px;padding:17px;margin:20px 0;font-size:12px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:22px 0}input,select,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #ccd8db;background:white;color:#172b3b}input{min-width:260px;flex:1}button{cursor:pointer}a{color:#087e8b}.table{overflow:auto;background:white;border:1px solid #dfe7e7;border-radius:15px}table{border-collapse:collapse;width:100%;min-width:1050px}th,td{text-align:right;padding:16px;vertical-align:top;border-bottom:1px solid #e4ebeb;font-size:12px}th{background:#eaf0f0}td:nth-child(2){min-width:240px;max-width:320px}td:nth-child(5){min-width:220px}td:last-child{min-width:190px}small{display:block;font-size:10px;color:#697888;margin-top:8px;overflow-wrap:anywhere}.english{font:12px/1.8 Arial,sans-serif;text-align:left}details{margin-top:12px}summary{color:#087e8b;cursor:pointer;font-size:11px}pre{white-space:pre-wrap;overflow-wrap:anywhere;text-align:left;font:11px/1.8 ui-monospace,monospace;background:#f3f6f6;padding:12px;border-radius:8px}h4{margin:12px 0 4px;font-size:11px}.counter{font-size:12px;color:#647582}.cross{margin:20px 0;border:1px solid #dfe7e7;background:white;border-radius:14px;padding:20px;overflow:auto}.cross table{min-width:500px}footer{font-size:11px;color:#61707e;margin-top:25px}input:focus-visible,select:focus-visible,button:focus-visible{outline:3px solid #e6a23c}@media(max-width:650px){main{padding:22px 14px}h1{font-size:24px}.cards{grid-template-columns:1fr;gap:12px}article{padding:15px}article strong{display:inline-block;margin-left:15px;font-size:30px}input{min-width:100%}}@media print{body{background:white}.toolbar{display:none}main{padding:0}table{min-width:0;font-size:9px}th,td{padding:7px;font-size:9px}.table{overflow:visible}details{display:none}article{break-inside:avoid}h1{font-size:23px}td:nth-child(2),td:nth-child(5),td:last-child{min-width:0;max-width:none}.cards{grid-template-columns:repeat(3,1fr)}}
    </style><main><header><div class="meta">PersianViolenceBench · Cultural portability review</div><h1>آیا ترجمه کافی است یا بومی‌سازی لازم است؟</h1><p>ارزیابی مستقل ۵۴ نمونه از روی متن انگلیسی؛ برچسب خشونت قبلی حفظ شده است. «قابل انتقال» یک پیش‌بینی پژوهشی دربارهٔ حفظ معنای درخواست است و اثبات جهان‌شمول بودن در همهٔ فرهنگ‌ها نیست.</p>__META__</header><section class="cards">__CARDS__</section><div class="notice">همهٔ تصمیم‌ها موقت و نیازمند بازبینی انسانی‌اند. هیچ ترجمهٔ واقعی یا ارزیابی توسط افراد فرهنگ مقصد انجام نشده است. راهنمای بومی‌سازی فقط پرسش و کنترل پژوهشی است؛ متن آسیب‌رسان بازنویسی یا عملیاتی نشده است.</div>__CROSS__<div class="toolbar"><input id="query" type="search" placeholder="جست‌وجو در متن، دلیل، فرهنگ، کشور یا شناسه…" aria-label="جست‌وجو"><select id="label" aria-label="فیلتر برچسب"><option value="all">همهٔ تصمیم‌ها</option>__OPTIONS__</select><span id="counter" class="counter" aria-live="polite"></span><button id="print" type="button">چاپ / PDF</button><a href="portability_review.csv">فایل CSV کامل</a></div><div class="table"><table><thead><tr><th>#</th><th>نمونه</th><th>دستهٔ خشونت قبلی / منشأ</th><th>برچسب فرهنگی جدید</th><th>دلیل و زمینهٔ منبع</th><th>راهنمای نظارت انسانی</th></tr></thead><tbody id="rows">__ROWS__</tbody></table></div><footer>این HTML محلی است و هیچ API یا داده‌ای به بیرون ارسال نمی‌کند. متن نمونه‌ها فقط به‌صورت متن نمایش داده می‌شود.</footer></main><script>const rows=[...document.querySelectorAll('#rows tr')],q=document.getElementById('query'),label=document.getElementById('label');function filter(){let n=0;rows.forEach(r=>{r.hidden=!( (label.value==='all'||r.dataset.label===label.value)&&r.textContent.toLocaleLowerCase().includes(q.value.trim().toLocaleLowerCase()));if(!r.hidden)n++});document.getElementById('counter').textContent=new Intl.NumberFormat('fa-IR').format(n)+' نمونه از '+new Intl.NumberFormat('fa-IR').format(rows.length)}q.addEventListener('input',filter);label.addEventListener('change',filter);document.getElementById('print').addEventListener('click',()=>window.print());filter();</script></html>"""
    cross_rows = "".join(
        "<tr><td>"
        + ("مطابق تعریف خشونت" if category == "unsafe_violence" else "سایر خشونت‌ها")
        + "</td>"
        + "".join(f"<td>{values[label]}</td>" for label in TITLES)
        + "</tr>"
        for category, values in summary["by_original_violence_category"].items()
    )
    cross = (
        '<section class="cross"><h3>دو محور مستقل: تعریف خشونت و انتقال‌پذیری فرهنگی</h3><table><tr><th>دستهٔ قبلی</th>'
        + "".join(f"<th>{title}</th>" for title in TITLES.values())
        + "</tr>"
        + cross_rows
        + "</table></section>"
    )
    meta = (
        '<div class="meta">مدل: '
        + e(summary["model"])
        + " · مقصد درنظرگرفته‌شده: "
        + e(summary["target_context"])
        + " · مصرف ثبت‌شدهٔ حساب پس از بررسی: "
        + e(summary.get("provider_usage_after_usd"))
        + " دلار</div>"
    )
    if summary.get("manual_review_due_provider_refusal"):
        meta += f'<div class="notice">مدل برای {summary["model_assessments"]} نمونه ارزیابی داده است. {summary["manual_review_due_provider_refusal"]} نمونه را ارائه‌دهنده نپذیرفت و مستقیماً به بازبین انسانی ارجاع شده است؛ برای آن‌ها برچسب فرهنگی به نام مدل ساخته نشده است.</div>'
    for key, value in {
        "__META__": meta,
        "__CARDS__": cards,
        "__CROSS__": cross,
        "__OPTIONS__": options,
        "__ROWS__": "".join(rows),
    }.items():
        markup = markup.replace(key, value)
    write_text(directory / "portability_report.html", markup)
