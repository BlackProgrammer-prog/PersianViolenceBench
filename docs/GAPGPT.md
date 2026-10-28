# طبقه‌بندی با GapGPT

backend مستقل `gapgpt` مدل انتخاب‌شدهٔ `gpt-5.6-terra` را از `https://api.gapgpt.app/v1` فراخوانی می‌کند. کلید فقط از `GAPGPT_API_KEY` خوانده می‌شود؛ کلید OpenRouter جایگزین آن نمی‌شود. redirect و endpoint دلخواه پذیرفته نمی‌شوند. نام کامل مشاهده‌شدهٔ پاسخ، `openai/gpt-5.6-terra`، به‌عنوان همان مدل پذیرفته می‌شود؛ مدل دیگری پذیرفته نمی‌شود.

تنظیمات در `.env` ریشهٔ پروژه:

```env
GAPGPT_API_KEY=your_key_here
GAPGPT_MODEL=gpt-5.6-terra
GAPGPT_CONCURRENCY=2
GAPGPT_TIMEOUT_SECONDS=180
GAPGPT_REASONING_EFFORT=medium
PVB_API_MAX_COST_USD=2
PVB_CLASSIFICATION_MAX_OUTPUT_TOKENS=8192
```

کلید را در چت، Git یا فایل گزارش قرار ندهید. شناسهٔ مدل در فهرست زندهٔ GapGPT بررسی می‌شود؛ هیچ fallback به مدل دیگری وجود ندارد. مدل به‌طور خودکار عوض نمی‌شود.

```bash
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode config-check
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode preflight
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode estimate-cost --selection pilot
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode smoke --confirm-paid-run
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode pilot --confirm-paid-run
```

سه دستور اول generation ندارند. smoke یک نمونه و pilot همان ۲۰ نمونهٔ development قطعی با seed فاز سوم را اجرا می‌کند. تنظیم مسیرها در `configs/gapgpt.yaml` و خروجی در `runs/gapgpt/pvb-gap-.../` است. prompt فعال `violence-classifier-1.3.0` است؛ قواعد معنایی 1.2.0 حفظ شده‌اند و فقط پروتکل evidence عوض شده است. نسخه‌های قبلی prompt برای provenance نگه داشته شده‌اند. اجرای full خودکار آغاز نمی‌شود.

درخواست از Chat Completions با `response_format=json_schema` و `strict=true`، `max_completion_tokens` و `reasoning_effort` استفاده می‌کند. پارامترهای اختصاصی OpenRouter مانند `provider.only` و `provider.max_price` به GapGPT ارسال نمی‌شوند. اعتبارسنجی JSON، enumها، سازگاری تصمیم، evidence عیناً موجود در ورودی و review انسانی با backend قبلی مشترک است. هر retry پیام راهنمای ثابت اعتبارسنجی دریافت می‌کند؛ پاسخ نامعتبر بازپخش یا خودکار تبدیل به برچسب معتبر نمی‌شود.

در نسخهٔ 1.3.0، برنامه حداکثر ۶۴ قطعهٔ عیناً موجود در prompt/context با طول حداکثر ۱۶۰ نویسه می‌سازد. این قطعه‌ها در پیام user جدا با نام `evidence_catalog` و به‌عنوان دادهٔ غیرقابل‌اعتماد ارسال می‌شوند. مدل به‌جای بازنویسی نقل‌قول، index عددی قطعه‌های مرتبط را انتخاب می‌کند؛ index منفی، bool، رشته یا عدد خارج از محدوده رد می‌شود. برنامه متن اصلی قطعهٔ انتخابی را در Decision و annotation قرار می‌دهد و وجود آن در ورودی را دوباره کنترل می‌کند. schema نهایی annotation همچنان evidence از نوع فهرست رشته‌ها دارد. [] مجاز است و این روش انتخاب شاهد را به مدل می‌سپارد؛ مرتبط بودن شاهد و درستی label همچنان نیازمند review است.

## بودجه با صورت‌حساب واقعی حساب

در بررسی زنده، `/v1/models` تعرفهٔ توکن نداشت؛ نرخ مستقیم OpenAI به‌جای تعرفهٔ GapGPT فرض نمی‌شود. اگر نرخ قابل‌تفسیر موجود نباشد، preflight مسیرهای زیر را با همان کلید می‌خواند:

