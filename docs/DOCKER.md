# Запуск всего проекта в Docker

Логи контейнеров, сопоставление запросов и проверка режима Groq:
[Диагностика](LOGGING.md).

Из корня репозитория, при запущенном Docker Desktop с Linux-контейнерами:

```powershell
docker compose up --build -d
```

Открыть **https://localhost:8443**. Проверить готовность: `docker compose ps`.
При первом запуске скачиваются образы, устанавливаются зависимости, создаются ключи и сертификаты, применяются миграции. Python, Node.js и PostgreSQL на компьютере не требуются.

Это локальный запуск с настоящими API и PostgreSQL. Demo-авторизация включена, NLP использует mock, данные должны быть вымышленными. Интерфейс отправляет ответы API; автономный frontend mock здесь не используется.

## Локальный сертификат

Первый запуск создаёт собственный CA. Браузеру нужно доверие к нему. Скопировать только публичный сертификат:

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
docker compose cp web:/run/web-secrets/ca.crt .local/docker-ca.crt
curl.exe --cacert .local/docker-ca.crt https://localhost:8443/health
```

Для Windows можно вручную установить этот CA в хранилище текущего пользователя:

```powershell
Import-Certificate -FilePath .local/docker-ca.crt -CertStoreLocation Cert:\CurrentUser\Root
```

Установка доверия не выполняется автоматически. Сертификаты сервера действуют 30 дней. Для размещения на сервере нужны сертификаты настоящего домена и настройка доступа; текущий порт привязан только к localhost.

## Состав

- `apps/api/Dockerfile` — FastAPI, запуск HTTPS и автоматические миграции Alembic.
- `apps/api/postgres/Dockerfile` — PostgreSQL 16 с обязательным TLS для сетевых подключений.
- `apps/web/Dockerfile` — сборка React и Nginx, HTTPS и проксирование API с проверкой сертификата.
- `compose.yaml` в корне — общий запуск. Dockerfile собирает один образ; Compose управляет несколькими контейнерами.
- Одноразовый сервис `init` создаёт секреты только на новых томах. При повторном запуске ключи и пароль сохраняются.

База не публикует порт на компьютере. API доступен через Nginx по тому же origin, что и frontend. HTTPS используется между браузером и Nginx, Nginx и API, API и PostgreSQL. JSON в БД продолжает шифроваться приложением.

У каждого сервиса отдельный том секретов. Frontend получает только TLS-сертификат, ключ HTTPS и публичный CA; контейнер БД — свою TLS-пару и пароль. Ключ шифрования JSON и ключ подписи остаются у API. Файлы `.env`, локальные ключи, дампы, тесты и скриншоты не включаются в образы.

## Настройки

По умолчанию всё запускается без `.env`. Для изменения параметров скопировать корневой `.env.example` в `.env`. Например, другой внешний HTTPS-порт:

```dotenv
WEB_HTTPS_PORT=9443
```

Для настоящего запуска MAX: `DEMO_MODE=false`, `VITE_HOST_MODE=max` и действительный `CORE_SERVICE_TOKEN`; для Groq: `NLP_MODE=live`, `GROQ_API_KEY` и `GROQ_MODEL`. После изменения режима frontend нужна пересборка: `docker compose up --build -d`. Секреты не передаются через build args и не попадают в JavaScript.

Исходная локальная БД проекта `medved_local` и файлы `.local/runtime` не используются и не изменяются. Новый стек имеет собственные тома. Для переноса прежних данных нужны дамп и соответствующий прежний ключ шифрования; простого копирования записей недостаточно.

## Управление

```powershell
docker compose ps
docker compose logs --tail=100 api postgres web
docker compose stop
docker compose up -d
docker compose down
```

Обычный `down` сохраняет тома базы и ключей. Не добавляйте `-v`, если данные нужны. Для восстановления нужны и данные PostgreSQL, и прежний том `api-secrets`: потеря ключа делает зашифрованные JSON недоступными.

Просмотреть таблицы:

```powershell
docker compose exec postgres psql -U medved -d medved -c "\dt"
```

Миграции выполняются перед каждым запуском API; ошибка миграции останавливает API. Готовность PostgreSQL и API проверяется до старта зависимых сервисов.

## Ключи агента чата

Compose читает необязательный `apps/api/.env`, затем корневой `.env` (он имеет приоритет). `NLP_MODE=mock` включает локальные ответы чата. Для Groq укажите на сервере `NLP_MODE=live`, `GROQ_API_KEY` и `GROQ_MODEL`. После изменения пересоздайте API командой `docker compose up -d --force-recreate api`. При отсутствии ключа или недоступности провайдера в режиме `live` интерфейс предложит повторить отправку. Содержимое `.env` не включается в Docker-образ.
