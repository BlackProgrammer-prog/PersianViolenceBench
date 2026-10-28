# Phase 3: طبقه‌بندی موقت با OpenRouter

فاز سوم backend اختصاصی async برای OpenRouter، بررسی metadata مدل، بودجه، ثبت usage، اجرای pilot/full، resume و review را اضافه می‌کند. schema چهارده‌فیلدی canonical و taxonomy `pvb-violence@1.0.0` حفظ شده‌اند. classifier درخواست را تحلیل می‌کند و نباید آن را پاسخ دهد یا دستور خشونت بسازد. تمام annotationهای LLM با method=llm، review_status=pending و requires_human_review=true باقی می‌مانند.

## اصلاح pilot در ۲۶ اکتبر ۲۰۲۶

به‌روزرسانی نهایی همان روز: تنظیم فعال اکنون `violence_classifier_v3.txt` با نسخهٔ `violence-classifier-1.3.0` است. شواهد از طریق انتخاب index در catalog قطعه‌های عیناً موجود در ورودی دریافت و به متن اصلی بازسازی می‌شوند؛ schema نهایی annotation و taxonomy تغییر نکرده‌اند. جزئیات این پروتکل و backend جدید در [راهنمای GapGPT](GAPGPT.md) آمده است. شرح 1.2.0 زیر، مرحلهٔ قبلی اصلاح و علت تصمیم‌ها را ثبت می‌کند.

تنظیم فعال `configs/openrouter.yaml` اکنون از `configs/prompts/violence_classifier_v2.txt` با نسخهٔ `violence-classifier-1.2.0` و pacing برابر ۱۸ درخواست در دقیقه استفاده می‌کند. prompt قبلی برای provenance اجرای قبلی حفظ شده است. درخواستِ روشن ولی غیرخشونت‌آمیز—even اگر دربارهٔ بدافزار یا فریب باشد—می‌تواند out_of_scope با intent=harmful باشد؛ نبودن خشونت به‌تنهایی دلیل intent=ambiguous نیست. ابهام واقعی همچنان abstain می‌شود و برنامه برچسب‌های قبلی را خودکار تبدیل نمی‌کند.

schema ارسالی اکنون سقف rationale و evidence و requires_human_review=true را به مدل اعلام می‌کند. validation محلی همچنان JSON، enumها، سازگاری تصمیم و عیناً موجود بودن evidence در یکی از دو فیلد ورودی را کنترل می‌کند. خطاهای JSON، schema و ناسازگاری تصمیم کدهای مجزا دارند. retry برای خطاهای اعتبارسنجی، فقط راهنمای ثابت و trusted همان خطا را به system message اضافه می‌کند؛ پاسخ نامعتبر، دستور بالادستی یا secret در feedback بازپخش نمی‌شود. هر تلاش همچنان reservation و settlement مستقل دارد و تصمیم نامعتبر annotation یا cache معتبر تولید نمی‌کند.

برای مدل‌های دقیق `:free`، قیمت ورودی و خروجی صفر می‌تواند با نبودن request price همراه باشد. فقط در این حالت request price حذف‌شده صفر در نظر گرفته می‌شود؛ قیمت صریح نامعتبر یا surcharge مثبت همچنان رد می‌شود. اگر تمام قیمت‌های قابل‌محاسبه صفر باشند، health code عددی endpoint صرفاً اطلاعاتی است و generation API در دسترس بودن را مشخص می‌کند؛ کدهای متغیر مشاهده‌شدهٔ -2 و -5 به‌عنوان قابلیت structured-output تفسیر نمی‌شوند. بررسی قابلیت‌ها، tag، context و کنترل قیمت در خود درخواست برقرار است. برای endpoint پولی، status غیرصفر همچنان رد می‌شود.

تنظیم اختیاری `PVB_CLASSIFICATION_REASONING_ENABLED=false` reasoning را صریحاً خاموش می‌کند؛ اگر متغیر تعریف نشده باشد پارامتر reasoning ارسال نمی‌شود. `.env.example` سقف خروجی ۸۱۹۲ را پیشنهاد می‌دهد. سقف قبلی ۶۰۰ در مدل فعلی به پاسخ ناقص منجر شد. وضعیت اجراها و نسخه‌های قدیمی در بخش‌های بعدی این سند، تاریخچهٔ مراحل قبلی هستند.

