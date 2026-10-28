# گزارش پیاده‌سازی و اجرای فاز دوم PersianViolenceBench

تاریخ تحویل: ۲۰۲۶-۱۰-۲۴. کار مستقیماً در مخزن انجام شد. ابتدا pyproject، configها، schemaها، adapterها، storage contractها، آزمون‌ها، گزارش فاز اول و سند محلی NexoraQL خوانده شدند. baseline واقعاً ۱۰۴ آزمون موفق و ۷۱۳ نمونه با سه source registry داشت. هیچ نمونهٔ raw یا normalized تغییر نکرد و schema اصلی همان ۱۴ فیلد است.

## خروجی واقعی و حدود اعتبار

| نتیجه در اجرای نهایی | شمارش |
|---|---:|
| نمونهٔ ورودی | 713 |
| annotation موقت unsafe_violence | 5 |
| annotation benign_violence_related | 0 |
| annotation out_of_scope | 0 |
| abstention / بدون classification | 708 |
| خطای پردازش | 0 |
| صف بازبینی انسانی | 713 |
| عدم اطمینان، شامل confidence صفر قواعد | 713 |
| annotation انسانی approved | 0 |

شناسهٔ اجرای نهایی `pvb-run-d21db14f7fb6420b90035e941707769f` است. پوشش موقت قواعد `5/713`، حدود `0.70%` است. هر پنج annotation با method=rule_based، review_status=pending و confidence=0.0 ثبت شده‌اند؛ backend اعتماد معنایی برآوردشده‌ای ادعا نمی‌کند. این عدد امتیاز ساختگی accuracy یا احتمال کالیبره‌شده نیست. آن ۷۰۸ مورد به‌هیچ‌وجه out_of_scope نامیده نشده‌اند؛ label نامعلوم در unclassified نگه داشته شده است. فایل‌های benign و out_of_scope خالی‌اند، چون قواعد در دادهٔ واقعی هیچ تصمیمی در آن دو گروه نداده‌اند؛ پشتیبانی نرم‌افزاری آن‌ها با fixture آزموده شد.

دو annotation از HarmBench test و سه annotation از StrongREJECT unspecified هستند. categoryهای اصلی این پنج مورد: illegal=2، Violence=2، Disinformation and deception=1. بنابراین انتخاب براساس category Violence انجام نشده است. فراوانی زیرگروه‌ها V3=1، V4=5 و V5=2 است؛ جمع زیرگروه‌ها نباید با شمارش نمونه یکسان فرض شود. V1/V2 در آزمون‌های مصنوعی پوشش دارند اما در اجرای محدود قواعد match واقعی نداشتند. هیچ tuning براساس نتیجهٔ held-out انجام نشد.

گزارش کیفیت از نظر نرم‌افزاری passed و errors خالی است؛ هشدار صریح برای ۷۰۸ unclassified و ۵ annotation موقت دارد. ground_truth=false است. درخواست‌های test برای تحلیل دستی یا تنظیم قواعد خوانده نشدند؛ فقط شمارش‌ها و گزارش‌های integrity بررسی شدند. گذر آزمون نرم‌افزاری به معنی اعتبار علمی taxonomy یا classifier نیست.

## فایل‌های ایجاد و اصلاح‌شده

- `configs/taxonomy.yaml` از placeholder به taxonomy رسمی تبدیل شد؛ `configs/extraction.yaml` و `configs/prompts/violence_classifier_v1.txt` اضافه شدند.
- `src/pvb/schemas/annotations.py` و `annotation_runs.py`: مدل‌های مستقل strict، validation، timestamp و منشأ.
- `src/pvb/extraction/{__init__,config,io,taxonomy,rules,pipeline,duplicates,quality,review,agreement}.py` و `backends/{__init__,base,rule_based,llm,mock}.py`: pipeline، abstention، backendها، cache، checkpoint، review و گزارش‌ها.
- `src/pvb/storage/contracts.py` و `memory.py`: قراردادهای annotation/run، نگهداری attemptها و جلوگیری از orphan شدن تاریخچه.
- `src/pvb/storage/nexoradb/{__init__,repository,__main__}.py` و README: adapter واقعی نسخهٔ تأییدشده و CLI persistence.
- `tests/{test_phase2_schemas,test_taxonomy,test_extraction,test_duplicates,test_review,test_quality,test_llm,test_nexoradb}.py` و `tests/conftest.py`: آزمون‌های جدید و fixtureهای غیرعملیاتی.
- `pyproject.toml` و `uv.lock`: dependency اختیاری pinned برای NexoraDB با platform marker؛ وابستگی پایه به آن نیاز ندارد.
- `README.md`، `.gitignore`، `docs/IMPLEMENTATION_REPORT.md` و چهار سند راهنمای فارسی به‌روزرسانی/اضافه شدند. این گزارش و `docs/PHASE2_TEST_RESULTS.txt` نتیجهٔ واقعی اجرا را نگه می‌دارند.
- `data/extracted/`: annotationها، سه گروه label، صف و CSV انسانی، classification_results، unclassified، annotation_runs، quality/extraction/duplicate report، execution_verification و آرشیو runها/checkpointها/attemptها/run_events.
- `data/nexoradb/`: دیتابیس embedded واقعی، خارج از Git. چهار entity خوانده و تأیید شدند.

