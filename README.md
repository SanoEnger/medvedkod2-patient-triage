# МедВед — навигатор пациента

Рабочая интеграционная ветка — `develop`. `main` предназначена для проверенного
релиза. Здесь собраны React-оболочка, FastAPI backend, детерминированные правила
безопасности, MAX server-to-server adapter и автономный Groq NLP-модуль.

Это демонстрационный прототип для синтетических данных. Frontend подключает
backend для MAX-авторизации; SessionService использует NLP для свободных жалоб.
Опросник подключён к API: согласие, пять шагов, возврат, экстренный экран и результат. PostgreSQL-хранилище с шифрованием и TLS подключено. Наличие компонентов в одной ветке
не означает готовность медицинского сервиса или сквозной интеграции MAX.

На главной доступна «История чатов». Оттуда можно открыть или удалить
сохранённую переписку, включая чат по завершённому опросу. История хранится
в PostgreSQL до конца исходного срока обращения, максимум 24 часа. При
повторном входе через MAX сервер показывает историю того же пользователя.

## Запуск всего проекта в Docker

Из корня репозитория:

~~~powershell
docker compose up --build -d
~~~

Открыть https://localhost:8443. Инструкция по локальному сертификату, настройкам и сохранению данных — [Docker](docs/DOCKER.md).

## Голосовой ввод

Диктовка на русском доступна в текстовых полях анкеты и в чате. Запись длится до 30 секунд. После остановки распознанный текст добавляется в черновик. Приложение обрабатывает аудио на своём сервере и не сохраняет запись в базе.

Подготовьте модель один раз из корня репозитория:

```powershell
python -m pip install -r apps/api/requirements-voice.txt
python -c "from faster_whisper.utils import download_model; download_model('base', output_dir='.local/models/whisper-base')"
```

Для Docker задайте `INSTALL_VOICE=1` в корневом `.env` и запустите `docker compose up --build -d`. При запуске API без Docker укажите в `apps/api/.env` абсолютный путь к скачанной папке в `WHISPER_MODEL_PATH`. Откройте приложение по HTTPS и разрешите доступ к микрофону.

## Компоненты и запуск

- [PostgreSQL](apps/api/README_POSTGRES.md) — схема, миграции и запуск БД.
- [Backend и API](apps/api/README_BACKEND.md) — конфигурация, запуск сервера,
  сессии PostgreSQL и правила безопасности.
- [Groq NLP](apps/api/README.md) — установка, mock, fallback и формат извлечения.
- [React UI](apps/web/README.md) — запуск, demo/production-сборки и браузерные тесты.
- [MAX](apps/api/MAX_INTEGRATION.md) — границы серверной проверки host-токена.

Для общей проверки Python-компонентов из `apps/api`:

```powershell
python -m pip install -e ".[test]" -r requirements-backend.txt
python -m pytest -q
```

Для проверки frontend из `apps/web`:

```powershell
npm ci
npm run lint
npm run test:unit
npm run build
npm run build:demo
npx playwright install chromium
npm test
```

Для проверки истории в браузере с локальным HTTPS API и PostgreSQL
используйте `npm run test:live` по инструкции в [README frontend](apps/web/README.md#сквозная-проверка-с-настоящей-бд).

Не передавайте реальные медицинские данные и не добавляйте секреты в Git.
Клиническая проверка правил и проверка реального MAX остаются отдельными задачами.
