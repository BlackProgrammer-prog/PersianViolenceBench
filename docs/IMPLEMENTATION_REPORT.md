# گزارش اجرای پیاده‌سازی

این سند گزارش تاریخی فاز اول است. نتیجهٔ جدید در [گزارش فاز دوم](PHASE2_IMPLEMENTATION_REPORT.md) آمده است.

تاریخ گزارش: ۲۰۲۶-۱۰-۲۴. محیط اجرای واقعی: `Ubuntu Linux`، `Python 3.10.22`، `uv 0.13.4`.

## فایل‌های ایجاد یا اصلاح‌شده

- `pyproject.toml`: نسخهٔ پروژه، وابستگی‌ها، build برای `pvb`، entry pointها و تنظیم ابزارها.
- `uv.lock`: قفل وابستگی‌های نصب‌شده با `uv`.
- `.gitignore`: جلوگیری از ورود cache، محیط مجازی و secretهای متداول به Git.
- `README.md`: معرفی فارسی، معماری و راهنمای شروع.
- `configs/datasets.yaml`: سه ورودی snapshot، URL، مسیر، split و انتظار شمارش.
- `configs/taxonomy.yaml`: جای‌نگهدار نسخه‌دار بدون دسته‌بندی نهایی.
- `src/persianviolencebench/__init__.py`: scaffold قبلی به `src/pvb/__init__.py` منتقل و جایگزین شد.
- `src/pvb/schemas/{__init__,common,metadata,samples,sources,validation}.py`: schemaهای strict و invariantهای مشترک.
- `src/pvb/ingestion/{__init__,config,provenance,normalize,export,validate}.py`: pipeline، export و validation.
- `src/pvb/ingestion/adapters/{__init__,base,harmbench,strongreject}.py`: CSV reader و adapterها.
- `src/pvb/storage/{__init__,contracts,memory}.py`: قرارداد مستقل و مخزن حافظه.
- `src/pvb/storage/nexoradb/README.md`: مرز integration و پژوهش لازم.
- `tests/{conftest,test_schemas,test_harmbench,test_strongreject,test_normalization,test_validation,test_storage,test_provenance}.py`: آزمون‌ها.
- `docs/{DATA_SCHEMA,DATA_PROVENANCE,INGESTION,IMPLEMENTATION_REPORT}.md`: مستندات فارسی.
- `data/normalized/{benchmark_samples.csv,benchmark_samples.jsonl,benchmark_sources.jsonl}`: خروجی‌های تولید و تأییدشده.

فایل‌های raw بدون تغییر ماندند. scaffoldهای نامرتبط موجود در `configs/` تغییر نکردند.

## schema نهایی

نسخه `1.0.0`، دقیقاً ۱۴ فیلد و بدون `source_file`:

```text
schema_version, sample_id, dataset_name, dataset_split, source_record_id,
original_language, original_prompt, original_context, source_category,
functional_category, source_tags, source_metadata, raw_record_sha256, prompt_sha256
```

نوع، نگاشت و قواعد سازگاری هر فیلد در `DATA_SCHEMA.md` آمده‌اند. metadata دارای union discriminated با `source_type` است و تمام فیلدهای تعریف‌شده اجباری‌اند؛ کلید ناشناخته رد می‌شود.

## نتیجهٔ پردازش و اعتبارسنجی

| منبع | split | رکورد |
|---|---|---:|
| HarmBench | validation | 80 |
| HarmBench | test | 320 |
| StrongREJECT | unspecified | 313 |
| مجموع | | 713 |

سه سند source registry ساخته شد. اعتبارسنجی schema، metadata، hashها، identity، uniqueness، شمارش، برابری CSV/JSONL و تطبیق کامل با raw موفق بود. هیچ اختلاف شمارش نسبت به snapshot فعلی وجود نداشت. هر سه `retrieved_commit` برابر null هستند؛ commit قابل تأیید برای rawهای موجود در دسترس نبود.

هر سه artifact پس از اجرای مجدد روی دادهٔ واقعی byte-identical بودند. SHA256 خروجی‌ها:

| artifact | SHA256 |
|---|---|
| `benchmark_samples.csv` | `c6d42d7ce399a91bb8f368dd9f02935cd65e13bc3558c2de2096e21351b303f3` |
| `benchmark_samples.jsonl` | `f4b8efaf22ab7950bc72a595f4044d9369d3de10235c8d6a0d38fcd7a8595b29` |
| `benchmark_sources.jsonl` | `d283de8f8c9214a5d151268d732430dfdffa4358d5a2c236cccaa90b58ff29c2` |

hash فایل‌های raw پیش و پس از اجرای تکراری یکسان بود. import و اجرای pipeline با حذف `PYTHONPATH` از محیط نیز موفق بود.

## آزمون‌ها و دستورهای اجراشده

اجرای نهایی `uv run pytest -v`: تعداد **104 passed**، بدون skip و failure، در **0.94s**. آزمون integration هر سه فایل واقعی اجرا شد. آزمون‌های staging failure، جلوگیری از overwrite فایل خام، nullهای مبهم در CSV، کلید تکراری JSON، commit تأییدنشده، idempotency و جایگزینی snapshot نیز اجرا و موفق شدند.

دستورهای اصلی اجراشده، با همان spelling:

```bash
uv add 'pydantic>=2,<3' 'pyyaml>=6,<7'
uv add --dev 'pytest>=8,<10' 'ruff>=0.14,<1'
uv sync
uv run python --version
uv run python -m pvb.ingestion.normalize
uv run python -m pvb.ingestion.validate
uv run python -m pvb.ingestion.normalize --help
uv run python -m pvb.ingestion.validate --help
uv run pytest -q
uv run pytest -v
uv run ruff check --fix .
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
```

بررسی نهایی Ruff بدون خطا و تمام ۳۳ فایل Python مطابق formatter بودند. علاوه بر دستورهای بالا، اسکریپت Python با `env -u PYTHONPATH uv run python -`، hashهای raw و خروجی‌ها را قبل و بعد از فراخوانی دوبارهٔ `normalize` مقایسه و `validate_bundle == (713, 3)` را assert کرد.

## محدودیت‌ها و NexoraDB

مسئلهٔ حل‌نشده‌ای برای پردازش snapshot فعلی باقی نمانده است. commit بالادستی معلوم نیست و به‌درستی null باقی مانده است. atomic replacement برای هر فایل برقرار است؛ انتشار سه فایل transaction مشترک ندارد. خواندن/نوشتن هم‌زمان نیاز به هماهنگی دارد. پردازش در حافظه انجام می‌شود و مخزن مرجع durability ندارد.

برای `NexoraDB` باید SDK/API رسمی، سازگاری Python، اتصال و authentication، مدل document، indexهای یکتا، upsert/bulk، transaction، pagination، retry و failure semantics تأیید شوند. سپس adapter واقعی باید قرارداد و آزمون‌های integration پایگاه داده را اجرا کند. هیچ API یا syntax فرضی پیاده‌سازی نشده است؛ جزئیات در `src/pvb/storage/nexoradb/README.md` ثبت شده‌اند.