فایل HTML ارائه‌شده، کد engine NexoraDB و فایل‌های source/raw/normalized تغییر داده نشدند. آزمون‌ها و pipeline فاز اول حفظ شدند.

## schema، backend و provenance

Taxonomy با شناسهٔ pvb-violence، نسخهٔ 1.0.0، سه label و پنج زیرگروه multi-label اعتبارسنجی می‌شود. مدل annotation همهٔ dimensionهای خواسته‌شده و ارجاعات supersedes/adjudicates را دارد. run، configuration، fingerprint ورودی و کد، taxonomy/prompt hash، method، model/provider/version در صورت اطلاع، شمارش‌ها و زمان واقعی را ثبت می‌کند. UUID هر اجرای تازه مستقل است؛ attempt ID درون run قطعی است و conflict تاریخی رد می‌شود.

backend قواعد عمداً بسیار محدود است و جای classifier معنایی را نمی‌گیرد. همهٔ نمونه‌ها خوانده می‌شوند و context وارد predicateها می‌شود؛ ابهام و فرم‌های پشتیبانی‌نشده abstain می‌شوند. backend LLM transport مستقل با endpoint قابل تنظیم، JSON schema، prompt version، temperature/timeout/retry، rate limit، concurrency، batch و cache پیاده‌سازی شد. تست‌ها بدون API key و با mock و HTTP محلی اجرا شدند. مدل واقعی تنظیم نبود؛ دستور LLM با خطای روشن پایان یافت و هیچ label منتسب به مدل واقعی تولید نشد. model_version/provider ساختگی ثبت نشد.

review CSV همهٔ نمونه‌ها را پوشش می‌دهد. import تمام dimensionهای انسانی، هویت، متن canonical و referenceها را کنترل می‌کند؛ annotation تازه تولید و پیشنهاد قبلی حفظ می‌شود. workflow مستقل، تشخیص اختلاف، adjudication و kappa دو بازبین/زیرگروه پیاده‌سازی و با fixture تست شد. برای دادهٔ واقعی هنوز review انسانی یا agreement محاسبه نشده است.

## duplicates و leakage

۵ گروه exact با ۱۲ رکورد پیدا شد؛ normalized-text نیز ۵ گروه و ۱۲ رکورد دارد. cross-source group برابر صفر و cross-split group برابر ۲ است. متن‌های اصلی تغییر نکرده‌اند؛ تشابه معنایی به‌عنوان برابری گزارش نشده است. هیچ merge/delete صورت نگرفت. تکرارهای validation/test نیازمند سیاست ثابت کنترل leakage در ارزیابی بعدی هستند. HarmBench validation/test و StrongREJECT unspecified حفظ شدند. method_frozen=true پیش از اجرای کامل تنظیم بود؛ قواعد و prompt براساس خروجی test بازتنظیم نشدند.

## NexoraDB: پژوهش و نتیجهٔ واقعی

