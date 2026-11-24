# MAX Core relay — Cloudflare Workers Free

Альтернатива локальному relay, без зависимости от включённого компьютера.
Совместим с существующими `CORE_RELAY_URL` и `CORE_RELAY_TOKEN` основного API.

## Проверки

Из корня репозитория: `node --test apps/core-relay-worker/worker.test.mjs`.

## Публикация

1. Авторизовать официальный Wrangler в аккаунте Cloudflare с Workers Free.
   Не включать платный план.
2. Сначала проверить доступ к Core тестовым Worker без секретов.
   Работающий локальный relay до этой проверки не отключать.
3. В секретах Worker настроить `CORE_SERVICE_TOKEN` организаторов и отдельный
   `CORE_RELAY_TOKEN` длиной не менее 32 символов. Не помещать их в конфигурацию
   Wrangler, Git, браузерный код или журналы.
4. Опубликовать: `npx wrangler@4.166.0 deploy --config apps/core-relay-worker/wrangler.jsonc`.
5. Проверить `GET /health`, отказ без секрета и настоящий вход через MAX.
   Только после успешных проверок переключить `CORE_RELAY_URL` в Vercel на
   постоянный адрес Worker и повторно опубликовать API.

`POST /resolve` принимает JSON `{"token":"<JWT пользователя>"}` и
`Authorization: Bearer <CORE_RELAY_TOKEN>`. Токен передаётся только фиксированному
Core организаторов. При ошибке идентификатор пользователя не выдаётся.
Ответ содержит только `_id`, профили не сохраняются. Журналы Worker отключены.

Free-план имеет квоты, в том числе 100 000 запросов в сутки на аккаунт;
актуальные условия: https://developers.cloudflare.com/workers/platform/pricing/.
