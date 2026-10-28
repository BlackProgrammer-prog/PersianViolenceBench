# adapter تأییدشدهٔ NexoraDB

فاز دوم، `NexoraRepository` را با API واقعی `NexoraDataBase==0.2.1` اضافه می‌کند. قراردادهای فاز اول و `InMemoryRepository` حفظ شده‌اند؛ schema چهارده‌فیلدی تغییر نکرده است.

پژوهش نسخه، API، read-after-write واقعی، transaction، idempotency، محدودیت sync=false و دستورهای اجرا در [NEXORADB_INTEGRATION.md](../../../../docs/NEXORADB_INTEGRATION.md) مستند شده‌اند. منبع مستندات HTML فقط برای شناخت syntax استفاده شد؛ API Python از release و binary نصب‌شده تأیید شد. نصب اختیاری با `uv sync --extra nexoradb` انجام می‌شود؛ dependency پایه به engine نیاز ندارد.
