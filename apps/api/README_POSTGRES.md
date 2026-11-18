# PostgreSQL: схема, подключение и обслуживание

БД готова для локальной интеграции MVP: PostgreSQL 16+, SQLAlchemy 2, asyncpg, Alembic. API использует постоянное хранилище; данные сохраняются после перезапуска процесса и контейнера. При недоступной БД, неверном ключе или несовместимой схеме приложение не переключается на память.

## Полная схема

| Таблица | Назначение |
| --- | --- |
| sessions | Владелец, статус, шаг, TTL и зашифрованное состояние с идемпотентностью |
| answers | Актуальные структурированные ответы, включая анамнез |
| messages | Хронология вопросов, ответов, возвратов и снимков результата |
| triage_results | Один актуальный результат на обращение, срочность и версии правил |
| safety_rule_versions | Каталог версий действующих правил, приоритет, enabled и predicates |
| audit_events | Служебные события с разрешёнными метаданными |
| integration_nonces | Хеши одноразовых значений, срок и отметка использования |

Техническая таблица alembic_version хранит ревизию схемы.

answers, messages и triage_results связаны с sessions через ON DELETE CASCADE. У triage_results уникален session_id. audit_events.session_id допускает NULL и использует ON DELETE SET NULL: после удаления обращения журнал теряет связь с ним. В meta нет идентификатора владельца или копии ID обращения.

Индексы покрывают TTL, список обращений владельца, порядок ответов/сообщений, время и сессию аудита. CHECK-ограничения проверяют статусы, приоритеты, порядок, TTL и формат зашифрованных JSON.

## Запуск с нуля

