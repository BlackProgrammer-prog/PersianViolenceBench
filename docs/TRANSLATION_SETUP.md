# سه نسخهٔ زبانی بنچمارک

ورودی فعلی هر ۵۴ نمونهٔ بررسی‌شده است: ۳۵ نمونهٔ مطابق تعریف خشونت پروژه و ۱۹ نمونهٔ «سایر خشونت‌ها». هر دو دسته در تمام نسخه‌ها با همان `sample_id`، دسته‌بندی، متادیتای بنچمارک و مرجع annotation حفظ می‌شوند.

این مرحله فقط تنظیمات و طرح داده‌ها را آماده می‌کند. فرمان ترجمهٔ پولی در این مرحله اضافه یا اجرا نشده است؛ وضعیت pending به‌معنای ترجمهٔ انجام‌شده نیست.

| نسخه | زبان | روش و مشخصات |
|---|---|---|
| `english` | انگلیسی | متن و context اصلی بدون تغییر |
| `llm_translation` | فارسی | LLM با ثبت provider و نام دقیق مدل در `model_requested`؛ مدل برگشتی بعد از اجرا باید جدا ثبت شود |
| `google_translate` | فارسی | Google Cloud Translation Basic v2 با مدل NMT |

## چه چیزی را در .env پر کنم؟

قسمت جدید انتهای `.env` و `.env.example` با عنوان Three benchmark language variants مشخص شده است. کلیدهای قبلی دست‌نخورده‌اند. متغیرهای اصلی:

```env
PVB_TRANSLATION_SCOPE=all
PVB_TRANSLATION_SOURCE_LANGUAGE=en
PVB_TRANSLATION_TARGET_LANGUAGE=fa

PVB_TRANSLATION_LLM_PROVIDER=gapgpt
PVB_TRANSLATION_LLM_MODEL=gpt-5.6-terra
PVB_TRANSLATION_LLM_BASE_URL=https://api.gapgpt.app/v1
PVB_TRANSLATION_LLM_CREDENTIAL_ENV=GAPGPT_API_KEY

GOOGLE_TRANSLATE_API_KEY=
PVB_GOOGLE_TRANSLATE_EDITION=basic_v2
PVB_GOOGLE_TRANSLATE_MODEL=nmt
PVB_TRANSLATION_MAX_COST_USD=2.00
```

برای LLM، کلید موجود `GAPGPT_API_KEY` خوانده می‌شود؛ نیازی به کپی دوبارهٔ آن نیست. مقدار `PVB_TRANSLATION_LLM_CREDENTIAL_ENV` **نام متغیر** است، نه خود کلید. برای عوض کردن مدل ترجمه، `PVB_TRANSLATION_LLM_MODEL` را عوض کنید؛ مدل دسته‌بندی قبلی مستقل باقی می‌ماند. انتخاب OpenRouter نیز با provider=openrouter، base URL رسمی آن و نام متغیر `OPENROUTER_API_KEY` پشتیبانی تنظیماتی دارد؛ کلید سرویس دیگر خودکار جایگزین نمی‌شود.

مقدار خالی `GOOGLE_TRANSLATE_API_KEY` را با کلید **Google Cloud Translation API** پر کنید. در پروژهٔ Google Cloud مربوط به همان کلید، Cloud Translation API و billing باید فعال باشند. این انتخاب Basic v2 است؛ برای آن service-account JSON، location یا مسیر Advanced v3 لازم نیست. طبق [مستندات احراز هویت گوگل](https://docs.cloud.google.com/translate/docs/authentication)، Basic v2 از API key پشتیبانی می‌کند و Advanced v3 از این روش پشتیبانی نمی‌کند. مدل NMT صریحاً انتخاب شده تا نسخهٔ Google Translate با نسخهٔ LLM قاطی نشود؛ [مستندات مدل ترجمه](https://docs.cloud.google.com/translate/docs/translate-text).

`PVB_TRANSLATION_MAX_COST_USD` سقف درخواستی برای مرحلهٔ اجرای آینده است؛ آماده‌سازی فعلی هیچ هزینه‌ای ندارد و این متغیر، سقف billing جدیدی در Google Cloud ایجاد نمی‌کند. کلید را در چت یا گزارش قرار ندهید.

## بررسی تنظیمات، بدون شبکه

```bash
uv run python -m pvb.translation --mode config-check
```

این فرمان فقط بررسی محلی تنظیمات است و اعتبار واقعی کلید یا مجوز حساب را با API آزمایش نمی‌کند. تا زمان پر شدن کلید گوگل، `google_configuration_ready=false` طبیعی است. هیچ credential در خروجی public یا طرح داده‌ها چاپ/ذخیره نمی‌شود.

## آماده‌سازی نسخه‌ها، بدون ترجمه

```bash
uv run python -m pvb.translation --mode prepare
```

ورودی از `PVB_TRANSLATION_INPUT` و مسیر خروجی از `PVB_TRANSLATION_OUTPUT` خوانده می‌شود. مقدار scope=all هر دو دستهٔ فعلی را حفظ می‌کند. خروجی در پوشه‌ای مانند `runs/translation/plan-.../` ساخته می‌شود:

```text
plan.json
english/samples.jsonl              # 54 متن اصلی؛ status=original
llm_translation/pending.jsonl      # 54 رکورد منتظر ترجمه؛ متن فارسی=null
google_translate/pending.jsonl     # 54 رکورد منتظر ترجمه؛ متن فارسی=null
```

هر نسخه `variant_id` مستقل و `sample_id` مشترک دارد. provider، مدل درخواستی، زبان، hash متن/context اصلی، متادیتای منبع و شناسهٔ annotation/run اصلی نگه داشته می‌شوند. `model_returned=null` یعنی هنوز مدلی برای آن ترجمه اجرا نشده است. برچسب‌ها فعلاً از نسخهٔ انگلیسی ارجاع می‌گیرند و اثبات هم‌ارزی معنایی ترجمه یا ground truth انسانی نیستند.

داده‌های canonical انگلیسی و نتایج دسته‌بندی قبلی بازنویسی نمی‌شوند. اگر فایل طرح دستی تغییر کرده باشد، prepare آن را خودکار بازنویسی نمی‌کند.