به‌دلیل تغییر prompt/schema/implementation باید run تازه ساخت؛ resume اجرای قدیمی با این تغییرات عمداً رد می‌شود. cache و annotationهای قبلی حفظ می‌شوند و به‌عنوان خروجی روش جدید پذیرفته نمی‌شوند. پایان یافتن pilot به معنای تأیید دقت علمی یا اجازهٔ خودکار اجرای full نیست.

## تنظیمات محلی

فایل credential در مسیر دقیق زیر ایجاد شده و در Git نادیده گرفته می‌شود:

`/home/parham/PersianViolenceBench/.env`

این فایل با permission برابر `0600` و placeholder ساخته شد؛ اگر از قبل وجود داشت، بازنویسی نمی‌شد. `.env.example` الگوی بدون secret است. فایل `.env` را در ویرایشگر خود باز کنید و فقط دو مقدار زیر را با مقادیر واقعی جایگزین کنید:

```env
OPENROUTER_API_KEY=your_actual_api_key
OPENROUTER_MODEL=author/exact-model-id
```

این مثال credential واقعی نیست. کلید را در chat، گزارش یا Git قرار ندهید. شناسهٔ مدل را از catalog رسمی انتخاب کنید؛ شناسهٔ مدل یا provider در کد حدس زده نمی‌شود. `openrouter/auto` و routerهای خودکار پشتیبانی نمی‌شوند. مدل باید endpoint دارای `structured_outputs`، `response_format`، `temperature` و `max_tokens` داشته باشد. فقط وجود response_format به‌عنوان اثبات JSON Schema کافی نیست.

تنظیمات اولیهٔ دیگر: OPENROUTER_BASE_URL=https://openrouter.ai/api/v1، PVB_API_CONCURRENCY=5، PVB_API_MAX_RETRIES=3، PVB_API_TIMEOUT_SECONDS=90، PVB_API_MAX_COST_USD=2.00، PVB_CLASSIFICATION_TEMPERATURE=0 و PVB_CLASSIFICATION_MAX_OUTPUT_TOKENS=600. کنترل pacing با requests_per_minute در `configs/openrouter.yaml` است؛ پیش‌فرض ۳۰ request/minute است. تغییر endpoint به سرویس دیگر در این backend رد می‌شود؛ redirect دنبال نمی‌شود. هیچ مدل جایگزین خودکار ارسال نمی‌شود.

python-dotenv فایل root را خودکار می‌خواند؛ export کردن لازم نیست. متغیر محیطیِ از قبل تنظیم‌شده بر `.env` اولویت دارد. interpolation متغیرها غیرفعال است. کلید در SecretStr و خارج از public config نگهداری می‌شود. مقدار key، headerهای احراز هویت و body خطای provider در artifact یا exception ذخیره/چاپ نمی‌شوند. metadata یا پاسخ شامل کلید شناخته‌شده رد می‌شود.

برای storage واقعی در Ubuntu/Linux x86_64 با Python 3.10:

```bash
uv sync --extra nexoradb
uv run python -m pvb.extraction.pipeline --backend openrouter --mode config-check
```

config-check فقط local است و هیچ درخواست شبکه یا generation ندارد. key خالی/placeholder، مدل خالی، router خودکار، عدد نامعتبر یا endpoint غیررسمی با خطای روشن رد می‌شود. `uv sync` بدون extra برای تست‌های مستقل کافی است؛ native tests در نبود dependency اختیاری skip می‌شوند. paid mode بدون نسخهٔ تأییدشدهٔ NexoraDB شروع نمی‌شود.

## metadata و هزینه، بدون generation

```bash
uv run python -m pvb.extraction.pipeline --backend openrouter --mode preflight
uv run python -m pvb.extraction.pipeline --backend openrouter --mode estimate-cost --selection pilot
uv run python -m pvb.extraction.pipeline --backend openrouter --mode estimate-cost --selection full
```

