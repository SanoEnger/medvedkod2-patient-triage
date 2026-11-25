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

## Поиск поликлиник в Кургане

Из нового или сохранённого результата опроса в поиск переносятся специальность и возрастная группа пациента. Если в опросе возраст пропущен, выберите группу на экране поиска. Поиск сортирует подходящие филиалы по расстоянию от выбранного дома. Детские отделения доступны пациентам младше 18 лет. Для такого поиска в государственном каталоге учитываются филиалы с подтверждённым детским приёмом.

Завершите опрос или откройте результат из истории, чтобы перейти к поиску. Адрес можно ввести вручную. Геолокация запрашивается по кнопке. Докер применяет миграции при старте. Затем импортируйте филиалы и адреса независимо друг от друга.

```powershell
docker compose up --build -d --wait
docker compose exec api python -m app.container import-clinics /app/clinic_catalog/kurgan.json
docker compose exec api python -m app.container import-clinic-addresses /app/clinic_catalog/kurgan-osm.json.gz
# При DEMO_MODE=true можно добавить явно помеченные демонстрационные филиалы.
docker compose exec api python -m app.container import-clinics /app/clinic_catalog/kurgan-demo.json
```

Откройте `https://localhost:8443` и введите адрес дома пациента, например «Курган, ул. Кравченко, 53». От выбранного дома рассчитывается расстояние до филиалов. Для просмотра всех ближайших карточек можно убрать предустановленный фильтр специалиста или увеличить радиус. Проверьте фильтр «Платно» со специальностью «Дерматолог» на адресе «Курган, ул. Советская, 119». В базовом каталоге подтверждён платный приём по этому профилю в «Центре ДНК» на Советской и в «АльфаМед» на Томина. Сведения об ОМС, ДМС и платном приёме отображаются при наличии подтверждения для конкретного филиала и специальности.

