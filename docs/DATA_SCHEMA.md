# ساختار canonical نسخهٔ 1.0.0

مدل `BenchmarkSample` دقیقاً شامل فیلدهای جدول زیر و با همین ترتیب است. همهٔ کلیدها اجباری‌اند؛ nullable بودن به معنای مجاز بودن حذف کلید نیست. `source_file` وجود ندارد. فیلد ناشناخته و تبدیل ضمنی نوع رد می‌شوند. مدل‌ها frozen هستند؛ مخزن حافظه از مجموعه‌های mutable نیز با کپی و اعتبارسنجی مجدد محافظت می‌کند.

| ردیف | فیلد | نوع | معنا و قاعده |
|---:|---|---|---|
| 1 | `schema_version` | string | مقدار ثابت `1.0.0` |
| 2 | `sample_id` | string | شناسهٔ قطعی SHA256 با namespace منبع |
| 3 | `dataset_name` | enum | `harmbench` یا `strongreject` |
| 4 | `dataset_split` | enum | `validation`، `test` یا `unspecified` |
| 5 | `source_record_id` | string/null | `BehaviorID` در HarmBench؛ null در StrongREJECT |
| 6 | `original_language` | string | `en`، کد BCP 47 منابع فعلی؛ زبان با الگوریتم تشخیص داده نمی‌شود |
| 7 | `original_prompt` | string | متن دقیق و دارای حداقل یک نویسهٔ غیر whitespace |
| 8 | `original_context` | string/null | `ContextString`؛ رشتهٔ خالی به null نگاشت می‌شود |
| 9 | `source_category` | string | دسته‌بندی اصلی بدون remapping |
| 10 | `functional_category` | string/null | `FunctionalCategory` در HarmBench |
| 11 | `source_tags` | array[string] | برچسب‌های جداشده با کاما؛ در StrongREJECT آرایهٔ خالی |
| 12 | `source_metadata` | discriminated object | ساختار نسخه‌دار و محدود به source_type |
| 13 | `raw_record_sha256` | string | ۶۴ رقم hexadecimal کوچک؛ hash رکورد کامل بازسازی‌پذیر |
| 14 | `prompt_sha256` | string | hash بایت‌های UTF-8 متن دقیق prompt |

HarmBench فقط splitهای `validation/test` را می‌پذیرد. StrongREJECT فقط `unspecified` را می‌پذیرد و `source_record_id`، `original_context` و `functional_category` آن null هستند. `source_tags` آن همواره `[]` است.

## ساختار metadata

انتخاب نوع به کمک discriminator برابر `source_type` انجام می‌شود؛ مقدار آن باید با `dataset_name` نیز برابر باشد. تمام کلیدهای نمایش‌داده‌شده اجباری‌اند. هیچ کلید اضافه‌ای پذیرفته نیست و migration خودکار به نسخه‌ای دیگر وجود ندارد.

HarmBench:

```json
{
  "metadata_schema_version": "1.0.0",
  "source_type": "harmbench",
  "behavior_id": "example_id",
  "semantic_category": "illegal",
  "functional_category": "standard",
  "tags_raw": "",
  "context_string": ""
}
```

مقادیر `behavior_id`، `semantic_category` و `functional_category` باید با فیلدهای canonical متناظر برابر باشند. `context_string` دقیقاً حفظ می‌شود؛ فقط رشتهٔ تهی در `original_context` به null تبدیل می‌شود. رشتهٔ شامل فاصله، context معتبر و عیناً محفوظ است. `tags_raw` همیشه مقدار اصلی را نگه می‌دارد. برای `source_tags`، جداسازی با `,`، حذف فاصلهٔ ابتدا و انتهای هر جزء و حذف اجزای تهی اجرا می‌شود؛ ترتیب و تکرار برچسب‌های غیرتهی حفظ می‌شوند.

StrongREJECT:

```json
{
  "metadata_schema_version": "1.0.0",
  "source_type": "strongreject",
  "prompt_source": "example_source"
}
```

`prompt_source` دقیقاً ستون `source` است و نباید با نام دیتاست اشتباه گرفته شود. مقدار آن باید غیرتهی باشد.

## نگاشت ستون‌ها

