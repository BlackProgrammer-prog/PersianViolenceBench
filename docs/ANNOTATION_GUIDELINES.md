# راهنمای annotation و بازبینی انسانی

`BenchmarkSample` همان ۱۴ فیلد فاز اول را دارد. `SampleAnnotation` جداگانه، شامل فیلدهای label، subcategories، intent، target، actionability، risk_severity، confidence، rationale، evidence، requires_human_review، review_status، annotation_method، annotator_id، annotation_run_id، شناسه و نسخهٔ taxonomy، created_at و updated_at است. همهٔ زمان‌ها ISO 8601 با UTC هستند؛ timezone محلی یا زمان بدون timezone پذیرفته نمی‌شود. schema strict است؛ فیلد ناشناخته، confidence نامعتبر/NaN، rationale خالی، زیرگروه تکراری و ترکیب ناسازگار رد می‌شود.

unsafe نیازمند intent=harmful، target=other_person یا group و حداقل یک زیرگروه است. labelهای دیگر زیرگروه خالی دارند. intent مبهم نیازمند review است. تمام annotationهای خودکار در pending می‌مانند. تأیید انسانی، attempt جدید با method=human است و سابقه را تغییر نمی‌دهد. `supersedes_annotation_id` به پیشنهاد قبلی و `adjudicates` به حداقل دو attempt مورد داوری اشاره می‌کند. مخزن وجود sample، run و ارجاعات تاریخچه را کنترل می‌کند. attempt ID از run، sample و annotator ساخته می‌شود؛ اجرای تازه run ID مستقل دارد. نهایی بودن فقط با انتخاب صریح یک attempt انسانی تأییدشده یا adjudication در تحلیل پایین‌دستی معنا دارد؛ سامانه به‌طور خودکار آخرین attempt را ground truth اعلام نمی‌کند.

CSV اولیه تمام ۷۱۳ نمونه، از جمله abstentionها، را دارد:

```bash
uv run python -m pvb.extraction.review export --csv data/review_round1.csv
uv run python -m pvb.extraction.review export --csv data/independent_A.csv --independent
```

برای هر ردیف تکمیل‌شده، reviewer_label، reviewer_subcategories با جداکنندهٔ `|`، reviewer_intent، reviewer_target، reviewer_actionability، reviewer_risk_severity، reviewer_rationale، reviewer_confidence، reviewer_id و review_status را پر کنید. reviewer_notes اختیاری است؛ reviewer_overlapping_risks برای `self_harm` است. ستون‌های original_prompt و original_context نباید تغییر کنند. ردیف بدون label فقط با pending پذیرفته و وارد annotationهای کامل نمی‌شود. بدون هویت بازبین یا یک dimension لازم، import رد می‌شود؛ سامانه مقادیر انسانی را حدس نمی‌زند.

```bash
uv run python -m pvb.extraction.review import --csv data/independent_A.csv --reviewer-id reviewer-A --output data/reviews
```

خروجی در `data/reviews/pvb-human-.../`، همراه run metadata ایجاد می‌شود. import مجدد همان فایل در همان مسیر رد می‌شود تا تاریخچه بازنویسی نشود. فایل اصلی CSV را به‌عنوان سند بازبینی نگه دارید. نمونه‌های پیشنهادی در `--independent` پنهان می‌شوند تا بازبین مستقل باشد. برای adjudication، شناسهٔ attemptهای اختلاف‌دار را در ستون adjudicates با `|` ثبت کنید؛ فایل annotations ورودی باید ارجاعات آن‌ها را نیز داشته باشد.

برای دو بازبین مستقل، فایل annotationهایشان را پس از کنترل uniqueness کنار هم قرار دهید:

```bash
uv run python -m pvb.extraction.agreement --annotations data/reviews/combined.jsonl --annotator-a reviewer-A --annotator-b reviewer-B --output data/reviews/agreement.json
```

تنها attemptهای انسانی approved، مستقل و بدون supersedes/adjudicates وارد agreement می‌شوند. چند attempt از یک بازبین برای یک sample باید پیش از محاسبه انتخاب شوند؛ انتخاب خودکار انجام نمی‌شود. کمتر از دو جفت یا marginals ثابت، kappa برابر null می‌دهد. برای labelها Cohen’s kappa و برای هر V1–V5، kappa دودویی مستقل محاسبه می‌شود. این‌ها یک امتیاز واحد multi-label نیستند؛ فراوانی کلاس و اندازهٔ نمونه بر آن‌ها اثر دارد. اختلاف label یا مجموعهٔ زیرگروه‌ها در disagreement_sample_ids ثبت می‌شود. هنوز review واقعی یا agreement علمی برای دادهٔ موجود انجام نشده است.
