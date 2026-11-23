# Размещение MAX-авторизации на Vercel

Два проекта из одной личной feature-ветки. PR согласуется отдельно.

## Тестовое размещение

- Web: https://medved-web-five.vercel.app
- API: https://medved-api.vercel.app (`/health`).
- Команда Vercel: `xennophrykiryk-7819`; проекты `medved-web` и `medved-api`.
- PostgreSQL: Neon `neon-bronze-marble`, Free, подключён только к API.
- `DEMO_MODE=false`, `VITE_HOST_MODE=max`; Groq включён в live-режиме.

Проверен полный синтетический опрос через опубликованный интерфейс, API, Groq и
Neon, включая сохранение и удаление. Вход для этой проверки подменялся отдельной
короткоживущей синтетической сессией, поэтому это не проверка авторизации MAX.
Для MAX ещё необходимы свежий JWT из запуска кнопки организаторов и origin страницы
их фрейма для CSP. Учебные учётки автоматически не занимались.

Миграции запускаются Build Command через изолированное окружение `uv` Python 3.12.
Зависимости функции берутся из `pyproject.toml`; backend-зависимости обязательны.
Neon URL преобразуется в `postgresql+asyncpg`; сертификат/hostname проверяет SSLContext.
Ключи сессий и шифрования постоянные, хранятся как серверные Secret-переменные.
Локальная резервная копия новых ключей находится только в игнорируемом `.local`.
Никогда не печатайте переменные с ключами или строки подключения в диагностике.

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
на каждом deployment. Вместо файла на Vercel можно задать серверную переменную
`DATA_ENCRYPTION_KEY`: base64-кодированный ключ из 32 случайных байтов.
`DATA_ENCRYPTION_KEY_FILE` в таком случае не задаётся. Если файл задан, он имеет
приоритет. Миграции и приложение должны использовать один и тот же постоянный ключ.
Rate limiter пока использует память процесса и требует распределённой реализации.
Передача HTTPS scheme до ASGI проверена на опубликованном API: `/health` возвращает 200.
API отклоняет HTTP и не доверяет произвольным заголовкам X-Forwarded-Proto.
Реальный MAX проверяется только со свежим JWT из запуска mini-app.
Учебные учётки привязываются к MAX, поэтому не использовать их автоматически.
