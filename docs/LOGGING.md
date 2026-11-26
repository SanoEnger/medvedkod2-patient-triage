# Диагностика контейнеров и Groq

Из корня проекта:

```powershell
docker compose ps
docker compose logs --since 10m --tail 200 api web postgres init
docker compose logs -f --tail 100 api web
```

Docker ротирует stdout/stderr каждого контейнера: 3 файла по 10 МБ. Логи не
пишутся в образ или БД. Health-check успехи не засоряют HTTP-журнал.

- `init`: начало и завершение подготовки секретов; значения не выводятся.
- `api`: JSON с event, request_id, route-шаблоном, HTTP status и duration_ms.
  `application.ready` показывает фактический mode. `groq.started/completed/failed`
  отличают вызов API от mock. Ошибки содержат фиксированные коды timeout,
  rate_limited, server_error, invalid_response и missing_configuration.
- `web`: JSON access-log Nginx с классом маршрута (chat/survey/auth/page),
  статусом upstream и временем. request_id берётся из ответа backend;
  proxy_request_id позволяет найти запрос, не дошедший до API.
- `postgres`: stderr со временем, PID, SQLSTATE, запуском, checkpoint и lock waits.
  SQL-запросы, bind-параметры и тексты ошибочных SQL не включаются.

Для чата ожидается цепочка `chat.message_saved → groq.started → groq.completed →
chat.reply_validated → chat.reply_saved → http.completed`. В mock-режиме событий
Groq нет. Запись reply_saved означает завершение транзакции сохранения ответа.
Для сопоставления UI/сервера см. X-Request-ID в Network → Response Headers.

Нельзя включать wire/debug логи httpx/httpcore, SQL echo или обычный access-log с
полным URL: launch URL содержит JWT. Прикладные логи не содержат IP, owner/session
ID, query, headers, тела запросов, жалоб и ответов модели. Стандартный error-log
Nginx оставлен на crit: более подробные сообщения могут включать исходный URL.
Трейсы внешней платформы и инфраструктурные логи требуют отдельной настройки.
Ошибки выполнения JavaScript относятся к браузеру, а не Nginx; проверяйте Console
и Network. Тексты формы и сообщения не пересылаются в серверную телеметрию.

## Режим Groq в Docker

`apps/api/.env` читается контейнером через env_file; корневой `.env`, если создан,
имеет приоритет. Для живого вызова: NLP_MODE=live, GROQ_API_KEY и GROQ_MODEL.
Compose больше не заменяет NLP_MODE из API-файла значением mock.
После изменения переменных контейнер нужно пересоздать: `docker compose up -d api`.
Обычный restart не применяет новые значения окружения.

В опроснике Groq извлекает признаки и участвует в анализе завершённой анкеты; сервер проверяет результат и сохраняет приоритет экстренных правил. Чат — отдельный путь запросов. Для экстренного экрана используется отдельное объяснение причины, которое не задерживает показ экстренных действий.

В Vercel проверяйте Runtime Logs проекта API, маршрут `/api/v1/auth/launch`, HTTP-статус и `duration_ms`. Долгий первый запрос к Cloud.ru relay может означать холодный старт. Секреты и токены в журналы не добавляйте. Актуальные ветка публикации и схема размещения описаны в [общем README](../README.md#max-и-размещение).
