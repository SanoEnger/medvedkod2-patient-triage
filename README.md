# МедВед — навигатор пациента

Хакатонный проект команды **Signalary**: предварительный опрос пациента, анализ ответов с Groq, помощь с выбором специалиста и поиск медицинских учреждений Кургана.

Это учебный прототип. Он не ставит диагноз и не заменяет врача; для демонстрации используйте вымышленные данные.

## Возможности

- Опрос из пяти шагов с возвратом к ответам и сохранением результата.
- Проверка критических признаков, включая свободный текст на промежуточных шагах. При срабатывании — экстренная остановка с причиной и номерами экстренных служб.
- Анализ завершённой анкеты и чат с МедВедом через Groq; ответы проходят серверную проверку.
- История обращений и чатов с удалением пользователем. Срок хранения обращения ограничен 24 часами.
- Поиск клиник по адресу, координатам, специальности, возрастной группе и способу оплаты; карта Яндекса с резервной подложкой OpenStreetMap.
- Переход к внешнему сервису записи или звонку в клинику. Подтверждение записи происходит во внешнем сервисе.
- Голосовой ввод с добавлением распознанного текста в черновик; версия для слабовидящих.

## Команда

| Участник | Направление |
| --- | --- |
| Волосников Александр | Fullstack и ML |
| Вахрушев Александр | Backend |
| Смирнов Глеб | Frontend и SQL |

## Устройство проекта

| Путь | Содержимое |
| --- | --- |
| `apps/web` | React 19, TypeScript, Vite, Leaflet |
| `apps/api/app` | FastAPI, авторизация MAX, опрос, чат, Groq, каталог клиник |
| `apps/api/alembic` | Миграции PostgreSQL и версии правил безопасности |
| `apps/api/clinic_catalog` | Адресный набор Кургана и запрос для его обновления |
| `apps/api/tests`, `apps/web/tests` | Автоматические проверки и тестовые данные |
| `compose.yaml` | Локальный стек: Nginx, API, PostgreSQL и подготовка секретов |
| `docs` | Подробности [логирования](docs/LOGGING.md) и [защиты LLM](docs/PROMPT_SECURITY.md) |

## Локальный запуск в Docker

Нужны Docker Desktop с Linux-контейнерами и Docker Compose. Из корня проекта:

```powershell
docker compose up --build -d --wait
docker compose ps
```

Откройте **https://localhost:8443**. При первом запуске создаются ключи, локальные TLS-сертификаты и таблицы БД. По умолчанию включены учебная авторизация и mock-режим NLP. Python, Node.js и PostgreSQL на компьютере для этого запуска не требуются.