```text
GET /v1/dashboard/billing/subscription
GET /v1/dashboard/billing/usage
```

`hard_limit_usd` باید مثبت و حداکثر برابر `PVB_API_MAX_COST_USD` باشد و اعتبار مصرف‌نشده وجود داشته باشد. قرارداد سازگار با OpenAI/New API، `total_usage` را به واحد سنت دلار برمی‌گرداند؛ برای دلار بر ۱۰۰ تقسیم می‌شود. پاسخ‌های زندهٔ حساب و سقف ۲ دلار با این قرارداد تطبیق داده شدند. اطلاعات هویتی حساب و کلید ذخیره یا چاپ نمی‌شوند.

در حالت `pricing_origin=provider_budget`، قیمت توکن‌ها و estimate برابر null هستند. قبل از هر درخواست، همهٔ بودجهٔ باقی‌مانده reservation می‌شود. درخواست‌های این حالت یکی‌یکی ارسال می‌شوند تا تفاضل کنتور حساب با یکدیگر هم‌پوشانی نداشته باشند. بعد از پاسخ، کنتور با تأخیرهای محدود تا مجموع ۱۵٫۵ ثانیه خوانده می‌شود؛ تنها پس از مشاهدهٔ افزایش مثبت، مبلغ واقعی با `accounting_basis=provider_meter` تسویه می‌شود. تا آن زمان reservation آزاد نمی‌شود. پاسخ معتبر می‌تواند حفظ شود، اما اگر کنتور دیر برسد، unavailable شود یا درخواست timeout/cancel شود، کل reservation محفوظ می‌ماند و generation بعدی آن backend متوقف می‌شود.

کنتور ممکن است مصرف سایر برنامه‌های همان حساب/کلید را نیز شامل شود؛ در آن صورت تفاضل محافظه‌کارانه بیشتر از هزینهٔ درخواست خودمان است. سقف واقعی سمت سرویس برقرار می‌ماند، ولی تضمین رفتار حسابداری یا قطع اعتبار ارائه‌دهنده خارج از کنترل client است. برای مقایسهٔ تمیز، هم‌زمان از همان کلید در برنامهٔ دیگری استفاده نکنید.

اگر تعرفهٔ تأییدشدهٔ خود GapGPT را دارید، می‌توان نرخ ورودی/خروجی به‌ازای یک میلیون توکن، هزینهٔ هر درخواست و منبع آن را در `GAPGPT_INPUT_USD_PER_MILLION`، `GAPGPT_OUTPUT_USD_PER_MILLION`، `GAPGPT_REQUEST_USD` و `GAPGPT_PRICING_SOURCE` تنظیم کرد. این نرخ‌ها به‌عنوان `operator_configured` ثبت می‌شوند و ادعای تأیید خودکار provider ندارند. فیلد bare `usage.cost` بدون ارز صریح USD مبنای تسویه نیست.

## گزارش و ادامهٔ اجرا

### سایر خشونت‌ها و ردیابی بنچمارک

دستهٔ گزارشی `other_violence` («سایر خشونت‌ها طبق تعریف منبع») فقط وقتی انتخاب می‌شود که نمونه واقعاً طبقه‌بندی شده باشد، بنچمارک اصلی آن را در دستهٔ صریح خشونت گذاشته باشد و label مدل طبق تعریف ما `out_of_scope` باشد. این یک تفکیک گزارشی است؛ label اصلی و annotation مدل حفظ می‌شوند. out_of_scopeهای موضوعات دیگری مثل بدافزار یا فریب در همین گروه قرار نمی‌گیرند. نمونهٔ پردازش‌نشده، شکست‌خورده یا abstained نیز «ردشده» تلقی نمی‌شود.

تنظیم قابل‌کنترل در `configs/gapgpt.yaml` و `configs/openrouter.yaml`:

```yaml
source_violence_categories:
  strongreject: [Violence]
  harmbench: []
```

در snapshot فعلی StrongREJECT دستهٔ اختصاصی `Violence` دارد. HarmBench دسته‌ای با این نام ندارد؛ دستهٔ عام `harmful` خودکار معادل خشونت فرض نمی‌شود. mapping فقط برای تفکیک و گزارش پس از طبقه‌بندی استفاده می‌شود؛ metadata منبع به classifier فرستاده نمی‌شود و جای تعریف خشونت یا ground truth را نمی‌گیرد.

خروجی‌های هر run:

