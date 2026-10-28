# منشأ و بازتولیدپذیری

فایل‌های `data/raw/` ورودی immutable این مرحله هستند. ingestion نه دانلود می‌کند و نه فایل خام را تغییر می‌دهد. URL بالادستی در `configs/datasets.yaml` ذخیره می‌شود و نام یا مسیر مطلق دستگاه در canonical sample و registry وارد نمی‌شود.

## registry منابع

هر ورودی manifest یک `SourceRecord` با دقیقاً این فیلدها تولید می‌کند:

| فیلد | شرح |
|---|---|
| `source_id` | شناسهٔ قطعی نسخهٔ فایل منبع |
| `schema_version` | `1.0.0` |
| `dataset_name` | نام enum منبع |
| `dataset_split` | split واقعی منبع |
| `source_url` | URL ثبت‌شدهٔ بالادستی |
| `sha256` | hash تمام بایت‌های فایل خام، شامل BOM و newlineها |
| `record_count` | تعداد واقعی رکوردهای پذیرفته‌شده، بدون header |
| `retrieved_commit` | SHA کامل commit تأییدشده، یا null |

SHA256 فایل‌های snapshot موجود:

| منبع | SHA256 |
|---|---|
| HarmBench validation | `7bfaaa5e2b9b95002c89e2d33c019f58e9e8496e2fc65d368f1eeb8179e69534` |
| HarmBench test | `75d257b3e7428c52eb7b0154318f455af3e01b09a3794b5e2f3d36054f3c0e29` |
| StrongREJECT unspecified | `4dd70357e4ff8b5d0ba5ebafecab5d6dd5633ce8046e3dd1c8bd93e64de44381` |

این hashها snapshot محلی را مشخص می‌کنند؛ به‌تنهایی اثبات منشأ شبکه یا مالکیت مؤلف نیستند. URLهای `main` قابل تغییرند. زمان دریافت و commit فایل‌های از قبل دانلودشده معلوم نیست و ساخته نمی‌شوند.

## تعریف دقیق hash و identity

در توابع زیر، `H(text)` برابر SHA256 بایت‌های UTF-8 و نمایش lowercase hexadecimal است. `J(value)` برابر serialization زیر در Python است:

```python
json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
```

رکورد منبع یک object با همهٔ نام‌ستون‌ها و مقدارهای string، شامل رشته‌های تهی است. شمارهٔ سطر و مسیر در آن وارد نمی‌شوند. این قرارداد، hash بایت‌های خط CSV نیست و ادعای پیاده‌سازی استاندارد عمومی مانند JCS نیز ندارد.

```text
raw_record_sha256 = H(J(complete_original_csv_record))
prompt_sha256 = H(original_prompt)
sample_id = "pvb:" + dataset_name + ":" + H(J([
    "1.0.0", dataset_name, dataset_split, raw_record_sha256
]))
source_id = "pvb:source:" + H(J([
    "1.0.0", dataset_name, dataset_split, source_url, sha256_of_raw_file
]))
```

تغییر ترتیب ستون یا سطر، identity نمونه‌ها را عوض نمی‌کند. تغییر هر مقدار رکورد، حتی metadata، نسخهٔ دیگری از نمونه می‌سازد. تغییر بایت‌های فایل خام، identity منبع را عوض می‌کند. تغییر split یا منبع، namespace دیگری می‌سازد. این تفکیک، متن یکسان در دو منبع را به دو رکورد مستقل تبدیل می‌کند.

## ثبت commit بدون جعل provenance

پیش‌فرض `retrieved_commit: null` است. مقدار SHA صرفاً از معتبر بودن قالب آن قابل تأیید نیست. برای ثبت اختیاری commit، یک checkout محلی از همان مخزن بالادستی با objectهای لازم در اختیار قرار دهید و این دو مقدار را در source مربوطه تنظیم کنید:

```yaml
retrieved_commit: <full-40-character-lowercase-git-commit-sha>
commit_repository: external/HarmBench
```

`commit_repository` نسبت به `root` manifest حل می‌شود و فقط تنظیم محلی است؛ در registry ذخیره نمی‌شود. کد با دستورهای read-only `git remote get-url origin`، `git rev-parse --verify` و `git show`، origin متناظر، commit واقعی و hash blob همسان با فایل خام را بررسی می‌کند. هیچ fetch، checkout یا دانلودی انجام نمی‌شود. اگر repository موجود نباشد، origin نادرست باشد، commit موجود نباشد یا بایت‌ها متفاوت باشند، هشدار ثبت و مقدار خروجی null می‌شود. verifier فعلی فقط URLهای `raw.githubusercontent.com` با ساختار `owner/repo/ref/path` را پشتیبانی می‌کند؛ ref دارای slash پشتیبانی نمی‌شود.

checkout محلی و تنظیم origin ورودی مورد اعتماد پژوهشگر هستند؛ این مکانیزم امضای رمزنگاری‌شده یا اثبات زمان دریافت فراهم نمی‌کند. در snapshot حاضر هیچ commit تأییدشده‌ای در اختیار نیست و هر سه مقدار null هستند.

## سیاست تکرار و خطا

- `BehaviorID` تکراری در یک split از HarmBench خطاست، حتی اگر متن متفاوت باشد.
- رکورد کامل تکراری در StrongREJECT باعث `sample_id` تکراری و خطا می‌شود.
- در کل خروجی، تکرار `sample_id` خطاست؛ هیچ deduplication خاموشی وجود ندارد.
- prompt یکسان با metadata یا منبع متفاوت حفظ می‌شود؛ `prompt_sha256` امکان تحلیل بعدی تکرارها را می‌دهد.
- هیچ برچسب Violence از `source_category` استنتاج نمی‌شود.
- تعداد متفاوت با snapshot تنظیم‌شده هشدار است؛ تعداد واقعی به registry می‌رود. validator تعداد واقعی raw و artifactها را تطبیق می‌دهد.
- خطای header، تعداد سلول، quoting، UTF-8، فیلد اجباری یا schema با مسیر و شمارهٔ خط گزارش می‌شود. رکورد خالی نیز خطاست؛ حذف خاموش انجام نمی‌شود.

اعتبارسنجی عادی، علاوه بر بازسازی hash هر رکورد، فایل خام را دوباره می‌خواند و تمام نمونه‌ها و تمام registry را مقایسه می‌کند؛ بنابراین کم‌شدن هماهنگ تعداد نمونه‌ها در CSV، JSONL و registry نیز پنهان نمی‌ماند.