Для доверия локальному сертификату скопируйте публичный CA:

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
docker compose cp web:/run/web-secrets/ca.crt .local/docker-ca.crt
curl.exe --cacert .local/docker-ca.crt https://localhost:8443/health
```

В Windows при необходимости установите его для текущего пользователя:

```powershell
Import-Certificate -FilePath .local/docker-ca.crt -CertStoreLocation Cert:\CurrentUser\Root
```

Это локальный CA, не сертификат публичного сайта. Приватные ключи остаются в Docker-томах. Сертификаты локальных сервисов действуют 30 дней.

Для изменения параметров скопируйте корневой `.env.example` в `.env`. Он предназначен для Compose: внешний порт, режимы приложения, Groq и публичный ключ карты. Дополнительные серверные настройки можно хранить в `apps/api/.env`; корневой `.env` имеет приоритет при запуске общего стека. Реальные значения в Git не добавляются.

```powershell
docker compose logs --since 10m --tail 100 api web postgres
docker compose stop
docker compose up -d
```

`docker compose down` сохраняет тома. Ключ шифрования API нужно сохранять вместе с резервной копией БД: без него зашифрованные данные не восстановить. Параметр `-v` удаляет тома, поэтому для обычной остановки его не используйте.

## Groq и голосовой ввод

Для ответов модели задайте на сервере `NLP_MODE=live`, `GROQ_API_KEY` и `GROQ_MODEL`. Выберите модель с поддержкой JSON-ответов; на текущем размещении используется `openai/gpt-oss-120b`. `NLP_MODE=mock` позволяет работать без обращения к провайдеру.

Для облачного распознавания речи используются `VOICE_PROVIDER=groq` и `GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo`; ключ Groq хранится только у API. Аудио передаётся провайдеру для распознавания, в БД не сохраняется.

Для локального Whisper сначала скачайте модель, затем включите `INSTALL_VOICE=1` в корневом `.env` и пересоберите Docker-стек:

```powershell
python -m pip install -r apps/api/requirements-voice.txt
python -c "from faster_whisper.utils import download_model; download_model('base', output_dir='.local/models/whisper-base')"
docker compose up --build -d
```

Микрофон требует HTTPS и разрешения пользователя. Во вложенном mini-app MAX также нужно делегирование доступа со стороны родительских окон. Работа записи внутри MAX пока не подтверждена; при отказе интерфейс показывает «Микрофон недоступен.».

## Каталог клиник и адресов

Карта читает данные из PostgreSQL. Обновление Git или публикация Vercel не переносят содержимое локальной БД. В облачный каталог 26 ноября 2026 года загружены 8 131 адрес, 18 организаций и 41 филиал, а также условия оплаты и источники данных.

На новой базе после запуска стека загрузите адресный справочник и открытые данные «Поликлиники45»:

```powershell
docker compose exec api python -m app.container import-clinic-addresses /app/clinic_catalog/kurgan-osm.json.gz
docker compose exec api python -m app.container import-poliklinika45 --live --report /tmp/poliklinika45-report.json
```

Живой импорт не восстанавливает все вручную проверенные клиники и условия оплаты. Для точной копии рабочего каталога нужна его резервная копия. Сохранить только таблицы карты из существующей локальной БД:

```powershell
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only --no-owner --no-privileges --table="public.clinic_*" --file=/tmp/clinic-catalog.sql'
docker compose cp postgres:/tmp/clinic-catalog.sql .local/clinic-catalog.sql
```

Перед переносом проверяйте структуру и содержимое выгрузки, используйте транзакцию и не перезаписывайте конфликтующие данные рабочей БД. Секреты и истории пациентов для переноса справочника не нужны.

Для поиска подойдёт адрес «Курган, ул. Кравченко, 53». Для проверки платного приёма можно выбрать «Дерматолог» рядом с Советской, 119. В карточках указаны источники; способы оплаты и доступность записи уточняются в клинике.

Публичный ключ `VITE_YANDEX_TILES_API_KEY` задаётся перед сборкой frontend: в корневом `.env` для Compose, `apps/web/.env.local` для Vite или окружении проекта `medved-web` на Vercel. Ключ доступен браузеру; ограничьте его доменами сайта в кабинете Яндекса. Без него используется OpenStreetMap.

Для обновления адресов сохранены [Overpass-запрос](apps/api/clinic_catalog/kurgan.overpassql) и модуль `app.db.export_kurgan_addresses` для выгрузок Geofabrik. Данные OpenStreetMap требуют [атрибуции и соблюдения ODbL](https://www.openstreetmap.org/copyright). Импорт «Поликлиники45» поддерживает `--collect-only`, `--snapshot-out` и проверку набора до записи; параметры доступны через `python -m app.db.import_poliklinika45 --help` из `apps/api`.

## MAX и размещение

| Компонент | Размещение |
| --- | --- |
| [Сайт](https://medved-web-five.vercel.app) | Vercel, проект `medved-web`, Root Directory `apps/web` |
| [API / health](https://medved-api.vercel.app/health) | Vercel, проект `medved-api`, Root Directory `apps/api` |
| PostgreSQL | Neon |
| Relay авторизации | Cloud.ru Container Apps, модуль `apps/api/app/core_relay.py` |

Production-ветка обоих проектов Vercel — **`main`**. Рабочие изменения можно собирать в `develop`, затем переносить проверенную версию в `main`. Слияние в `main` запускает независимые публикации сайта и API; перед проверкой дождитесь `Ready` у обоих. Другие ветки дают preview. `vercel.json` каждого приложения содержит настройки его сборки.

Авторизация проходит так:

1. Организаторы открывают сайт из своего mini-app с краткоживущим JWT в query-параметре `token`.
2. Frontend удаляет параметр из адресной строки и отправляет его в `POST /api/v1/auth/launch` как `host_token`, `mode=host`.
3. API обращается к relay по HTTPS с отдельным `CORE_RELAY_TOKEN`. Relay передаёт JWT в Core: `GET /api/v3/users/user-for-external-service?token=...`, с серверным `CORE_SERVICE_TOKEN` в Bearer-заголовке.
4. После подтверждения пользователя API выдаёт собственную короткоживущую сессию. Frontend хранит её только в памяти.

JWT пользователя, сервисный токен организаторов и секрет relay — разные значения. Учебные учётные записи организаторов привязываются к аккаунту MAX; не используйте их автоматически. Для повторного входа нужен свежий запуск через кнопку MAX.

Relay имеет постоянный адрес Cloud.ru и не зависит от ноутбука. Настройте `CORE_RELAY_URL` в API и одинаковый `CORE_RELAY_TOKEN` у API и relay; `CORE_SERVICE_TOKEN` нужен самому relay. В текущем размещении минимум экземпляров — 0, максимум — 1, ресурсы — 0,5 CPU / 1 ГБ. После простоя контейнер стартует заново, поэтому время пробуждения нужно учитывать при проверке авторизации. История успешных входов не гарантирует успешный холодный старт.

Для контейнера relay используется команда `python -m uvicorn app.core_relay:create_relay --factory --host 0.0.0.0 --port 8080 --no-access-log --no-proxy-headers`. Порт контейнера — 8080, внешний HTTPS обеспечивает облачная платформа. Секреты задаются окружением, не включаются в образ. Free tier имеет квоты; хранение образа и превышения оплачиваются отдельно.

## Переменные окружения

Общий пример Compose — [`.env.example`](.env.example). Полный серверный шаблон — [`apps/api/.env.example`](apps/api/.env.example); публичные настройки frontend — [`apps/web/.env.example`](apps/web/.env.example).

| Где | Переменные |
| --- | --- |
| API: авторизация | `DEMO_MODE=false`, `SESSION_SIGNING_KEY`, `CORE_RELAY_URL`, `CORE_RELAY_TOKEN`, `CORE_TIMEOUT_SECONDS` |
| API: прямой Core, если доступен | `CORE_URL`, `CORE_SERVICE_TOKEN` |
| API: БД | `DATABASE_URL`, при необходимости `DATABASE_SSL_CA_FILE` |
| API: шифрование | Постоянный `DATA_ENCRYPTION_KEY_FILE`; на Vercel допустим `DATA_ENCRYPTION_KEY` — base64 от 32 случайных байтов |
| API: Groq | `NLP_MODE=live`, `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_TIMEOUT_SECONDS` |
| API: распознавание | `VOICE_PROVIDER=groq`, `GROQ_TRANSCRIPTION_MODEL` |
| API: CORS | `CORS_ORIGINS` с точным HTTPS origin сайта |
| Frontend | `VITE_HOST_MODE=max`, `VITE_SURVEY_MODE=api`, `VITE_API_ORIGIN`, `VITE_YANDEX_TILES_API_KEY` |
| Relay | `CORE_SERVICE_TOKEN`, `CORE_RELAY_TOKEN` |

Переменные `VITE_*` попадают в браузер — приватные ключи под такими именами не задаются. В Vercel избегайте пересекающихся записей одной переменной для Production: старый адрес может перекрыть новый. Изменения окружения применяются после новой публикации. Ключ подписи и ключ шифрования нельзя генерировать заново при каждом deployment.

Миграции Alembic запускаются сборкой API до старта приложения. На Vercel PostgreSQL URL преобразуется для asyncpg, TLS проверяет сертификат и имя сервера. Для локального API напрямую используется `postgresql+asyncpg://...` без параметров `ssl`/`sslmode`, с CA в `DATABASE_SSL_CA_FILE`.