preflight از `GET /api/v1/models` و `GET /api/v1/models/{author}/{slug}/endpoints` استفاده می‌کند؛ chat completion نمی‌سازد. شناسهٔ دقیق، پارامترهای اعلام‌شده، context/output limits، status و قیمت endpointها کنترل می‌شوند. account restrictions ناشناخته باقی می‌ماند؛ catalog عمومی اثبات مجوز حساب یا موفقیت inference نیست. اگر هیچ endpoint قابل تأیید و دارای قیمت پشتیبانی‌شده وجود نداشته باشد، generation متوقف می‌شود. اجرای بدون قیمت مجاز نیست. محدودیت key/account و تغییرات availability ممکن است بعداً باعث خطای generation شوند.

قیمت‌های prompt/completion از metadata به واحد USD/token خوانده می‌شوند. سقف قیمت و providerهای واجد شرایط در خود request نیز محدود می‌شوند. هزینهٔ request لحاظ می‌شود؛ surchargeهای محاسبه‌نشده، از جمله cache-write پولی یا هزینه‌های اضافی ناشناخته، پذیرفته نمی‌شوند. endpointهایی که قابلیت لازم را اعلام نکرده‌اند از routing حذف می‌شوند. این سیاست محافظه‌کارانه می‌تواند مدل‌هایی را که واقعاً قابل استفاده‌اند نیز رد کند؛ fallback به متن آزاد وجود ندارد.

estimate-cost از `ceil(UTF-8 payload bytes / 4)` به‌عنوان proxy ورودی و max_output_tokens به‌عنوان فرض طول خروجی استفاده می‌کند. این تعداد token دقیق یا قیمت واقعی اجرا نیست. قیمت باید از metadata تأیید شده باشد؛ در غیر این صورت مقدار هزینه ساخته نمی‌شود. برای نگهداری گزارش در مسیر جدید می‌توان `--output runs/phase3/pilot_cost_estimate.json` افزود؛ مسیر موجود بازنویسی نمی‌شود.

برای کنترل budget، قبل از هر تلاش HTTP یک reservation durable ثبت می‌شود: هزینهٔ کل context تأییدشده، max output و request fee با حاشیهٔ ۵٪. این مقدار عمداً محافظه‌کارانه‌تر از estimate معمول است و برای مدل‌های context بزرگ ممکن است حتی یک request به بودجهٔ ۲ دلار نخورد. هزینهٔ reservation هر request در estimate نمایش داده می‌شود؛ در چنین وضعیتی مدل مناسب‌تر یا بودجهٔ صریح دیگری انتخاب کنید. budget به هر run مربوط است؛ محدودیت مطلق هزینهٔ کل حساب نیست.

گزارش، provider-reported cost، token-pricing estimate و accounted cost را جدا نگه می‌دارد. اگر actual cost گزارش نشود، reservation آزاد نمی‌شود، حتی اگر token usage موجود باشد. timeout، cancel و پاسخ گم‌شده نیز ممکن است هزینه داشته باشند. با تمام شدن ظرفیت budget، درخواست تازه—even retry—dispatch نمی‌شود؛ درخواست‌های در حال اجرا ثبت/تسویه می‌شوند. کنترل client-side تضمین مطلق عدم overspend نیست؛ قیمت/usage بالادستی و قطع ارتباط محدودیت دارند. برای سقف حساب، محدودیت credit سمت OpenRouter را نیز می‌توان مستقل تنظیم کرد.

## Stage A: dry run

```bash
uv run python -m pvb.extraction.pipeline --backend openrouter --mode dry-run
```

این دستور با placeholderهای فعلی هم اجرا می‌شود، ولی configuration_ready=false و موارد لازم برای اصلاح را گزارش می‌کند. داده، taxonomy، prompt version، schema، uniqueness، source counts، مسیرهای محافظت‌شده، native connection در صورت نصب و نمونه‌گیری pilot کنترل می‌شوند. هیچ HTTP request انجام نمی‌شود؛ storage محلی ممکن است برای بررسی اتصال collection خالی جدید را آماده کند. گزارش در `runs/phase3/dry-run/dry_run_report.json` است. هیچ label آزمایشی به دادهٔ واقعی اضافه نمی‌شود.

در snapshot موجود ۷۱۳ نمونه، با splitهای ۸۰ validation، ۳۲۰ test و ۳۱۳ unspecified تأیید شدند. pilot با seed=20261024، شامل ۶ HarmBench validation و ۱۴ StrongREJECT است؛ test sample ندارد. طبقه‌های proxy شامل potential_harm، potential_discussion_or_pretext و unclear_or_other هستند. این‌ها برچسب معنایی یا نمونهٔ benign تأییدشده نیستند؛ متن benchmark ممکن است مقدمهٔ ظاهراً آموزشی داشته باشد. شکاف ground truth به‌صراحت حفظ می‌شود.

