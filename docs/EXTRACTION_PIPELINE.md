# اجرای استخراج و بازتولید

ورودی پیش‌فرض `data/normalized/benchmark_samples.jsonl` و تنظیمات `configs/extraction.yaml` است. تمام نمونه‌ها با schema فاز اول، hash و uniqueness کنترل می‌شوند؛ taxonomy نیز strict است. prompt و context بررسی می‌شوند. metadata، category و split منبع دست‌نخورده حفظ می‌شوند. schema sample تغییر نکرده است.

```bash
uv sync
uv run python -m pvb.extraction.pipeline --help
uv run python -m pvb.extraction.pipeline --config configs/extraction.yaml --backend rules
uv run python -m pvb.extraction.quality
uv run python -m pvb.extraction.duplicates
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

سه وضعیت نتیجه وجود دارد: classified با annotation معتبر، abstained بدون label، و failed با نام نوع خطا. بدنهٔ خطای provider ذخیره نمی‌شود چون ممکن است دادهٔ حساس داشته باشد. خروجی‌های annotations.jsonl، unsafe_violence.jsonl، benign_violence_related.jsonl، out_of_scope.jsonl، review_queue.jsonl و extraction_report.json تولید می‌شوند. فایل‌های گروهی شامل sample کامل و annotation هستند و ID قابل join دارند. گروه خالی فایل خالی معتبر دارد. `classification_results.jsonl` تمام نمونه‌ها را پوشش می‌دهد؛ `unclassified.jsonl` abstention و failure را نگه می‌دارد. `annotation_runs.jsonl`، quality_report.json و duplicate_report.json نیز تولید می‌شوند.

هر اجرا در `runs/<run_id>/` آرشیو می‌شود و خروجی سطح بالا نمای آخرین اجراست. checkpoint هر نمونه پس از پایان آن atomically نوشته می‌شود. با قطع فرایند، checkpointهای کامل قابل استفاده‌اند؛ batch ناتمام دوباره درخواست می‌شود. resume همان input fingerprint، کد استخراج، taxonomy، prompt و configuration را می‌خواهد:

```bash
uv run python -m pvb.extraction.pipeline --config configs/extraction.yaml --backend rules --resume RUN_ID_FROM_REPORT
```

جای RUN_ID_FROM_REPORT شناسهٔ واقعی report را قرار دهید. checkpointهای موفق تغییر نمی‌کنند؛ فراخوانی failed امکان retry دارد. نویسندهٔ هم‌زمان با lock رد می‌شود. تعویض هر فایل atomic است؛ انتشار تمام artifactها transaction فایل‌سیستمی مشترک ندارد. مصرف‌کننده باید پایان اجرا و status/report را کنترل کند. خروجی نباید روی normalized/raw قرار بگیرد. خروجی مستقل یک run با timestamp واقعی و UUID تازه، byte-identical اجرای جدید نیست؛ تصمیم‌ها و گروه‌بندی با method و input ثابت قطعی‌اند. resume موفق همان اجرا artifactهای یکسان می‌دهد.

## backendها

`rules-1.0.0` قواعد ساختاری محدود انگلیسی دارد: هم‌زمان فرم درخواست، اشارهٔ جسمی و هدف انسانی لازم است. چند زیرگروه مجاز است؛ نام category هیچ نقشی در تصمیم ندارد. این روش درک معنایی کامل، دقت یا recall تأییدشده ندارد. در context پیچیده، نقل‌قول، نفی، زبان پشتیبانی‌نشده یا نبود شواهد کافی abstain می‌کند. ابزار فنی به‌تنهایی هیچ‌وقت unsafe نمی‌شود؛ در مواردی که قاعدهٔ قابل اتکا ندارد، نتیجه unclassified می‌ماند و به انسان ارجاع می‌شود. همهٔ matchها موقت‌اند. confidence قواعد عمداً `0.0` است: backend هیچ اعتماد برآوردشده‌ای به درستی معنایی ادعا نمی‌کند. این عدد احتمال، accuracy یا امتیاز تجربی نیست. تمام نمونه‌ها، از جمله matchها، بازبینی می‌خواهند.

`LLMBackend` اختیاری، transport مستقل و قابل تزریق دارد. transport همراه پروژه یک endpoint با قرارداد chat-completions را می‌پذیرد: JSON شامل model، temperature، messages و response_format=json_schema می‌فرستد و رشتهٔ choices[0].message.content را اعتبارسنجی می‌کند. این به معنی سازگاری با تمام providerها نیست؛ endpoint باید این قرارداد و structured schema را پشتیبانی کند. برای پروتکل دیگر Transport.generate پیاده‌سازی می‌شود. تست‌ها از FakeTransport، MockBackend و سرور HTTP محلی استفاده می‌کنند؛ پاسخ واقعی مدل جعل نمی‌شود.

برای LLM، در config فیلدهای provider، model و endpoint واقعی را تعیین و credential را فقط در متغیر محیطی نام‌برده در credential_env قرار دهید؛ endpoint نباید credential/query/fragment داشته باشد. model_version فقط در صورت اطلاع معتبر پر می‌شود؛ مقدار پیش‌فرض null است. prompt نسخه‌دار در configs/prompts/violence_classifier_v1.txt است. temperature، timeout، retries، requests_per_minute، concurrency و batch_size قابل تنظیم‌اند. cache به متن prompt/context، مدل، provider، taxonomy و configuration وابسته است. پاسخ نامعتبر retry و سپس failure ثبت می‌شود. evidence باید به ورودی قابل ردیابی باشد. خروجی خودکار هیچ‌گاه approved نیست.

```bash
uv run python -m pvb.extraction.pipeline --config configs/extraction.yaml --backend llm
```

بدون تنظیم مدل واقعی، دستور با خطای روشن پایان می‌یابد؛ اجرای LLM واقعی در این تحویل انجام نشده است. تنظیمات با کلیدهای شبیه secret رد می‌شوند؛ مقادیر credential در فایل config قرار ندهید.

## split، duplicates و QC

HarmBench validation برای توسعه و test برای اجرای روش frozen است. کد قواعد و prompt پیش از اولین اجرای test تثبیت شدند و بر اساس labelهای test تنظیم نشدند. method_frozen باید برای ورودی شامل test برابر true باشد. fingerprint روش در هر run ثبت می‌شود. StrongREJECT همان unspecified است و split ساختگی ندارد. برای هر تغییر علمی آینده، توسعه روی validation انجام و نسخهٔ روش تازه منتشر شود؛ خروجی test حاضر نباید مبنای tuning همان ارزیابی قرار گیرد.

duplicateها با prompt_sha256 و نیز key جداگانهٔ NFKC/whitespace/casefold بررسی می‌شوند. تنظیم‌ها با --unicode-form، --keep-case و --keep-whitespace قابل تغییرند. برابری متن normalizeشده معادل برابری byte یا context نیست. هیچ نمونه‌ای merge/delete نمی‌شود؛ semantic similarity پیاده‌سازی نشده است. cross-source و cross-split گزارش می‌شوند. گروه‌های عبوری validation/test باید پیش از ارزیابی علمی با سیاست ثابت کنترل شوند.

QC فقدان تصمیمِ بدون توضیح، ID ناشناس/تکراری، schema و taxonomy نامعتبر، rationale/evidence، context لازم، منشأ run، وضعیت review و ارجاعات adjudication را کنترل می‌کند. abstentionهای صریح هشدار پژوهشی دارند و حذف بی‌صدا نیستند. موفقیت نرم‌افزاری QC به معنی کامل بودن annotation علمی نیست. توزیع موقت براساس dataset، category اصلی، split، label، زیرگروه، review status و method گزارش می‌شود. برای دادهٔ فعلی هیچ ground truth انسانی تأییدشده وجود ندارد.
