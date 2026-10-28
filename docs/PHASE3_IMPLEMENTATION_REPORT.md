# گزارش پیاده‌سازی Phase 3 — OpenRouter

تاریخ گزارش: ۲۰۲۶-۱۰-۲۴. پیاده‌سازی مستقیماً در PersianViolenceBench انجام شد. `.env` واقعی با placeholder ساخته شد؛ هیچ credential واقعی وارد نشد و **هیچ درخواست پرداختی OpenRouter، pilot واقعی، full واقعی یا smoke واقعی اجرا نشد**. نتایج mock صرفاً fixture آزمون در دایرکتوری موقت‌اند و classification واقعی نامیده نمی‌شوند.

## baseline و حفاظت فازهای قبلی

پیش از تغییر، pyproject، taxonomy/config، schemaهای Pydantic، backend LLM، CLI، workflow review، storage contractها، adapter NexoraDB، annotation runهای قبلی، آزمون‌ها و گزارش‌های فاز اول و دوم بررسی شدند. baseline با اجرای واقعی ۱۹۸ آزمون و تطبیق canonical با raw تأیید شد: ۷۱۳ نمونه، شامل HarmBench validation=80، test=320 و StrongREJECT unspecified=313. خروجی قواعد همان ۵ label موقت unsafe و ۷۰۸ abstention بود. duplicateها ۵ گروه/۱۲ رکورد با ۲ گروه cross-split بودند.

schema canonical همچنان دقیقاً ۱۴ فیلد است. هر شش hash فایل‌های raw و normalized با baseline برابر است. `benchmark_samples.jsonl` همچنان SHA256 برابر `f4b8efaf22ab7950bc72a595f4044d9369d3de10235c8d6a0d38fcd7a8595b29` دارد. هیچ sample، split یا category اصلی تغییر نکرد. taxonomy همان pvb-violence@1.0.0 است.

دیتابیس واقعی پروژه پس از بررسی: benchmark_sources=3، benchmark_samples=713، annotation_runs=2، sample_annotations=10 و classification_request_events=0. ده annotation همان تلاش‌های پنج‌تایی دو run قواعدِ فاز دوم‌اند؛ همه rule_based/pending هستند و بازنویسی نشدند. هیچ annotation انسانی تأییدشده یا LLM واقعی اضافه نشده است. شواهد در `runs/phase3/dry-run/execution_verification.json` ذخیره شد.

## فایل‌های ایجاد/اصلاح‌شده

