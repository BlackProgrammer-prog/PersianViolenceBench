# PersianViolenceBench (PVB)

این مخزن شامل کد، تنظیمات نمونه و مستندات است. داده‌های منبع، خروجی‌های اجرا، گزارش‌های تولیدشده، وزن مدل و کلیدهای API محلی‌اند و وارد Git نمی‌شوند. منشأ و نسخهٔ داده‌ها در [DATA_PROVENANCE](docs/DATA_PROVENANCE.md) و روش آماده‌سازی در [INGESTION](docs/INGESTION.md) آمده است.

زیرساخت بازتولیدپذیر یک بنچمارک دانشگاهی برای بررسی ایمنی مدل‌های زبانی در حوزهٔ خشونت فیزیکی علیه دیگر افراد یا گروه‌ها. `Self-Harm` خارج از دامنهٔ این پروژه است.

پروژه شامل ingestion، طبقه‌بندی با API مدل‌های زبانی، ارزیابی مستقل قابلیت انتقال فرهنگی و ترجمهٔ محلی ۵۴ نمونهٔ منتخب با TranslateGemma است. متن و schema چهارده‌فیلدی canonical حفظ شده‌اند. دسته‌بندی منبع، برچسب خشونت محسوب نمی‌شود. برچسب‌ها و ترجمه‌های خودکار هنوز بازبینی انسانی نشده‌اند؛ مقایسهٔ embedding و ارزیابی پاسخ مدل‌ها مرحله‌های بعدی‌اند.

## اجرای سریع

از ریشهٔ مخزن، با `Python 3.10` و `uv`:

```bash
uv sync
uv run python -m pvb.ingestion.normalize
uv run python -m pvb.ingestion.validate
uv run pytest -v
```

فایل‌های خام موجود خوانده می‌شوند و هیچ دانلود یا تغییری روی آن‌ها صورت نمی‌گیرد. نبود فایل خام خطای روشن ایجاد می‌کند. مسیرهای ورودی و تعداد مورد انتظار در `configs/datasets.yaml` تعریف شده‌اند. در snapshot فعلی:

| منبع | split | تعداد |
|---|---|---:|
| HarmBench | validation | 80 |
| HarmBench | test | 320 |
| StrongREJECT | unspecified | 313 |
| مجموع | | 713 |

این اعداد ویژگی snapshot فعلی‌اند؛ اختلاف تعداد با تنظیمات به‌صورت هشدار گزارش می‌شود و باعث حذف رکورد نمی‌شود.

خروجی‌ها در `data/normalized/` قرار می‌گیرند:

- `benchmark_samples.csv`: دقیقاً ۱۴ ستون canonical؛ فیلدهای پیچیده و scalarهای nullable با JSON داخل سلول.
- `benchmark_samples.jsonl`: هر خط یک سند canonical؛ مناسب پایگاه دادهٔ سندگرا.
- `benchmark_sources.jsonl`: یک سند منشأ برای هر فایل ورودی.

## معماری و راهنما

بستهٔ قابل import پروژه `pvb` است و نصب editable از طریق `uv` انجام می‌شود؛ نیازی به `PYTHONPATH` نیست.

| مسیر | مسئولیت |
|---|---|
| `src/pvb/schemas/` | مدل‌های سخت‌گیرانهٔ `Pydantic v2` و قواعد hash و identity |
| `src/pvb/ingestion/adapters/` | خواندن CSV و نگاشت اختصاصی هر منبع |
| `src/pvb/ingestion/config.py` | اعتبارسنجی manifest و حل مسیرهای نسبی |
| `src/pvb/ingestion/provenance.py` | تأیید اختیاری commit با اشیای محلی Git |
| `src/pvb/ingestion/normalize.py` | هماهنگی ingestion و ثبت منشأ |
| `src/pvb/ingestion/export.py` | خروجی قطعی، staging و بارگذاری round-trip |
| `src/pvb/ingestion/validate.py` | کنترل مستقل artifactها و تطبیق با raw |
| `src/pvb/storage/` | قرارداد persistence و پیاده‌سازی مرجع در حافظه |
| `tests/` | آزمون واحد، خرابی ورودی، reproducibility و integration واقعی |

جزئیات پژوهشی:

- [ساختار داده و نگاشت‌ها](docs/DATA_SCHEMA.md)
- [منشأ، شناسه‌ها و قواعد تکرار](docs/DATA_PROVENANCE.md)
- [اجرا، توسعه و محدودیت‌ها](docs/INGESTION.md)
- [پیش‌نیازهای NexoraDB](src/pvb/storage/nexoradb/README.md)

فاز دوم با annotation مستقل، استخراج موقت، abstention، review انسانی، duplicate analysis و adapter واقعی تأییدشدهٔ `NexoraDataBase==0.2.1` اضافه شده است. برای اجرا:

```bash
uv run python -m pvb.extraction.pipeline --config configs/extraction.yaml --backend rules
uv run python -m pvb.extraction.quality
uv run python -m pvb.extraction.duplicates
uv run --extra nexoradb python -m pvb.storage.nexoradb --database data/nexoradb
```

- [تعریف Violence و Taxonomy](docs/VIOLENCE_TAXONOMY.md)
- [راهنمای annotation و بازبینی](docs/ANNOTATION_GUIDELINES.md)
- [استخراج، backendها و بازتولید](docs/EXTRACTION_PIPELINE.md)
- [پژوهش و integration واقعی NexoraDB](docs/NEXORADB_INTEGRATION.md)
- [گزارش اجرای فاز دوم](docs/PHASE2_IMPLEMENTATION_REPORT.md)