| ورودی HarmBench | مقصد canonical | مقصد metadata |
|---|---|---|
| `Behavior` | `original_prompt` | — |
| `BehaviorID` | `source_record_id` | `behavior_id` |
| `SemanticCategory` | `source_category` | `semantic_category` |
| `FunctionalCategory` | `functional_category` | `functional_category` |
| `Tags` | `source_tags` پس از parsing | `tags_raw` عیناً |
| `ContextString` | `original_context` با قاعدهٔ null | `context_string` عیناً |

| ورودی StrongREJECT | مقصد canonical | مقصد metadata |
|---|---|---|
| `forbidden_prompt` | `original_prompt` | — |
| `category` | `source_category` | — |
| `source` | — | `prompt_source` |

تمام ستون‌های منبع قابل بازسازی‌اند؛ همین بازسازی در اعتبارسنجی hash رکورد نیز استفاده می‌شود. محتوای prompt هیچ whitespace normalization، Unicode normalization، ترجمه یا بازنویسی دریافت نمی‌کند. `UTF-8-SIG` فقط BOM ابتدای فایل را مدیریت می‌کند؛ newlineهای داخل سلول حفظ می‌شوند.

## قرارداد serialization

`JSONL` با `UTF-8`، `ensure_ascii=False`، جداکننده‌های فشردهٔ `(',', ':')` و یک LF پس از هر سند نوشته می‌شود. ترتیب کلیدهای canonical برابر جدول است. آرایه‌ها و metadata ساختار واقعی JSON دارند. مقدار غایب اختیاری، JSON `null` است. کلید تکراری در JSON ورودی خطاست.

`CSV` با `UTF-8`، header دقیقاً هم‌ترتیب با جدول، جداکنندهٔ کاما، quoting استاندارد `csv` و پایان رکورد `CRLF` نوشته می‌شود. نقل‌قول و newline داخل سلول توسط CSV writer escape می‌شوند.

در CSV پنج فیلد `source_record_id`، `original_context`، `functional_category`، `source_tags` و `source_metadata` به‌صورت JSON درون سلول ذخیره می‌شوند. برای مثال، null سلول `null` است ولی رشتهٔ واقعی `null`، مقدار JSON برابر `"null"` دارد و CSV writer نقل‌قول‌های لازم را اضافه می‌کند. بنابراین null، رشتهٔ تهی، رشتهٔ `null` و متن شامل backslash با هم اشتباه نمی‌شوند. برای خواندن از `load_samples_csv` استفاده کنید؛ تبدیل عمومی سلول خالی به null قرارداد این پروژه نیست.

نمونه‌ها به ترتیب `sample_id` و registry به ترتیب `source_id` صادر می‌شوند. این ترتیب به محل فایل یا ترتیب رکوردهای ورودی وابسته نیست. ترتیب بایت‌های فایل خام روی hash فایل و registry اثر می‌گذارد، حتی اگر مجموعهٔ نمونه‌ها یکسان باشد.

## entityها و ارتباط پایگاه داده

دو entity مستقل وجود دارند: `BenchmarkSample` و `SourceRecord`. در یک snapshot، زوج `(dataset_name, dataset_split)` یکتا و رابطهٔ منبع به نمونه‌ها یک‌به‌چند است. حذف `source_file` از نمونه‌ها عمدی است؛ مسیر محلی جزو identity نیست. در نسخهٔ فعلی هر namespace فقط یک فایل منبع فعال دارد؛ چند فایل برای یک dataset/split نیازمند نسخهٔ جدید manifest یا مدل ارتباط است.

اسناد JSONL مستقیماً مناسب document persistence هستند. کلید ذخیره‌سازی برای هر entity به‌ترتیب `sample_id` و `source_id` است. `ingest` کامل، namespaceهای ارائه‌شده را به‌صورت یک snapshot جایگزین می‌کند، تعداد رکوردها را بررسی می‌کند و namespaceهای نامرتبط را نگه می‌دارد. `upsert_samples` برای درج تدریجی به ثبت قبلی منبع نیاز دارد؛ تا اتمام batch کامل، شمارش registry الزاماً با رکوردهای درج‌شده برابر نیست. مخزن حافظه برای تست و استفادهٔ تک‌پردازه‌ای است و durability یا concurrency فراهم نمی‌کند.