## Stage B و smoke: تنها با اجازهٔ صریح پرداخت

پس از config-check، preflight و برآورد هزینه:

```bash
uv run python -m pvb.extraction.pipeline --backend openrouter --mode smoke --confirm-paid-run
uv run python -m pvb.extraction.pipeline --backend openrouter --mode pilot --confirm-paid-run
```

smoke یک نمونهٔ توسعه از همان انتخاب قطعی را با structured output واقعی می‌آزماید؛ این دستور نیز می‌تواند هزینه داشته باشد. pilot بیست نمونهٔ قطعی و stratified از development را اجرا می‌کند. source/category فقط در انتخاب و تحلیل بعدی استفاده می‌شود و به primary classifier ارسال نمی‌شود. اجرای pilot باعث آغاز خودکار full نمی‌شود. هیچ‌کدام از این دو دستور هنگام تحویل اجرا نشده‌اند؛ تست‌های آن‌ها mock بودند.

## Stage C: full، freeze و resume

```bash
uv run python -m pvb.extraction.pipeline --backend openrouter --mode full --confirm-full-run
```

این flag اجازهٔ صریح اجرای تمام ۷۱۳ نمونه است؛ --confirm-paid-run به‌تنهایی برای full کافی نیست. قبل از اولین completion، config.json و AnnotationRun شامل hash ورودی، source registry، taxonomy، prompt، schema، config، public settings و implementation ذخیره می‌شوند. metadata مدل، زمان بررسی، مدل دقیق، generation parameters، selection و prompt version ثبت می‌شوند. کل `.env` یا hash کلید ذخیره نمی‌شود. taxonomy/prompt/model/schema و generation config برای آن run frozen هستند. outputهای held-out نباید برای tuning همان ارزیابی استفاده شوند.

برای ادامهٔ همان run، شناسه را از console یا classification_report.json بردارید:

```bash
uv run python -m pvb.extraction.pipeline --backend openrouter --mode pilot --resume RUN_ID --confirm-paid-run
uv run python -m pvb.extraction.pipeline --backend openrouter --mode full --resume RUN_ID --confirm-full-run
```

جای RUN_ID شناسهٔ واقعی pvb-or-... قرار می‌گیرد و mode باید با run اصلی یکسان باشد. input، prompt، metadata پایدار، کد و configuration باید یکسان باشند. تغییر مدل یا generation/schema/context، cache نامناسب را invalid می‌کند. تغییر budget همان run نیز پذیرفته نمی‌شود؛ برای config جدید run تازه بسازید. cacheِ تصمیم‌های معتبر قبلی با fingerprint یکسان می‌تواند هزینهٔ run تازه را کم کند؛ منشأ cache حفظ می‌شود.

reservation قبل از dispatch و settlement قبل از checkpoint نوشته می‌شود. بنابراین بعد از قطع process، پاسخ کامل از event journal بازیابی می‌شود و دوباره هزینه نمی‌شود. checkpoint موفق یا cache معتبر نیاز به completion تازه ندارد. اگر نتیجه/charge قبلی نامعلوم یا cancelled باشد، retry خودکار ممنوع است؛ فقط با افزودن `--retry-uncertain` همراه flag پرداخت می‌توان آن مورد را دوباره فرستاد. reservation قبلی همچنان در budget می‌ماند. Ctrl+C، taskها را cancel و وضعیت partial/report را تا حد امکان ذخیره می‌کند. journal دیسکی امکان recovery پس از شکست DB را هم می‌دهد. نویسندهٔ هم‌زمان در یک output root با lock رد می‌شود.

## prompt، schema و خروجی

prompt فعلی `configs/prompts/violence_classifier_v1.txt` با نسخهٔ مستقل `violence-classifier-1.1.0` است. نسخهٔ فاز دوم در violence_classifier_phase2_v1.txt نگه داشته شده است. taxonomy همچنان 1.0.0 است. system message شامل دستور trusted و taxonomy است؛ user message فقط JSONِ original_prompt و original_context دارد. source_category، functional_category و source_tags به مدل فرستاده نمی‌شوند. دستور داخل sample نقش اجرایی ندارد و باید به‌عنوان داده تحلیل شود. rationale کوتاه و evidence کوتاه و عیناً موجود در sample لازم است؛ chain-of-thought درخواست نمی‌شود.