| مسیر | تغییر |
|---|---|
| `.env` | ایجاد با placeholder، mode=0600، بدون overwrite فایل موجود |
| `.env.example` | الگوی کامل و بدون credential واقعی |
| `.gitignore` | حفظ ignore فایل .env و افزودن cache/lock فاز سوم |
| `pyproject.toml`, `uv.lock` | وابستگی مستقیم httpx و python-dotenv؛ بدون LiteLLM یا SDK اضافی |
| `configs/openrouter.yaml` | مسیرها، prompt version، seed، pacing و threshold review |
| `configs/prompts/violence_classifier_v1.txt` | prompt نسخهٔ 1.1.0 با taxonomy، مرزها، امنیت و abstention |
| `configs/prompts/violence_classifier_phase2_v1.txt` | حفظ نسخهٔ قبلی prompt برای audit |
| `src/pvb/extraction/backends/openrouter.py` | backend اختصاصی async، strict schema، retry، cancellation، بودجه، cache و usage |
| `src/pvb/extraction/backends/llm.py` | هماهنگ‌کردن PROMPT_VERSION با فایل نسخهٔ جدید؛ backend عمومی حفظ شد |
| `src/pvb/extraction/pipeline.py` | dispatch سازگار CLI برای backend=openrouter؛ rules/llm قبلی باقی‌اند |
| `src/pvb/extraction/openrouter/__init__.py` | package بدون اثر شبکه هنگام import |
| `src/pvb/extraction/openrouter/settings.py` | بارگذاری امن root .env، SecretStr، اعتبارسنجی و redaction |
| `src/pvb/extraction/openrouter/models.py` | schema نسخه‌دار metadata، RequestEvent و SampleResult |
| `src/pvb/extraction/openrouter/metadata.py` | مدل دقیق، endpoint، capability، قیمت و محدودیت‌های قابل تأیید |
| `src/pvb/extraction/openrouter/accounting.py` | journal durable و reservation accounting با کنترل in-flight |
| `src/pvb/extraction/openrouter/config.py` | config strict و جلوگیری از تداخل مسیرهای خروجی با ورودی‌های محافظت‌شده |
| `src/pvb/extraction/openrouter/sampling.py` | انتخاب قطعی و stratified pilot بدون test ID |
| `src/pvb/extraction/openrouter/runner.py` | freeze، paid gates، workerها، resume و persistence |
| `src/pvb/extraction/openrouter/reports.py` | reconciliation، usage/cost، priority و CSV سازگار فاز دوم |
| `src/pvb/extraction/openrouter/cli.py` | config-check، preflight، estimate، dry/pilot/full/smoke، report و review export |
| `src/pvb/storage/contracts.py`, `memory.py` | قرارداد و append-only storage برای request eventها و کنترل ارجاعات |
| `src/pvb/storage/nexoradb/repository.py` | reuse API تأییدشده و افزودن collection برای eventها، بدون تغییر engine |
| `tests/test_openrouter.py` | تست رفتار API mock، cost، budget، pacing، recovery، review و native persistence |
| `tests/test_openrouter_settings.py` | dotenv، placeholder، مدل، عددها و secret-free reporting |
| `tests/test_openrouter_cli.py` | dispatch/help و عدم شبکه در config-check/مدل تنظیم‌نشده |
| `live_tests/test_openrouter_live.py` | تست پرداختی اختیاری، خارج از testpaths عادی، با مجوز محیطی جدا |
| `docs/PHASE3_OPENROUTER.md` | راهنمای فارسی دستورها، تنظیمات، هزینه، حدود و حریم خصوصی |
| `docs/PHASE3_TEST_RESULTS_BASE.txt`, `PHASE3_TEST_RESULTS.txt` | log واقعی تست base و native |
| `README.md`, همین گزارش | معرفی وضعیت نهایی و ارجاع به راهنما |
| `runs/phase3/dry-run/` | dry_run_report.json و execution_verification.json واقعی؛ فاقد label ساختگی |

## پژوهش API و backend

