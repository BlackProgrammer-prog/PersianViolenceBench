# راهنمای ورود و اعتبارسنجی داده

## نصب و اجرا

تمام وابستگی‌ها با `uv` و lockfile مدیریت می‌شوند. محیط آزمایش‌شده `Python 3.10.22` است. از ریشهٔ مخزن اجرا کنید:

```bash
uv sync
uv run python -m pvb.ingestion.normalize --config configs/datasets.yaml --output data/normalized
uv run python -m pvb.ingestion.validate --config configs/datasets.yaml --input data/normalized
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

نسخهٔ بدون argument هر دو command نیز همین مسیرهای پیش‌فرض را دارد. commandهای نصب‌شدهٔ `pvb-normalize` و `pvb-validate` معادل entry pointهای ماژولی‌اند.

```bash
uv run python -m pvb.ingestion.normalize --help
uv run python -m pvb.ingestion.validate --help
```

کد خروج `0` موفقیت و `1` خطای داده یا I/O است. `--help` با کد `0` تمام می‌شود. پیام‌ها از `logging` می‌آیند و نمونه‌های دارای محتوای حساس به‌صورت عادی در log چاپ نمی‌شوند.

## manifest

`configs/datasets.yaml` یک object سخت‌گیرانه با `schema_version`، `root` و `sources` است. `root` نسبت به پوشهٔ فایل config و `path` هر source نسبت به آن حل می‌شود. این قاعده اجازه می‌دهد manifest را با مسیر کامل از محل دیگری اجرا کنید. مسیر `--output` و `--input` نسبت به پوشهٔ جاری command هستند.

هر source دارای `dataset_name`، `dataset_split`، `path` و `source_url` است. `expected_record_count` اختیاری و صرفاً انتظار snapshot است. `retrieved_commit` و `commit_repository` برای تأیید محلی و اختیاری Git هستند. کلید ناشناخته یا dataset/split تکراری در manifest رد می‌شود.

## مراحل pipeline

۱. manifest اعتبارسنجی و namespaceهای منبع بررسی می‌شوند.

۲. hash بایت‌های raw پیش و پس از خواندن محاسبه می‌شود تا تغییر فایل حین پردازش آشکار شود.

۳. adapter، header دقیق از نظر مجموعهٔ ستون‌ها را کنترل می‌کند؛ ترتیب ستون ورودی می‌تواند متفاوت باشد. هیچ ستون ناشناخته یا تکراری پذیرفته نیست. خواندن با `UTF-8-SIG`، `newline=''` و parser سخت‌گیرانه انجام می‌شود.

۴. prompt، metadata، hash و identity نمونه تولید و مدل canonical اعتبارسنجی می‌شود. همهٔ نمونه‌ها قبل از export در حافظه جمع‌آوری و uniqueness کنترل می‌شود.

۵. registry با تعداد واقعی و hash فایل ساخته می‌شود. اختلاف با انتظار manifest هشدار می‌دهد.

۶. هر سه خروجی به‌صورت قطعی در پوشهٔ موقت روی همان filesystem نوشته و `fsync` می‌شوند. پس از تکمیل staging، `os.replace` برای هر فایل اجرا می‌شود. خطای پردازش یا serialization پیش از مرحلهٔ replace، خروجی قبلی را دست‌نخورده نگه می‌دارد.

۷. validator به‌طور جداگانه هر دو قالب را بارگذاری می‌کند و schema، فیلدهای اجباری، enumها، metadata، hash متن و رکورد، identity، یکتایی، برابری CSV/JSONL، شمارش‌ها و registry را می‌سنجد. سپس نمونه‌ها و registry دوباره از raw تولید و کامل تطبیق می‌یابند.

در صورت خطا، دادهٔ خراب را اصلاح یا snapshot را آگاهانه عوض کنید؛ خطا را با حذف رکورد دور نزنید. pipeline فایل خام گمشده را خودکار دانلود نمی‌کند تا snapshot ناخواسته تغییر نکند. در صورت نیاز، دریافت منبع باید جداگانه و با ثبت provenance انجام شود.

## اعتبارسنجی بدون raw

برای artifact منتقل‌شده به محیط فاقد raw:

```bash
uv run python -m pvb.ingestion.validate --input data/normalized --skip-raw
```

این حالت هشدار محدودیت می‌دهد. ساختارها، hashهای بازسازی‌شده، identity، یکتایی، برابری دو قالب و شمارش registry کنترل می‌شوند؛ ولی کامل‌بودن نسبت به snapshot اصلی، hash بایت‌های فایل خام و صحت منشأ قابل اثبات نیستند. اجرای پیش‌فرض raw را الزامی می‌داند.

## ذخیره‌سازی

`BenchmarkRepository` در `storage/contracts.py` قرارداد `upsert_source`، `upsert_sample`، `upsert_samples`، `get_sample`، `get_source`، `list_sources`، `list_samples` و `ingest` را تعریف می‌کند. `InMemoryRepository` پیاده‌سازی مرجع است:

```python
from pathlib import Path
from pvb.ingestion.normalize import collect
from pvb.storage.memory import InMemoryRepository

