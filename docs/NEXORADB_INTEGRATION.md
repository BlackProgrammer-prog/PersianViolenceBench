# پژوهش و اتصال واقعی NexoraDB

در محیط اولیه هیچ بستهٔ NexoraDB نصب نبود. فایل ارائه‌شدهٔ `04_nexoraql_syntax.html` مرجع NexoraQL v1.0.0 بود: Collection، InsertOne/InsertMany، query، update/delete و transaction را توصیف می‌کرد، اما constructor و نام توزیع Python را تعیین نمی‌کرد. متن آن فقط سند فنی بود و دستور اجرایی برای عامل تلقی نشد.

منبع رسمی بسته: [NexoraDataBase 0.2.1 در PyPI](https://pypi.org/project/NexoraDataBase/0.2.1/). نام توزیع `NexoraDataBase`، import برابر `nexoradb` و نسخهٔ نصب‌شده `0.2.1` است. این wheel برای CPython 3.10 و Linux x86_64/glibc>=2.35 منتشر شده است. محیط حاضر Ubuntu با Python 3.10.22 بود. dependency اختیاری با markerهای Python/platform قفل شده است.

کد رسمی release در [commit c599b723b706a9efaf0267cdf1b90ce190cc8e76](https://github.com/BlackProgrammer-prog/NexoraDB/tree/c599b723b706a9efaf0267cdf1b90ce190cc8e76) بررسی شد؛ به‌ویژه bindings/nexoradb_bind.cpp، core/DocEngine.cpp و tests/cpp/test_doc_engine.cpp. HEAD فعلی متفاوت بود و مبنای API adapter قرار نگرفت. docstringها و عملیات binary نصب‌شده مستقلاً بررسی و اجرا شدند. engine پروژهٔ NexoraDB تغییر نکرد.

| عملیات | API تأییدشده در 0.2.1 |
|---|---|
| اتصال embedded | `nexoradb.DocEngine(str(path))` و `is_healthy()` |
| collection | `collection_exists(name)` و `create_collection(name)` |
| درج | `insert_one(collection, json_string)` |
| batch native | `insert_many(collection, list_of_json_strings)` |
| query | `find_by_id(collection, id)` و `find_many(collection, condition, limit, skip)` |
| filtering native | `Condition.leaf(field, Op.EQ, value, ValueType.String)` |
| update native | `UpdateSpec().set(field, value)` و `update_by_id(...)` |
| delete | `delete_by_id(collection, id)` |
| transaction | `begin_transaction()`، `insert_one_tx`، `delete_by_id_tx`، `find_by_id_tx`، `commit_transaction` و `rollback_transaction` |
| نتیجه | `DBResult.success`، `data` و `error_msg` |

درج مجدد `_id` در binary خطای duplicate می‌دهد؛ insert به‌عنوان upsert فرض نشد. adapter پس از اعتبارسنجی کامل با مخزن مرجع، برای سند متغیر از delete+insert در همان transaction استفاده می‌کند. اسناد یکسان اصلاً دوباره نوشته نمی‌شوند. annotation متعارض با ID یکسان رد می‌شود. annotation تاریخی و sample/run references حفظ می‌شوند. برای batch چند entity، insert_one_tx در یک transaction استفاده می‌شود؛ رفتار insert_many نیز جداگانه با engine واقعی تست شده است. `_id` داخلی کنار ID اصلی ذخیره و هنگام خواندن کنترل/حذف می‌شود؛ مدل canonical تغییر نمی‌کند. فیلتر قرارداد repository در حافظه روی مدل‌های خوانده‌شده اعمال می‌شود و از query-string یا سازگاری Mongo/Postgres استفاده نمی‌کند.

چهار collection واقعی: benchmark_sources، benchmark_samples، annotation_runs و sample_annotations. هر mutation پس از commit با خواندن کامل داده کنترل می‌شود. تغییر snapshot که annotation را orphan کند رد می‌شود. مسیر RocksDB باید یک مالک adapter داشته باشد؛ نوشتن مستقیم از engine بیرون از adapter در این قرارداد پشتیبانی نمی‌شود. دادهٔ کوچک فعلی کامل در RAM validate می‌شود؛ برای مقیاس بزرگ نیاز به طراحی snapshot/index/pagination کاراتر است. ایجاد collection خارج از transaction داده انجام می‌شود.

```bash
uv sync --extra nexoradb
uv run --extra nexoradb pytest -v tests/test_nexoradb.py
uv run --extra nexoradb python -m pvb.storage.nexoradb --database data/nexoradb
```

آخرین دستور چهار entity را از canonical و extraction جاری وارد می‌کند. برای runهای قبلی، --extracted را به data/extracted/runs/RUN_ID بدهید. اجرای مجدد idempotent است. دیتابیس local در Git ignore می‌شود و artifactهای JSONL قابل حمل هستند. واحدهای بدون native dependency skip می‌شوند؛ در محیط حاضر native integration واقعاً اجرا شد. آزمون‌ها CRUD، rollback، ingestion تکراری، حفظ تاریخچه و بازیابی پس از خروج process را بررسی می‌کنند.

محدودیت durability: در source همان release، write_options_.sync و BeginTransaction با sync=false تنظیم شده‌اند. آزمون بازگشایی پس از خروج عادی موفق است، اما تضمین دوام در قطع برق یا crash سخت ادعا نمی‌شود. این adapter engine را تغییر نمی‌دهد. مدیریت remote authentication/TLS در این مسیر embedded موضوعیت ندارد؛ برای remote service باید API جداگانه تأیید شود. partial batchهای adapter با transaction کنترل می‌شوند؛ شکست commit خطا می‌دهد و برنامه نباید موفقیت فرض کند. backup، stress/concurrency و crash/power-loss testing هنوز انجام نشده‌اند.