Городская выгрузка Geofabrik от 25 ноября 2026 года по времени Кургана даёт 8 131 адресную запись после фильтрации. Координаты филиалов базового каталога сверены с адресами зданий OpenStreetMap. Источники телефонов, расписаний и способов оплаты сохранены рядом с записями в `apps/api/clinic_catalog/kurgan.json`. [OSM у Невежина](https://api.openstreetmap.org/api/0.6/map?bbox=65.299,55.430,65.303,55.433), [OSM у Кравченко](https://api.openstreetmap.org/api/0.6/map?bbox=65.361,55.442,65.365,55.445), [список филиалов для диспансеризации на 2026 год](https://kapmed.ru/upload/iblock/401/d8puzmfuj8ki1k5ua12wi72qqi1oon9i.pdf), [территориальная программа ОМС](https://kurgan-med.ru/info/territorialnaya-programma-gosudarstvennykh-garantiy-besplatnogo-okazaniya-meditsinskoy-pomoshchi-zhi/).

Для обновления справочника выгрузите объекты по городской границе Кургана из файла запроса. Импортер читает готовую локальную выгрузку, использует точки и геометрию адресных зданий, сохраняет OSM ID и за одну транзакцию обновляет справочник. При работе без Compose выполните `python -m alembic upgrade head` и запустите `python -m app.db.import_clinic_addresses <файл>` и `python -m app.db.import_clinics <файл>` из `apps/api` с настройками той же PostgreSQL.

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
curl.exe --fail --get --data-urlencode "data@apps/api/clinic_catalog/kurgan.overpassql" https://overpass-api.de/api/interpreter -o .local/kurgan-addresses.json
docker compose cp .local/kurgan-addresses.json api:/tmp/kurgan-addresses.json
docker compose exec api python -m app.container import-clinic-addresses /tmp/kurgan-addresses.json
```

Городской набор можно также пересобрать из свежего `ural-fed-district-latest.osm.pbf`. В локальном окружении API установите `osmium` и из `apps/api` запустите `python -m app.db.export_kurgan_addresses <экстракт.osm.pbf> <новый-справочник.json.gz>`. Затем загрузите получившийся файл обычной командой импорта. [Региональные выгрузки Geofabrik](https://download.geofabrik.de/russia/ural-fed-district/).

Покрытие зависит от разметки OSM. При публикации адресного набора или изменённой базы сохраняйте атрибуцию OpenStreetMap и соблюдайте условия ODbL для производной базы. Атрибуция справочника видна и в режиме списка. [Лицензия и атрибуция OpenStreetMap](https://www.openstreetmap.org/copyright), [граница Кургана в OSM](https://www.openstreetmap.org/relation/398427).

Без ключа карта использует тайлы OpenStreetMap. Для основной подложки Яндекса задайте `VITE_YANDEX_TILES_API_KEY` в корневом `.env` перед сборкой Compose или в `apps/web/.env.local` для Vite. В кабинете Яндекса ограничьте ключ доменами фронтенда. У запросов тайлов Referer содержит только origin. Ручной поиск работает через PostgreSQL даже при недоступности обеих подложек. [Настройка Яндекс Tiles API](https://yandex.ru/maps-api/docs/tiles-api/quickstart.html), [правила тайлов OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/).

### Источник «Поликлиника45»

Импорт дополняет филиалы и специальности в PostgreSQL. Поиск и карточки читают локальную базу. Кнопка «Записаться через Поликлинику45» открывает сопоставленную страницу учреждения. Кнопка «Записаться через Госуслуги» ведёт на форму записи, где при необходимости выбирают филиал. Для платного приёма и частных клиник запись предлагается по телефону.

Для проверки ОМС выберите «Гинеколог» и «ОМС». Для взрослого пациента есть, например, филиалы на Дзержинского, 41Б и Карельцева, 54. Для ребёнка есть отделения на Коли Мяготина, 114 и проспекте Конституции, 38. Условия приёма и прикрепление уточняются в регистратуре.

Проверка 25 ноября 2026 года подтвердила серверный HTML раздела специальностей, списка врачей с пагинацией, карточек организаций и страниц расписания. Публичный JavaScript также содержит JSON-запрос автодополнения `/service/schedule/search`. Для обхода справочника он не нужен. Путь расписания разрешён действующим robots.txt. На просмотренных открытых страницах отдельные условия автоматизированного доступа не опубликованы. Импорт использует десять специальностей из словаря МедВеда и фильтр территории Кургана. В условиях технических работ, недоступности или неизвестной разметки команда останавливается до записи в БД. [Специальности](https://www.poliklinika45.ru/service/schedule/profiles), [пример списка врачей](https://www.poliklinika45.ru/service/schedule/0/450101000000028/doctors), [пример карточки организации](https://www.poliklinika45.ru/service/hospitals/view/1155017), [robots.txt](https://www.poliklinika45.ru/robots.txt).

Команда сначала сохраняет и полностью проверяет набор, затем применяет его. Для проверки без обновления БД используйте `--collect-only` вместе с `--snapshot-out`. Сохранённый проверенный набор можно загрузить повторно. Это внутренний JSON МедВеда. Корень содержит `schema_version: 1`, `source: "poliklinika45"`, `complete: true`, `retrieved_at` с часовым поясом, `start_url` и `pages`. Каждая страница содержит публичный `url`, `records` и `next_url` для следующей страницы. В записи обязательны `kind` (`organization` или `branch`), `external_id` и публичный `url`. Можно указать `name`, `organization_external_id`, `organization_name`, `address`, `phones` в E.164 или короткий номер 122, `official_website`, `facility_kind` (`public` или `private`), `specialties` и `field_urls` для отдельного происхождения полей. В `specialty_urls` можно указать публичную страницу для каждой специальности. Опубликованное расписание можно сохранить в `schedule` с полями `specialty`, `date`, `starts_at`, `ends_at` и датой актуальности `schedule_as_of` на записи. Живой обход собирает датированные диапазоны опубликованных временных отметок максимум из десяти открытых расписаний. Доступность талонов и имена врачей в набор не включаются.

```powershell
docker compose cp .local/poliklinika45-verified.json api:/tmp/poliklinika45.json
docker compose exec api python -m app.container import-poliklinika45 --snapshot /tmp/poliklinika45.json --report /tmp/poliklinika45-report.json
docker compose cp api:/tmp/poliklinika45-report.json .local/poliklinika45-report.json
docker compose exec api python -m app.container import-poliklinika45 --live --snapshot-out /tmp/poliklinika45.json --report /tmp/poliklinika45-report.json
```

При запуске без Compose выполните `python -m app.db.import_poliklinika45 --snapshot <файл> --report <отчёт.json>` из `apps/api` с настройками TLS той же базы. Для периодического обновления запускайте эту команду из Планировщика заданий или cron, например ежедневно в 03:00 по времени Кургана. Для обновления непосредственно с портала запускайте `--live`. Запросы выполняются последовательно с интервалом не меньше секунды. Повторы ограничены, учитывается `Retry-After`. Импорт проверяет связность страниц, применяет набор в одной транзакции под блокировкой PostgreSQL и сохраняет в отчёт совпадения, конфликты, поля и адреса для проверки. При сбое HTTP, CAPTCHA, заглушке или неполном наборе справочник остаётся на прошлой успешной версии.

## Голосовой ввод

На Vercel распознавание выполняет Groq Whisper: в серверных Environment Variables
проекта `medved-api` задаются `VOICE_PROVIDER=groq`, `GROQ_API_KEY` и
`GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo`. Запись передаётся Groq для
распознавания; текст возвращается в черновик. `INSTALL_VOICE` относится только
к Docker и не устанавливает локальную модель на Vercel.

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