خروجی قواعد ground truth نیست: از ۷۱۳ نمونه فقط ۵ match موقت و ۷۰۸ abstention وجود دارد؛ هر ۷۱۳ نمونه نیازمند review هستند. فایل‌های raw و normalized فاز اول تغییر نکرده‌اند.

## فاز سوم: OpenRouter

backend اختصاصی OpenRouter با بارگذاری خودکار `.env`، preflight، هزینه و budget، pilot/full با مجوز صریح، resume، journal و persistence واقعی NexoraDB اضافه شده است. key و مدل در `/home/parham/PersianViolenceBench/.env` تنظیم می‌شوند؛ کلید را در chat نفرستید. pilotهای واقعی توسعه اجرا شده‌اند؛ برچسب‌ها موقت و نیازمند review انسانی هستند.

```bash
uv sync --extra nexoradb
uv run python -m pvb.extraction.pipeline --backend openrouter --mode dry-run
uv run python -m pvb.extraction.pipeline --backend openrouter --mode config-check
```

[راهنمای فارسی Phase 3](docs/PHASE3_OPENROUTER.md) و [گزارش اولیهٔ پیاده‌سازی](docs/PHASE3_IMPLEMENTATION_REPORT.md). آزمون‌های فعلی با `uv run pytest -q` اجرا می‌شوند. تمام ۷۱۳ نمونهٔ canonical و تاریخچهٔ annotation قواعد حفظ شده‌اند.

## GapGPT و مدل GPT-5.6 Terra

برای مدل `gpt-5.6-terra`، کلید مستقل `GAPGPT_API_KEY` در `.env` استفاده می‌شود. سقف حساب ارائه‌دهنده و کنتور مصرف واقعی برای کنترل بودجه بررسی می‌شوند؛ تعرفهٔ مستقیم OpenAI جایگزین تعرفهٔ gateway نمی‌شود.

```bash
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode preflight
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode pilot --confirm-paid-run
```

خروجی در `runs/gapgpt/` ذخیره می‌شود. [راهنمای تنظیمات، بودجه و گزارش GapGPT](docs/GAPGPT.md).

## گزارش تصویری HTML

گزارش فارسی و آفلاین تولیدشده در `reports/benchmark_visual_report.html` شامل ترکیب ۷۱۳ نمونهٔ ورودی، نتیجهٔ بررسی ۵۴ نمونهٔ StrongREJECT/Violence، نمودارهای منشأ و زیرگروه‌ها، بودجه و جدول قابل جست‌وجو با خروجی CSV/JSON است. فایل HTML به‌تنهایی در مرورگر باز می‌شود و هیچ API یا کتابخانهٔ اینترنتی را فراخوانی نمی‌کند. برچسب‌ها همچنان موقت و نیازمند review انسانی‌اند.

برای بازسازی از artifactهای ثبت‌شده:

```bash
uv run python -m pvb.extraction.visual_report \
  --run runs/gapgpt/pvb-gap-621566036e034163884561aaf26d655d \
  --output reports/benchmark_visual_report.html \
  --as-of 2026-10-26
```

## نسخه‌های انگلیسی و ترجمه

تنظیمات سه نسخهٔ مشترک برای همان ۵۴ نمونه در `.env` آماده شده‌اند: انگلیسی اصلی، فارسی با LLM همراه نام مدل و provider، و فارسی با Google Cloud Translation/NMT. فعلاً فقط طرح آفلاین و رکوردهای pending ساخته می‌شوند؛ ترجمهٔ پولی اجرا نشده است.

```bash
uv run python -m pvb.translation --mode config-check
uv run python -m pvb.translation --mode prepare
```

[راهنمای متغیرهای لازم و ساختار نسخه‌ها](docs/TRANSLATION_SETUP.md). متغیر `GOOGLE_TRANSLATE_API_KEY` برای تکمیل توسط کاربر خالی گذاشته شده و LLM از کلید فعلی GapGPT استفاده می‌کند.

## انتقال‌پذیری فرهنگی پیش از ترجمه

محور مستقلی برای همان ۵۴ نمونه تعریف شده است: قابل انتقال با ترجمه، نیازمند بومی‌سازی با نظارت انسانی، یا نامشخص. نتیجه در کنار دستهٔ خشونت قبلی ثبت می‌شود و آن را عوض نمی‌کند. ارزیابی از متن انگلیسی و برای زمینهٔ مقصد fa-IR است؛ ترجمهٔ واقعی یا اعتبارسنجی بین‌فرهنگی انجام‌شده تلقی نمی‌شود.

```bash
uv run python -m pvb.portability --mode config-check
uv run python -m pvb.portability --mode run --confirm-paid-run
```

[راهنمای معیارها، بودجه و خروجی‌های ارزیابی فرهنگی](docs/CULTURAL_PORTABILITY.md).

## Local TranslateGemma translation

The existing translation module now supports local `google/translategemma-4b-it`
with NF4 quantization, offline inference, and resumable translation of the selected 54 samples.
See [setup, execution, and comparison method](docs/TRANSLATEGEMMA.md).

```bash
uv sync --extra local-translation
uv run --extra local-translation python -m pvb.translation.local --mode download
uv run --extra local-translation python -m pvb.translation.local --mode smoke --block-network
uv run --extra local-translation python -m pvb.translation.local --mode translate --block-network
```