توزیع رسمی [NexoraDataBase 0.2.1](https://pypi.org/project/NexoraDataBase/0.2.1/) و [source همان release](https://github.com/BlackProgrammer-prog/NexoraDB/tree/c599b723b706a9efaf0267cdf1b90ce190cc8e76) بررسی شدند. نام import nexoradb و constructor DocEngine(path) در binary نصب‌شده تأیید شدند. syntax MongoDB یا PostgreSQL فرض نشد. duplicate _id خطا می‌دهد؛ upsert معادل با delete/insert در transaction پیاده شد. collection، insert/batch، filtering، update/delete، transaction، rollback، خطا و persistence با engine واقعی آزموده شدند.

درج واقعیِ اجرای نهایی دو بار انجام و پس از خروج فرایند بازخوانی شد: ۳ source، ۷۱۳ sample، ۲ run و ۱۰ annotation تاریخی در دیتابیس وجود دارد. این ۱۰ annotation از دو اجرای مستقلِ پنج‌تایی‌اند؛ ۱۰ نمونهٔ متمایز یا ground truth نیستند. اجرای دوبارهٔ همان run هیچ رکورد تازه‌ای نساخت. مقایسهٔ کامل مدل‌ها، metadata، null، Unicode و همهٔ annotationهای آرشیو موفق بود. شواهد machine-readable در data/extracted/execution_verification.json است.

engine با sync=false کار می‌کند. بازیابی پس از خروج عادی آزمایش شد؛ durability هنگام قطع برق/crash سخت، remote API، backup و بار هم‌زمان ادعا نمی‌شود. adapter برای اندازهٔ فعلی داده طراحی شده و هر snapshot را برای validation در RAM می‌خواند. جزئیات در NEXORADB_INTEGRATION.md است.

## بازتولید و حفاظت داده

resume اجرای نهایی برای تمام artifactهای JSON/JSONL سطح بالا byte-identical بود. تصمیم‌های دو اجرای مستقل با حذف ID، timestamp و provenance نیز یکسان بودند. checkpointهای موفق دوباره اجرا نشدند؛ آزمون resume پس از failure نشان داد فقط مورد failed retry می‌شود و attempt و run-event قبلی باقی می‌مانند. UUID/timestamp واقعی باعث می‌شود دو اجرای تازه لزوماً byte-identical نباشند؛ این تفاوت مستند است.

SHA256 هر شش فایل ورودی با baseline برابر ماند. نمونهٔ اصلی JSONL همچنان `f4b8efaf22ab7950bc72a595f4044d9369d3de10235c8d6a0d38fcd7a8595b29` است. hashهای کامل CSV، source registry و سه raw در execution_verification.json ثبت شده‌اند. validate فاز اول نیز تطبیق ۷۱۳ نمونه و سه source را با raw تأیید کرد.

## آزمون‌ها و دستورهای واقعاً اجراشده

اجرای نهایی `uv run pytest -v`: **198 passed**، شامل آزمون‌های native، بدون skip یا failure. گزارش کامل در PHASE2_TEST_RESULTS.txt است. Ruff check و format check موفق‌اند. آزمون‌های نسخهٔ نهایی موارد مرزی taxonomy/schema، هر V1–V5، benign history/education/prevention/journalism، Self-Harm-only، سلاح بدون هدف، ابهام، context، multi-label، duplicate، review/adjudication/agreement، mock/HTTP/timeout/retry/concurrency/cache، resume/failure، حفاظت داده، قرارداد memory و NexoraDB را می‌پوشانند. خطای timeout مربوط به Python 3.10 در توسعه پیدا و اصلاح شد؛ نتیجهٔ نهایی بدون failure است.

دستورهای اصلی اجراشده؛ placeholder انتهایی شناسهٔ run را در مثال راهنما مشخص می‌کند، ولی دستور resume واقعی از API Python در همان config و با run ID گزارش فراخوانی شد:

```bash
uv run pytest -q
uv run python -m pvb.ingestion.validate
uv pip list
uv pip install 'NexoraDataBase==0.2.1'
git clone --depth 1 https://github.com/BlackProgrammer-prog/NexoraDB.git /tmp/pvb-nexoradb-research
git -C /tmp/pvb-nexoradb-research fetch --depth 1 origin c599b723b706a9efaf0267cdf1b90ce190cc8e76
git -C /tmp/pvb-nexoradb-research checkout --detach c599b723b706a9efaf0267cdf1b90ce190cc8e76
uv add --optional nexoradb 'NexoraDataBase==0.2.1; python_version < "3.11" and sys_platform == "linux" and platform_machine == "x86_64"'
uv run --extra nexoradb pytest -q
uv run pytest -v > docs/PHASE2_TEST_RESULTS.txt
uv run ruff check .
uv run ruff format --check .
uv run python -m pvb.extraction.pipeline --help
uv run --extra nexoradb python -m pvb.extraction.pipeline --config configs/extraction.yaml --backend rules
uv run python -m pvb.extraction.pipeline --backend llm
uv run python -m pvb.extraction.quality
uv run python -m pvb.extraction.duplicates
uv run --extra nexoradb python -m pvb.extraction.review export --csv data/extracted/human_review.csv
uv run --extra nexoradb python -m pvb.storage.nexoradb --database data/nexoradb
```

علاوه بر این‌ها، Ruff با --fix و formatter در توسعه اجرا شد؛ تبدیل dict literalها با --unsafe-fixes صرفاً در tests انجام شد. اسکریپت‌های Python محلی API نصب‌شده را introspect کردند، عملیات native را probe کردند، resume و برابری تصمیم‌ها را assert کردند، CSV نهایی را از artifact نهایی ساختند و hash/خواندن مجدد دیتابیس را بررسی کردند. دستور LLM عمداً exit=1 داشت چون provider/model/endpoint واقعی تنظیم نبود؛ این شکست با طبقه‌بندی ساختگی جایگزین نشد.

## کار علمی باقی‌مانده

برای ادعای benchmark معتبر، باید annotation مستقل انسانی توسط متخصصان، adjudication، اندازه‌گیری توافق روی تعداد کافی، ارزیابی precision/recall و خطاهای روش روی development جدا، پوشش زبان و ظرایف فارسی، کنترل duplicate leakage، مستندسازی split و روش frozen، و در صورت استفاده calibration اعتماد انجام شود. coverage پایین قواعد محدودیت آشکار این تحویل است؛ هیچ ادعایی دربارهٔ قابل اتکا بودن classification نهایی همهٔ ۷۱۳ نمونه وجود ندارد.
