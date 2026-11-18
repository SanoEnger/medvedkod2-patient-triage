# Размещение MAX-авторизации на Vercel

Два проекта из одной личной feature-ветки. PR согласуется отдельно.

1. Backend: Root Directory `apps/api`, framework Other. Серверные переменные:
   `CORE_URL=https://tm-test-yakut.hostco.ru`, `CORE_SERVICE_TOKEN` (секрет команды),
   `SESSION_SIGNING_KEY` (отдельный случайный секрет от 32 символов), `DEMO_MODE=false`.
   `CORS_ORIGINS` — точный HTTPS origin frontend без завершающего слеша.
2. Frontend: Root Directory `apps/web`, Vite. `VITE_API_ORIGIN` — HTTPS origin
   backend, `VITE_HOST_MODE=max`. Секрет команды никогда не задаётся через VITE_*.
3. Сначала проверить preview выбранной личной ветки. Не переключать production на main.
4. После получения origin фрейма организаторов добавить его в `frame-ancestors`
   в `apps/web/vercel.json`. Пока задано только `'self'`: внешнее встраивание
   закрыто до получения адреса. Не добавлять X-Frame-Options DENY.
5. Deployment Protection не должна блокировать пользователей MAX и запросы frontend
   к backend. После проверки передать организаторам публичный URL frontend без token.

Frontend удаляет token из URL, один раз отправляет его в `/api/v1/auth/launch`.
Собственный access token сохраняется только в памяти. JWT имеет приоритет над demo.
После отказа входа нужно открыть приложение заново из MAX; истёкший JWT не повторяется.
URL приходит на хостинг до JavaScript: исключить query string из инфраструктурных
логов и аналитики. History API не удаляет уже записанный URL из серверных логов.

## Ограничения

SessionService использует PostgreSQL с проверяемым TLS и AES-шифрованием состояния,
включая NLP и ревизии. Для размещения нужны DATABASE_URL, DATABASE_SSL_CA_FILE
(если CA не системный) и DATA_ENCRYPTION_KEY_FILE с доступным серверу ключом.
Миграции Alembic выполняются до запуска. Ключ шифрования нельзя генерировать заново
на каждом deployment. Размещение файла секрета на Vercel ещё требует проверки.
Rate limiter пока использует память процесса и требует распределённой реализации.
На платформе нужно проверить передачу HTTPS scheme до ASGI: API отклоняет HTTP,
произвольным заголовкам X-Forwarded-Proto не доверяет. Публикация пока не выполнялась.
Реальный MAX проверяется только со свежим JWT из запуска mini-app.
Учебные учётки привязываются к MAX, поэтому не использовать их автоматически.