CSP frontend разрешает встраивание в `https://web.max.ru` и `https://tm-test-yakut.hostco.ru`. Защита deployment не должна требовать входа в Vercel от пользователей MAX. Токены, query-параметры запуска и содержимое анкет не следует включать в инфраструктурную аналитику.

## Разработка без общего Docker-стека

Нужны Python 3.12+, Node.js 22.12+ и Docker для локальной PostgreSQL. Из корня, в PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[test]" -r apps/api/requirements-backend.txt
cd apps/api
python -m app.core.local_setup --directory ../../.local/runtime
docker compose --project-name medved_local --env-file ../../.local/runtime/backend.env -f compose.postgres.yaml up -d --wait
python -m alembic -x env_file=../../.local/runtime/backend.env upgrade head
.\run_demo.ps1
```

Генератор ключей вызывается один раз для новой папки. Для повторного запуска используйте уже созданный `backend.env`. API доступен по HTTPS на `localhost:8443`, PostgreSQL — на `127.0.0.1:55432`. OpenAPI доступен в `/docs`.

В другом терминале из `apps/web`:

```powershell
npm ci
```

Создайте `apps/web/.env.local` с `VITE_HOST_MODE=demo`, `VITE_SURVEY_MODE=api` и `VITE_API_ORIGIN=https://localhost:8443`, затем выполните `npm run dev`. Локальному браузеру требуется доверие к CA из `.local/runtime/ca.crt`. Для MAX-режима API есть `run_max.ps1`; нужны серверные настройки Core либо relay и `DEMO_MODE=false`.