Из корня репозитория, Python 3.12+ и Docker:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[postgres,test]" -r apps/api/requirements-backend.txt
cd apps/api
python -m app.core.local_setup --directory ../../.local/runtime
docker compose --project-name medved_local --env-file ../../.local/runtime/backend.env -f compose.postgres.yaml up -d --wait
python -m alembic -x env_file=../../.local/runtime/backend.env upgrade head
.\run_demo.ps1
```

Генератор вызывается только для новой пустой папки. Существующие ключи не перезаписываются. При повторном запуске используйте уже созданный backend.env и пропустите генерацию.

API: https://localhost:8443; документация: https://localhost:8443/docs. Локальная БД: 127.0.0.1:55432. Пароль случайный, хранится в игнорируемом backend.env. Docker-том postgres-data сохраняется после обычного down; удаление тома уничтожит данные.

Для MAX-режима задайте CORE_SERVICE_TOKEN в окружении и запустите run_max.ps1. Сервисный токен не передаётся клиенту. Frontend и HTTP-методы истории в этой ветке не добавляются; публичный домен пока не задан.

## Шифрование и TLS

JSON шифруется приложением AES-256-GCM до записи. Каждый шифротекст получает случайный nonce и контекст конкретной записи/поля. Это относится к ответам, состоянию, переписке, полям результата, predicates правил и meta аудита.

В triage_results поля specialty, place и rationale — JSONB с зашифрованным объектом value; rule_codes содержит зашифрованные коды и версии правил. details_jsonb хранит зашифрованные disclaimer и needs_clarification. Операции чтения возвращают обычный объект TriageResponse. Расшифрованный JSON не присваивается ORM-полям.

Открыты только служебные поля: UUID, непрозрачный owner_id, статус, шаг, срочность, коды/версии каталога, роли, виды событий и время. Исходные жалобы, анамнез, сообщения и тексты рекомендаций в открытом виде в БД не хранятся.

DATA_ENCRYPTION_KEY_FILE указывает на файл с base64 от 32 случайных байт. Ключ хранится отдельно от Git и дампов. Для восстановления нужен тот же ключ; его потеря делает данные недоступными. Простая замена ключа без перешифрования не поддерживается.

API принимает HTTPS, отклоняет HTTP с 426, не доверяет X-Forwarded-Proto и выдаёт HSTS. TLS 1.2 и выше включён для API и PostgreSQL. Клиент БД проверяет CA и имя сервера; локальный pg_hba.conf запрещает сетевой доступ без TLS.

Локальные сертификаты сервера действуют 30 дней. Их CA не устанавливается в системное хранилище автоматически:

```powershell
curl.exe --cacert ../../.local/runtime/ca.crt https://localhost:8443/health
```

Для браузера нужно доверие к локальному CA. При размещении задайте API_TLS_CERT_FILE/API_TLS_KEY_FILE для настоящего домена и DATABASE_SSL_CA_FILE для сертификата PostgreSQL. Приватные ключи API, CA и AES не передаются контейнеру БД; ему монтируется только собственная пара сертификат/ключ.

SQLAlchemy скрывает параметры, SQL echo и access log API отключены. Настройки внешних прокси и PostgreSQL должны исключать запись тел запросов, JWT, паролей и медицинских текстов.

## Результаты, правила, история и аудит

Результат сохраняется в triage_results в одной транзакции с опросом, историей и аудитом. Возврат к предыдущему шагу удаляет актуальный результат и последующие актуальные ответы; прежняя переписка и снимки результатов остаются в messages. Повтор с тем же idempotency_key не дублирует ответ, сообщение и событие аудита.

Каталог safety_rule_versions заполнен версиями текущей синтетической реализации. Версия учитывает реализацию проверок, маршрутизации и медицинские тексты; результат хранит версию набора и версии сработавших правил. При старте API сверяет каталог и расшифрованные predicates с кодом. Прямые изменения каталога не подменяют клиническую логику: обновление правил требует review, изменения backend и отдельной миграции каталога. Исходный каталог ревизии 04 зафиксирован в alembic/seeds/20261118_04_safety_rules.json.

Старые результаты, у которых версия не сохранялась, переносятся с пометкой legacy-unversioned. Им не приписывается версия правил, которую невозможно подтвердить.

Аудит фиксирует создание, сохранение ответа, возврат, результат, удаление и истечение срока. meta принимает только step, status и version с проверкой типов; жалобы, prompt, JWT и идентификаторы владельца не допускаются. Метаданные также шифруются.

integration_nonces подготовлена как условная часть ТЗ. register_nonce сохраняет только SHA-256, consume_nonce атомарно отмечает первое использование. Повтор, неизвестное и просроченное значение отклоняются. Текущий JWT-протокол MAX не переключается на nonce автоматически.

## Интерфейсы для следующего этапа интеграции

Все операции получают AsyncSession; транзакцией управляет вызывающий код.

- app.db.repository: create_session, get_session, append_answer, get_answers, delete_session, list_sessions, append_message, get_messages, delete_expired_sessions.
- app.db.results: save_triage_result, get_triage_result, delete_triage_result.
- app.db.audit: record_audit, delete_expired_audit_events.
- app.db.nonces: register_nonce, consume_nonce, delete_expired_nonces.
- app.db.survey_store.PostgresSurveyStore уже подключён к SessionService через create_app.

Пользовательские операции требуют owner_id и исключают просроченные обращения. list_sessions сортирует новые обращения первыми, поддерживает limit/offset с максимумом 100. get_answers/get_messages возвращают зашифрованные ORM-записи; для представления в API используйте JsonCipher.decrypt с answer_context/message_context. get_triage_result возвращает расшифрованный объект результата.

## TTL и очистка

TTL обращения не превышает 24 часов. API раз в минуту удаляет просроченные обращения с ответами, перепиской и актуальным результатом. Одновременно очищаются аудит старше 24 часов и просроченные nonce.

Отдельный запуск с теми же настройками:

```powershell
python -m app.db.cleanup --env-file ../../.local/runtime/backend.env
```

Команда выводит только количество удалённых обращений.

## Миграции

Текущая ревизия: 20261118_04.

```powershell
python -m alembic -x env_file=../../.local/runtime/backend.env current
python -m alembic history
python -m alembic -x env_file=../../.local/runtime/backend.env upgrade head
python -m alembic -x env_file=../../.local/runtime/backend.env check
```

01 создаёт sessions/answers; 02 шифрует JSON; 03 создаёт переписку; 04 добавляет результаты, каталог правил, аудит и nonce, переносит существующие результаты из состояния. Перед обновлением существующей БД создайте резервную копию. Ключ AES должен оставаться прежним.

Повторный upgrade head безопасен. При ошибке переноса транзакция откатывается. Шаги 02–04 требуют подключения и ключа; offline SQL поддерживается только для начальной схемы.

Откат с данными намеренно ограничен: 04 не удаляется при наличии результатов, аудита или nonce; 03 — при наличии переписки; 02 — при наличии обращений. На рабочей БД используйте резервную копию вместо удаления данных ради downgrade.

На отдельной пустой тестовой БД, с переменными из следующего раздела:

```powershell
$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = $env:TEST_DATABASE_URL
    python -m alembic downgrade base
    python -m alembic upgrade head
} finally {
    $env:DATABASE_URL = $previousDatabaseUrl
}
```

## Проверки

Тестовая БД работает отдельно на 127.0.0.1:55433, данные временные. Проверки допускают только пустую БД с именем *_test и не удаляют существующие прикладные таблицы. Постоянная БД приложения не затрагивается.

```powershell
docker compose --project-name medved_tests --env-file ../../.local/runtime/backend.env -f compose.postgres-test.yaml up -d --wait
$env:DATABASE_SSL_CA_FILE = (Resolve-Path ../../.local/runtime/ca.crt).Path
$env:DATA_ENCRYPTION_KEY_FILE = (Resolve-Path ../../.local/runtime/encryption.key).Path
$env:API_TLS_CERT_FILE = (Resolve-Path ../../.local/runtime/api.crt).Path
$env:API_TLS_KEY_FILE = (Resolve-Path ../../.local/runtime/api.key).Path
$env:TEST_DATABASE_URL = "postgresql+asyncpg://medved_test:synthetic-test-only@127.0.0.1:55433/medved_test"
python -m pytest -q
docker compose --project-name medved_tests --env-file ../../.local/runtime/backend.env -f compose.postgres-test.yaml down
```

Без TEST_DATABASE_URL интеграционные проверки пропускаются. Проверяются новая схема, обновление заполненной базы, безопасный откат, каскады, TTL, права, шифрование, версии, идемпотентность, конкурентные nonce и настоящее TLS-соединение.

## Резервная копия и восстановление

Для локального контейнера доступны команды на основе [pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html) и [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html). Двоичные данные передаются напрямую, без текстового конвейера PowerShell:

```powershell
python -m app.db.backup --env-file ../../.local/runtime/backend.env backup ../../.local/backups/medved-before-update.dump
python -m app.db.backup --env-file ../../.local/runtime/backend.env restore ../../.local/backups/medved-before-update.dump --database medved_restore_test
```

backup отказывается перезаписывать существующий файл. restore создаёт новую БД и отказывается от существующей цели или имени исходной БД. Восстановление выполняется одной транзакцией. Для проверки переключите DATABASE_URL на новую БД и используйте исходный ключ AES; рабочую базу автоматически не переключают.

Храните резервные копии и ключ AES отдельно, вне Git. Копия содержит зашифрованные данные, но не сам ключ. Для демо учитывайте срок хранения копий при настройке ротации.

## Размещение на сервере

Схема и операции БД подготовлены; для размещения остаются параметры окружения: постоянный диск, закрытый сетевой доступ к PostgreSQL, отдельные роли приложения и миграций, секреты, действительные сертификаты, расписание резервного копирования и проверка восстановления. Публичный доступ пользователям должен идти через API. Домен и сервер выбираются на этапе размещения.