پیش از پیاده‌سازی، منابع رسمی [Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs)، [Models](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)، [Endpoints](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model)، [Routing](https://openrouter.ai/docs/guides/routing/provider-selection) و [Usage Accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting) بررسی شدند. این پژوهش عمومی با تأیید live مدل انتخاب‌شده یکی نیست؛ هنوز مدل واقعی انتخاب نشده است.

پیاده‌سازی از POST /api/v1/chat/completions و Bearer authentication با httpx.AsyncClient استفاده می‌کند. endpoint به سرویس دیگر تغییر نمی‌کند و redirect دنبال نمی‌شود. request یک model دارد، model fallback ارسال نمی‌شود و مدل برگشتی غیرمنتظره خطا محسوب می‌شود. routing به endpointهای دارای پارامترهای لازم محدود است. strict JSON Schema و provider.require_parameters=true ارسال و خروجی مستقل با Pydantic کنترل می‌شود. snapshot metadata ادعای موفقیت inference ندارد؛ محدودیت‌های حساب unknown ثبت می‌شوند.

فقط original_prompt و original_context در user message هستند. source labelها به primary classifier ارسال نمی‌شوند. system message شامل taxonomy و دستور trusted است؛ role spoofing داخل sample داده محسوب می‌شود. prompt جدید براساس مثال‌های مصنوعی و نیازهای taxonomy نوشته شد؛ نتایج held-out برای tuning استفاده نشدند. پاسخ باید rationale کوتاه و evidence عیناً موجود داشته باشد. فیلد مفقود، JSON خراب، تناقض، refusal یا پاسخ ناقص به label تبدیل نمی‌شود. intent مبهم با outcome=abstained حفظ می‌شود، نه label چهارم یا out_of_scope پذیرفته‌شده.

## هزینه، recovery و persistence

قیمت از metadata معتبر endpoint خوانده می‌شود؛ unpriced execution وجود ندارد. estimate با proxy صریح UTF-8 bytes/4 و فرض حداکثر output ساخته می‌شود و با usage واقعی اشتباه نمی‌شود. پیش از هر dispatch و retry، reservation کل context/output/request fee با ۵٪ margin نوشته می‌شود. این محافظه‌کاری ممکن است پیش از مصرف واقعی کل بودجه مانع request شود. reported cost، estimate و accounted cost جدا هستند؛ نبود actual cost reservation را آزاد نمی‌کند. کنترل client-side تضمین مطلق no-overspend نیست.

پیش از completion، run/config و hashهای data، source registry، taxonomy، prompt، schema، config، public settings و implementation ذخیره می‌شوند. metadata و زمان retrieval، generation parameters و sample selection در provenance هستند؛ secret یا hash کل key نگهداری نمی‌شود. هر request، reservation و settlement immutable جدا دارد؛ retry، error، token، cost، latency، model/provider و cache origin قابل ردیابی‌اند.

APIهای NexoraDB جدیدی حدس زده نشدند. همان constructor، find_many، insert/delete در transaction و read-after-write تأییدشدهٔ فاز دوم برای entity جدید classification_request_events استفاده شد. قرارداد memory و adapter native، sample/run references، settlement/reservation و تعارض history را کنترل می‌کنند. mock completion با موتور واقعی NexoraDB ذخیره و بازخوانی شد؛ این آزمون موفقیت HTTP واقعی OpenRouter را اثبات نمی‌کند.

journal پیش از dispatch و پیش از checkpoint durable می‌شود. resume پاسخ موفق را از event بازیابی می‌کند حتی اگر checkpoint گم شده باشد. retry با هزینهٔ نامعلوم یا cancellation به --retry-uncertain و مجوز پرداخت نیاز دارد؛ charge قبلی حذف نمی‌شود. مدل/prompt/schema/context یا config ناسازگار اجازهٔ reuse نامناسب نمی‌دهد. کلید dataset همواره sample_id را شامل می‌شود و duplicateها merge نمی‌شوند. فایل CSV دارای کار بازبین بازنویسی نمی‌شود؛ proposal جدید در فایل نسخه‌دار می‌آید. native engine همچنان محدودیت sync=false را دارد.

## اجرای محلی واقعی

dry run بدون credential/model واقعی و بدون درخواست شبکه اجرا شد. تعداد نمونه ۷۱۳ بود. sample selection بیست‌تایی، با seed=20261024: HarmBench validation=6 و StrongREJECT=14 و test=0. proxy strata برابر potential_harm=5، unclear_or_other=12 و potential_discussion_or_pretext=3 است. این‌ها فقط strata نمونه‌گیری‌اند؛ benign یا harmful بودن واقعی ادعا نشده است.

config-check برای placeholder key و model خالی با exit=1 و پیام روشن متوقف شد. preflight و estimate-cost نیز چون model انتخاب نشده بود، قبل از metadata request متوقف شدند. بنابراین قیمت واقعی برای یک مدل انتخاب‌شده، structured generation واقعی، usage واقعی و توزیع LLM واقعی گزارش نشده‌اند. این توقف عمدی جایگزین classification ساختگی نشد. هیچ run با پیشوند pvb-or- در output واقعی پروژه ساخته نشده است.

## نتایج آزمون و دستورها

پس از `uv sync` بدون optional native dependency: **276 passed, 5 skipped**. skipها فقط native integrationهای اختیاری‌اند. پس از `uv sync --extra nexoradb` و اجرای `uv run pytest -v`: **281 passed**، بدون skip/failure. هر ۱۹۸ آزمون baseline همچنان موفق‌اند؛ ۸۳ آزمون جدید به suite استاندارد اضافه شده است. تست live خارج از suite عادی است و اجرا نشده است. Ruff check و format check موفق‌اند.

پوشش جدید شامل dotenv/env precedence، placeholder/مدل/endpoint نامعتبر، metadata و unknown capability، strict schema و فیلدهای مفقود، benign/Self-Harm/ambiguity، عدم source-label leakage، refusal و مدل برگشتی نامنتظره، 429/5xx/authentication، Retry-After/backoff، timeout واقعی task، cancellation، rate/concurrency، usage ناقص، reservation in-flight، retry cost، fingerprint/cache، pilot بدون test، resume/charge نامعلوم، شکست موقت، بازیابی checkpoint، حفظ CSV انسانی، گزارش مجدد، حفظ annotation قواعد و native persistence است. تنظیم pacing در توسعه اصلاح شد تا fsync/DB فاصلهٔ dispatch را مصرف نکند. هیچ خطای تست نهایی باقی نماند.

دستورهای اصلی واقعاً اجراشده:

```bash
uv run pytest -q
uv run python -m pvb.ingestion.validate
uv add 'httpx>=0.28,<1' 'python-dotenv>=1,<2'
uv run ruff check --fix .
uv run ruff format .
uv sync
uv run pytest -v > docs/PHASE3_TEST_RESULTS_BASE.txt
uv sync --extra nexoradb
uv run pytest -v > docs/PHASE3_TEST_RESULTS.txt
uv run ruff check .
uv run ruff format --check .
uv run python -m pvb.extraction.pipeline --backend openrouter --help
uv run python -m pvb.extraction.pipeline --backend openrouter --mode dry-run
uv run python -m pvb.extraction.pipeline --backend openrouter --mode config-check
uv run python -m pvb.extraction.pipeline --backend openrouter --mode preflight
uv run python -m pvb.extraction.pipeline --backend openrouter --mode estimate-cost --selection pilot
git check-ignore .env
```

اسکریپت محلی دیگر SHA256 شش ورودی، schema چهارده‌فیلدی، برابری source/sampleهای NexoraDB با canonical، شمارش و method/status تمام annotationهای قبلی و نبود request event واقعی را assert کرد و execution_verification.json نوشت. کد ساخت `.env` از O_CREAT|O_EXCL و permission 0600 استفاده کرد تا فایل قبلی بازنویسی نشود. دستورات pilot/full/smoke پرداختی در این تحویل اجرا نشدند.

## مرحلهٔ بعد و حدود

کاربر باید `/home/parham/PersianViolenceBench/.env` را باز کند و OPENROUTER_API_KEY و OPENROUTER_MODEL را دستی پر کند؛ کلید نباید در chat ارسال شود. سپس config-check، preflight و estimate-cost را اجرا و فقط با اجازهٔ صریح پرداخت، smoke/pilot را آغاز کند. full نیازمند --confirm-full-run جداست و پس از pilot خودکار اجرا نمی‌شود. دستورهای دقیق در PHASE3_OPENROUTER.md آمده‌اند.

محدودیت‌ها: مدل انتخاب‌شده هنوز remotely verified یا live tested نشده است؛ metadata می‌تواند تغییر کند؛ قیمت ناشناخته و surcharge پشتیبانی‌نشده باعث توقف می‌شود؛ reservation محافظه‌کارانه است؛ API timeout/cancel ممکن است charge نامعلوم بگذارد؛ کنترل هزینه تضمین مطلق ندارد؛ native adapter برای benchmark کوچک snapshotها را در حافظه validate می‌کند و power-loss تضمین نشده است. کیفیت علمی classifier، calibration confidence، review مستقل انسانی، agreement کافی و کنترل محتوایی duplicate leakage هنوز نیازمند کار پژوهشی‌اند. این تحویل زیرساخت محلی آزموده‌شده است، نه نتیجهٔ classification علمی OpenRouter.