## Проверки

Python, из `apps/api` с активным окружением:

```powershell
python -m pytest -q
```

Интеграционные тесты PostgreSQL требуют отдельной **тестовой** базы в `TEST_DATABASE_URL` и её CA в `DATABASE_SSL_CA_FILE`. Для неё сохранён `apps/api/compose.postgres-test.yaml`; без тестового URL такие проверки пропускаются. Не направляйте тесты миграций на рабочую БД.

Frontend, из `apps/web`:

```powershell
npm run lint
npm run test:unit
npm run build
npx playwright install chromium
npm test
```

`npm run test:live` отдельно проверяет UI с локальным HTTPS API и синтетической PostgreSQL. Он ожидает API на `https://127.0.0.1:8444` с demo-авторизацией и CORS для `http://127.0.0.1:4174`; адрес можно переопределить через `MEDVED_LIVE_API_ORIGIN`. Удалённые production-адреса этим режимом не поддерживаются.

## API и обслуживание

| Маршрут | Назначение |
| --- | --- |
| `GET /health` | Готовность API |
| `POST /api/v1/auth/launch` | Обмен host JWT на сессию приложения |
| `/api/v1/sessions` | Создание, ответы, возврат, итог и удаление опроса |
| `POST /api/v1/sessions/{id}/emergency-explanation` | Объяснение причины экстренной остановки |
| `/api/v1/chats` | История, сообщения и удаление чатов |
| `POST /api/v1/voice/transcriptions` | Распознавание аудио |
| `/api/v1/clinics/geocode`, `/reverse-geocode`, `/search` | Поиск адреса и клиник |

Контракты и схемы доступны через `/docs` и `/openapi.json` API. Методы с данными требуют Bearer-сессии владельца.

Очистка истёкших обращений выполняется модулем `app.db.cleanup`. Для локального окружения из `apps/api`:

```powershell
python -m app.db.cleanup --env-file ../../.local/runtime/backend.env
python -m app.db.backup --env-file ../../.local/runtime/backend.env backup ../../.local/backups/medved.dump
```

Локальный backup использует контейнер проекта `medved_local`; восстановление выполняется в новую БД через подкоманду `restore --database <новая_БД>`. Облачные резервные копии создаются средствами провайдера или PostgreSQL. Для восстановления историй нужны исходные ключи шифрования. Справочник клиник переносится отдельно от пользовательских обращений.

JSON анкет и переписок шифруется, обращения изолированы по пользователю, используются TTL и проверяемый TLS. Ограничитель запросов хранится в памяти процесса и не является распределённой защитой. Подробности: [логи](docs/LOGGING.md), [prompt-инъекции](docs/PROMPT_SECURITY.md).