samples, sources = collect(Path("configs/datasets.yaml"))
repository = InMemoryRepository()
repository.ingest(sources, samples)
repository.ingest(sources, samples)  # retry: شمارش عوض نمی‌شود
records = repository.list_samples(dataset_name="harmbench", dataset_split="test")
```

ثبت کامل snapshot و batch نامعتبر پیش از mutation بررسی می‌شوند. `ingest` namespaceهای مربوطه را جایگزین می‌کند؛ retry همان داده idempotent است. `upsert_source` جایگزینی خاموش منبع با snapshot متفاوت را نمی‌پذیرد؛ برای آن از `ingest` استفاده می‌شود.

## افزودن منبع جدید

۱. ابتدا schema ورودی، مجوز استفاده، معنای split و provenance را بررسی کنید و raw را جدا از normalized نگه دارید.

۲. برای dataset جدید enumها، metadata نسخه‌دار discriminated، قواعد `original_record` و validatorهای سازگاری را با تغییر نسخهٔ آگاهانه توسعه دهید. صرف افزودن نام دلخواه به YAML کافی نیست.

۳. adapter جداگانه با header صریح، حفظ متن، فیلدهای لازم و خطاهای دارای location بنویسید. identity و hash مشترک را استفاده کنید.

۴. dispatch منبع در `collect` و manifest را به‌روز کنید. برای فایل جدید در namespace موجود ابتدا مدل چندفایلی را طراحی کنید؛ نسخهٔ فعلی فقط یک فایل در هر dataset/split می‌پذیرد.

۵. آزمون نگاشت، Unicode، metadata، duplicate، round-trip، خرابی ورودی، deterministic export و تطبیق provenance اضافه کنید؛ سپس normalize، validate و کل test suite را اجرا کنید.

۶. نگاشت، سیاست null و تغییر schema را در اسناد ثبت کنید؛ migration نسخهٔ قبلی باید صریح باشد.

## محدودیت‌های شناخته‌شده

- پردازش و مخزن مرجع در حافظه‌اند؛ برای corpus بسیار بزرگ باید streaming، indexing و transaction پایگاه داده طراحی شود.
- replace هر فایل atomic است؛ سه فایل یک transaction مشترک filesystem نیستند. یک writer اجرا کنید و خواندن هم‌زمان با انتشار را هماهنگ کنید. قطع سیستم یا خطای replace در میانهٔ انتشار می‌تواند به bundle مختلط منجر شود؛ validator آن را تشخیص می‌دهد و اجرای مجدد bundle را بازسازی می‌کند. تضمین durability در برابر قطع برق در سطح directory ارائه نمی‌شود.
- چند snapshot فعال از یک dataset/split در مخزن مرجع پشتیبانی نمی‌شود؛ نسخه‌های خام و artifactهای snapshotهای تاریخی را جدا نگه دارید.
- upstream commit بدون مدرک محلی معتبر null است؛ metadata امضای منشأ نیست.
- زبان canonical در این نسخه فقط `en` است و وجود متن غیرانگلیسی در رشته به‌صورت خودکار دسته‌بندی نمی‌شود.
- taxonomy نهایی، استخراج Violence، ترجمه، annotation، inference، evaluation و adapter واقعی `NexoraDB` خارج از این مرحله هستند.