- `categorized_samples.jsonl`: تمام نمونه‌های همان run، با متن اصلی، ۱۴ فیلد canonical، دستهٔ گزارشی، annotation و مشخصات اجرای مدل.
- `categorized_samples.csv`: نسخهٔ جدولی برای فیلتر کردن `dataset_name`، `dataset_split`، `source_category` و category. metadata تو در تو به‌صورت JSON در سلول‌ها حفظ می‌شود.
- `categories/other_violence.jsonl`: فقط خشونت‌های منبع که تعریف ما آن‌ها را خارج از دامنه دانسته است. فایل خالی یعنی در همان run مورد واجد شرط وجود نداشته است.
- `source_violence_inventory.jsonl`: فهرست همهٔ نمونه‌های ورودی از دسته‌های صریح خشونت منبع، همراه با `in_this_run`. موارد انتخاب‌نشده با `processing_status=not_selected` و label=null مشخص می‌شوند.
- `classification_report.json`: شامل `category_counts`، شمارش دسته‌ها به تفکیک بنچمارک، `category_rules` و `source_violence_coverage` برای تعداد بررسی‌شده، ردشده و هنوز انتخاب‌نشده.

نام بنچمارک، split، شناسهٔ اصلی رکورد، دسته و tagهای اصلی، source_metadata، hashهای رکورد/متن و registry منبع شامل URL و hash فایل حفظ می‌شوند. `source_registry` فایل‌های ثبت‌شده برای همان dataset/split را نشان می‌دهد. فایل‌های canonical و annotation اصلی با این خروجی‌های مشتق‌شده عوض نمی‌شوند.

برای ساخت این فایل‌ها از نتیجهٔ موجود، حالت `report` کافی است و completion یا هزینهٔ API جدید ندارد:

```bash
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode report --resume RUN_ID
```

report، request journal، annotations، cache provenance و review queue با همان قرارداد فاز سوم ساخته می‌شوند؛ `provider` و `annotator_id` برابر gapgpt هستند. مدل، prompt، schema، تنظیمات و implementation برای هر run frozen هستند. نتیجهٔ روش یا provider قبلی بازنویسی نمی‌شود. برای report گرفتن بدون completion تازه:

```bash
uv run python -m pvb.extraction.pipeline --backend gapgpt --mode report --resume RUN_ID
```

برای resume باید همان تنظیمات، داده و implementation حفظ شده باشد. درخواست قطع‌شده با هزینهٔ نامعلوم خودکار تکرار نمی‌شود. نتیجهٔ نرم‌افزاری موفق، دقت علمی یا تأیید انسانی برچسب‌ها را ثابت نمی‌کند.

## بررسی انتخاب مشخص از نمونه‌ها

حالت `selected` فقط شناسه‌های صریح `selected_sample_ids` در config را اجرا می‌کند. لیست باید غیرخالی، بدون تکرار و شامل شناسه‌های موجود در ورودی canonical باشد. نمونه‌های held-out از split=test در این حالت مجاز نیستند؛ workflow جداگانهٔ full برای آن‌ها حفظ شده است. دادهٔ ورودی یا شناسه‌ها عوض نمی‌شوند و انتخاب دقیق در config/run ثبت می‌شود.

فایل `configs/gapgpt_remaining_violence.yaml` شامل همان ۵۲ نمونهٔ StrongREJECT/Violence است که در اجرای `pvb-gap-31f369e2df0e418ba5a4b02631bd0f36` انتخاب نشده بودند. اجرای آن با سقف ۲ دلار از این دستور انجام می‌شود:

```bash
uv run python -m pvb.extraction.pipeline --backend gapgpt \
  --config configs/gapgpt_remaining_violence.yaml \
  --mode selected --confirm-paid-run
```

برای ادامهٔ همان run بعد از توقف، شناسهٔ واقعی را به همان دستور با `--resume RUN_ID` اضافه کنید. شروع run تازه معادل resume نیست؛ cache معتبر منشأ خود را حفظ می‌کند و مصرف واقعی حساب در هر حال زیر کنترل سقف ارائه‌دهنده می‌ماند.

منابع قرارداد: [مدل GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)، [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) و [قرارداد billing سازگار با New API](https://doc.newapi.pro/api/fei-account-billing-panel/). قابلیت native مدل، اثبات اجرای موفق همان قابلیت در gateway نیست؛ validation محلی برقرار است.
