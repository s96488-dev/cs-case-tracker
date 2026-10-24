# CS2 Case Price Tracker

Собирает цены всех оружейных кейсов CS2 со Steam Market раз в минуту, 24/7.
Сбор идёт в облаке, данные хранятся у тебя на компьютере в PostgreSQL.
Если компьютер выключен, облако копит данные в буфере и отдаёт их при следующем включении.

```
            каждые 60 c                                  когда ПК включён, раз в минуту
 Steam Market ───────────► Облако (Google Cloud e2-micro) ◄──────────── Домашний ПК (Windows)
 search/render             cloud/ : сборщик + буфер SQLite   HTTPS +   home/ : синхронизатор
 1 запрос = все кейсы      + API выдачи (/api/ticks, /ack)   токен     → PostgreSQL
                           хранит неотданное до 60 дней                → API графиков :8080
                                                                       → TradingView
```

## Почему так

**Источник — только Steam.** Используется JSON-эндпоинт поиска маркета
(`steamcommunity.com/market/search/render/?norender=1`), тот же, который вызывает сама страница маркета.
Один запрос возвращает все кейсы сразу (их меньше 100) с минимальной ценой продажи и числом лотов.
1 запрос в минуту — примерно в 20 раз ниже порога, после которого Steam отвечает `429`, поэтому
браузерные скраперы, логин и прокси не нужны. При `429` сборщик сам увеличивает паузу (2 → 15 минут).
`priceoverview` (медиана, объём за 24 ч) не используется: это запрос на каждый кейс отдельно, ~45 в минуту
гарантированно упрутся в лимит.

**Облако → дом по модели «дом сам забирает».** Домашнему ПК не нужен белый IP и открытые порты.
Каждая запись в буфере имеет возрастающий id, дом хранит курсор в своей базе и подтверждает (`ack`)
сохранённое. Данные и курсор пишутся в одной транзакции, вставка идемпотентна, поэтому обрывы связи,
перезапуски и даже пересоздание облачного буфера не дают ни потерь, ни дублей.

**Модель данных.** Таблица `items` (предмет) + `price_ticks` (снимок цены). У кейсов нет своих параметров,
у скинов они будут лежать в `items.attributes` (JSONB), таблица цен не меняется. Поле `source` оставлено,
чтобы в будущем можно было различать, например, разные валюты Steam.

## Что лежит в репозитории

| Путь | Что это |
|---|---|
| `common/steam.py` | запрос к Steam и разбор ответа, фильтр «только кейсы» |
| `common/models.py` | `Item` / `Case` / `PriceTick` |
| `cloud/` | облачный сервис: сборщик, буфер, API выдачи |
| `Dockerfile`, `docker-compose.yml`, `Caddyfile` | запуск в облаке с HTTPS |
| `home/schema.sql` | схема PostgreSQL (создаётся автоматически) |
| `home/sync.py` | синхронизатор облако → PostgreSQL |
| `home/api.py` | API для графиков и UDF-датафид TradingView |
| `home/static/index.html` | временная страница с графиком (Lightweight Charts), пока нет React |
| `start-home.bat` | запуск домашней части на Windows |

## 1. Облако: Google Cloud e2-micro (бесплатный тариф)

1. Зайди в [console.cloud.google.com](https://console.cloud.google.com), создай проект и привяжи платёжный
   аккаунт (без него нельзя даже бесплатный тариф). Сразу заведи **Billing → Budgets & alerts** на $1,
   чтобы узнать о любом списании.
2. **Compute Engine → VM instances → Create instance**:
   - регион `us-central1`, `us-west1` или `us-east1` (бесплатно только в них);
   - тип машины **e2-micro**;
   - диск: Debian 12, тип **Standard persistent disk**, до 30 ГБ (balanced/SSD уже платные);
   - Firewall: отметь **Allow HTTP** и **Allow HTTPS**.
   Проверь в калькуляторе при создании, что внешний IP не добавляет стоимость в твоём регионе.
3. Нажми **SSH** у машины (откроется терминал в браузере) и поставь Docker:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   ```
4. Залей код: кнопкой **Upload file** в окне SSH загрузи `cs-case-tracker.zip`, затем
   `sudo apt-get install -y unzip && unzip cs-case-tracker.zip && cd cs-case-tracker`
   (или `git clone`, когда код будет в репозитории).
5. Создай `.env` по образцу `.env.example`:
   ```bash
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # это API_TOKEN
   nano .env    # впиши API_TOKEN и DOMAIN = внешний IP через дефисы + .sslip.io
   ```
6. Запусти: `sudo docker compose up -d --build`. Сервисы перезапускаются сами после перезагрузки VM.
7. Проверь: `curl https://<DOMAIN>/health` → `last_success_at` должен обновляться каждую минуту.
   Логи: `sudo docker compose logs -f collector`.

## 2. Дом: PostgreSQL + синхронизатор (Windows)

1. Поставь [PostgreSQL](https://www.postgresql.org/download/windows/) (16 или новее) и Python 3.11+.
   Базу создавать не нужно: синхронизатор создаст `cs_prices` и таблицы сам.
2. Скопируй `home\.env.example.bat` в `home\env.bat` и впиши пароль postgres, адрес облака и тот же токен.
3. Запусти `start-home.bat`. Первый запуск создаст виртуальное окружение и поставит зависимости.
4. Открой <http://127.0.0.1:8080> — список кейсов и свечной график.
5. Автозапуск: **Планировщик заданий → Создать задачу** → триггер «При входе в систему» →
   действие: запуск `start-home.bat`. После включения ПК он догонит всё, что накопилось в облаке.

## API (домашний, порт 8080)

| Запрос | Ответ |
|---|---|
| `GET /api/items` | все кейсы: последняя цена, лоты, цена 24 ч назад |
| `GET /api/candles?item_id=7&tf=60` | OHLC-свечи; `tf`: `1`, `5`, `15`, `60`, `240` (минуты) или `1D` |
| `GET /api/status` | сколько снимков в базе и время последнего |
| `GET /udf/config`, `/udf/symbols`, `/udf/search`, `/udf/history`, `/udf/time` | датафид для TradingView Charting Library |

Свечи строятся из минутных снимков минимальной цены продажи. «Объём» на графике — среднее число
лотов на продаже: настоящий объём сделок этот эндпоинт Steam не отдаёт.

Для TradingView два варианта:
- **Lightweight Charts** (открытая библиотека, уже используется на временной странице) — берёт `/api/candles`.
- **Charting Library** (полный интерфейс TradingView с индикаторами) — бесплатно, но доступ выдают
  по заявке на сайте TradingView; подключается к `/udf` через их `UDFCompatibleDatafeed`.

## Облачный API (для синхронизатора)

`GET /health` (без токена), `GET /api/stats`, `GET /api/ticks?after_id=N&limit=5000`, `POST /api/ack {"up_to_id": N}`
— все, кроме `/health`, с заголовком `Authorization: Bearer <API_TOKEN>`.

## Что дальше

- React-фронт на Lightweight Charts или Charting Library поверх `/api` и `/udf`.
- Догрузка старой истории: эндпоинт Steam `pricehistory` отдаёт всю историю цены (по часам/дням),
  но требует cookie залогиненного аккаунта.
- Скины: наследник `Item` с параметрами в `attributes` и отдельный запрос поиска.