OpenRouter request از response_format=json_schema، strict=true و provider.require_parameters=true استفاده می‌کند؛ allow_fallbacks=false و فقط یک model ارسال می‌شود. پاسخ JSON باید تمام فیلدهای schema و enumهای صحیح را داشته باشد. confidence خارج از [0,1]، تناقض، فیلد مفقود، JSON خراب، evidence ناموجود، refusal، truncation یا مدل برگشتی نامنتظره، label تولید نمی‌کند. intent=ambiguous به outcome=abstained تبدیل می‌شود؛ tentative Decision برای audit باقی می‌ماند و annotation پذیرفته‌شده ساخته نمی‌شود. abstained label چهارم taxonomy نیست. confidence صرفاً self-assessment غیرکالیبرهٔ مدل است.

HTTP 429، 408، 5xx، timeout، network error و بعضی validation failures با تعداد محدود retry می‌شوند. exponential backoff، jitter و Retry-After رعایت می‌شوند. 401/402/403/404 و خطای دائمی configuration بی‌نهایت retry نمی‌شوند؛ ارسال جدید متوقف می‌شود. هر retry reservation و event جدا دارد. تأخیر HTTP در event ثبت می‌شود؛ pacing و concurrency محدودند.

ساختار هر اجرای واقعی در `runs/phase3/<run_id>/` شامل config.json، model_metadata.json، run.json، annotations.jsonl، annotation_runs.jsonl، results.jsonl، failures.jsonl، request_events.jsonl، events/، checkpoints/، usage.json، cost_report.json، classification_report.json و review_queue.csv است. processed، classified، abstained، failed، not_scheduled و interrupted جدا گزارش می‌شوند و جمع وضعیت‌ها باید با تعداد ورودی برابر باشد. tokenها و هزینه‌های گزارش‌نشده با شمارش coverage متمایز می‌شوند؛ مجموع مقادیر موجود به معنای total واقعیِ کامل نیست.

## NexoraDB و review

adapter تأییدشدهٔ NexoraDataBase==0.2.1 و همان API embedded فاز دوم استفاده می‌شود. چهار entity قبلی باقی‌اند و collection جدید classification_request_events برای reservation، settlement، retry، error، usage، cost، provider و cache provenance اضافه شده است. eventها immutable هستند؛ annotation قدیمی یا rule-based بازنویسی نمی‌شود. وجود sample/run و رابطهٔ settlement/reservation کنترل می‌شود. هر mutation adapter read-after-write دارد. این نسخهٔ engine همچنان sync=false است؛ تست خروج عادی با تضمین power-loss یکسان نیست.

برای مشاهدهٔ metadata و شمارش‌های محلی، بدون API:

```bash
uv run python -c 'from pathlib import Path; from pvb.storage.nexoradb import NexoraRepository; r=NexoraRepository(Path("data/nexoradb")); print([(x.run_id,x.method,x.status) for x in r.list_runs()]); print(len(r.list_annotations()),len(r.list_request_events()))'
```

برای گزارش و export مجدد، completion تازه لازم نیست:

```bash
uv run python -m pvb.extraction.pipeline --backend openrouter --mode report --resume RUN_ID
uv run python -m pvb.extraction.pipeline --backend openrouter --mode export-review --resume RUN_ID --output data/review_phase3.csv
```

صف review با ابهام/خطا، confidence پایین، اختلاف با قواعد، تفاوت category منبع، severity بالا و duplicate عبوری split مرتب می‌شود. category منبع ground truth نیست. دلایل priority در review_priorities.jsonl هستند. CSV از schema فاز دوم پیروی می‌کند و با `pvb.extraction.review import` وارد می‌شود. فایل CSV موجود که ممکن است ویرایش انسانی داشته باشد بازنویسی نمی‌شود؛ پیشنهاد تغییرکرده در نام نسخه‌دار تازه نوشته و نام آن در report ثبت می‌شود. دستور export مسیر تازه می‌خواهد. annotation انسانی و adjudication مستقل از LLM باقی می‌مانند.

۵ گروه duplicate، ۱۲ رکورد و ۲ گروه cross-split فاز دوم بازتأیید شدند. هیچ merge/delete رخ نمی‌دهد. نمونه‌گیری pilot هیچ test ID ندارد؛ overlap محتواییِ validation/test هنوز یک خطر leakage است و برای تحلیل علمی باید طبق سیاست از پیش تعیین‌شده کنترل شود.

## تست، حریم خصوصی و حدود ادعا

```bash
uv sync
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
uv sync --extra nexoradb
uv run pytest -v
```

تست معمولی از httpx.MockTransport و fixture مصنوعی استفاده می‌کند، key واقعی لازم ندارد و هزینه ندارد. native integration فقط در صورت نصب extra اجرا می‌شود. تست live در `live_tests/test_openrouter_live.py` خارج از testpaths معمول است؛ علاوه بر انتخاب صریح فایل، متغیر PVB_ALLOW_PAID_SMOKE=YES می‌خواهد. بدون این مجوز skip می‌شود. دستور زیر **پرداختی و اختیاری** است و در این تحویل اجرا نشده است:

```bash
PVB_ALLOW_PAID_SMOKE=YES uv run pytest live_tests/test_openrouter_live.py -v
```

در اجرای مجاز، prompt و context benchmark همراه دستور classifier و taxonomy به OpenRouter فرستاده می‌شوند و providerهای routed ممکن است طبق سیاست‌های مربوط آن‌ها را پردازش کنند. هیچ فایل خصوصی نامرتبط ارسال نمی‌شود. تنظیمات حریم خصوصی حساب و provider را مستقل بررسی کنید؛ ادعای retention یا ZDRِ تأییدنشده نداریم.

منابع رسمی پژوهش API: [Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs)، [Models](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)، [Endpoints](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model)، [Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection) و [Usage Accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting). metadata اعلام قابلیت است و اثبات موفقیت structured generation نیست؛ enforce دقیق schema میان providerها فرق دارد، بنابراین validation محلی حذف نمی‌شود. usage در API فعلی خودکار برمی‌گردد؛ پارامتر منسوخ usage.include ارسال نمی‌شود.

هنوز classification واقعی OpenRouter، review انسانی، calibration confidence، یا اعتبارسنجی علمی precision/recall انجام نشده است. اجرای موفق نرم‌افزار، benchmark را علمی تأیید نمی‌کند. تا زمان اجازهٔ صریح پرداخت، دادهٔ فعلی همان نتایج موقت قواعد فاز دوم را دارد.

## عیب‌یابی metadata: HTTP 403

در بررسی پس از خطای pilot، هر دو metadata endpoint با و بدون authentication پاسخ HTTP 403 و پیام «Access denied by security policy.» دادند. این مشاهده، مالک policy، علت دقیق منع دسترسی یا اعتبار کلید را مشخص نمی‌کند. key و model محلی تنظیم شده بودند، ولی هیچ generation آغاز نشد.

preflight اکنون در صورت وجود credential معتبر از نظر تنظیمات، header احراز هویت را برای metadata هم ارسال می‌کند؛ placeholder ارسال نمی‌شود. خطا نام endpoint، HTTP status و راهنمای ثابت و امن را نمایش می‌دهد و body/credential دلخواه بالادستی را چاپ نمی‌کند. شکست catalog باعث توقف پیش از درخواست endpoint بعدی می‌شود. برای 401، key را در .env بررسی کنید؛ برای 403، دسترسی سرویس و مجوزهای حساب/شبکه را بررسی یا از پشتیبانی رسمی OpenRouter پیگیری کنید. تغییر مدل یا افزایش budget به‌تنهایی راه‌حل اثبات‌شدهٔ منع دسترسی به catalog نیست.

```bash
uv run python -m pvb.extraction.pipeline --backend openrouter --mode preflight
```

این بررسی generation پرداختی ندارد. چهار regression test جدید، authentication در metadata، حذف placeholder، diagnostic امن 403 و شناسایی endpoint ناموفق را پوشش دادند؛ suite بعد از اصلاح ۲۸۵ آزمون موفق داشت و Ruff نیز موفق بود. اجرای pilot واقعی تا رفع منع دسترسی انجام نشد.
