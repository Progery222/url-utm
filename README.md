# URL Tracker

Минималистичный сервис для создания коротких ссылок и отслеживания переходов.

## Стек

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy + PostgreSQL
- HTML + Tailwind CSS (CDN)

## Переменные окружения

| Переменная | Обязательно | По умолчанию | Назначение |
|------------|-------------|--------------|------------|
| `DATABASE_URL` | да | — | PostgreSQL, строка подключения |
| `DEFAULT_TARGET_URL` | нет | см. `main.py` | Куда ведёт редирект для новых коротких ссылок |
| `TRUSTED_PROXY_COUNT` | нет | `1` | Сколько «правых» прокси в цепочке перед приложением (Railway/Cloudflare обычно `1`). Влияет на разбор `X-Forwarded-For` |
| `GEOIP_DB_PATH` | нет | `GeoLite2-City.mmdb` | Путь к файлу базы MaxMind GeoLite2 City (`.mmdb`). Если файла нет — регион в кликах будет пустым |
| `ATTRIBUTION_SHARED_SECRET` | нет | пусто | Общий секрет для HMAC-подписи запросов `POST /api/device-attribution`. Если не задан — endpoint отклоняет запросы |

## GeoIP (регион по IP)

1. Зарегистрируйся на [MaxMind](https://www.maxmind.com/) и создай **бесплатную** лицензию на **GeoLite2**.
2. Скачай архив **GeoLite2 City** (файл `GeoLite2-City.mmdb`).
3. Положи `GeoLite2-City.mmdb` в корень проекта (рядом с `main.py`) **или** укажи свой путь в `GEOIP_DB_PATH`.
4. Условия лицензии GeoLite2 и атрибуция — на сайте MaxMind; не публикуй лицензионный ключ в репозитории.

**Деплой (Railway и аналоги):** файл `.mmdb` в репозиторий обычно не кладут. Варианты: приватный репозиторий и добавление файла в образ, отдельный том/volume, или сборка образа с шагом загрузки базы (через `geoipupdate` и секрет с лицензионным ключом MaxMind). Главное — чтобы в рантайме по пути `GEOIP_DB_PATH` файл реально существовал.

## Локальный запуск

```bash
# Установка зависимостей
pip install -r requirements.txt

# Переменные окружения (Windows PowerShell: $env:DATABASE_URL="...")
export DATABASE_URL="postgresql://user:pass@localhost:5432/urltracker"
# опционально:
export TRUSTED_PROXY_COUNT=1
export GEOIP_DB_PATH="./GeoLite2-City.mmdb"
# export ATTRIBUTION_SHARED_SECRET="длинная-случайная-строка"

# Запуск
uvicorn main:app --reload
```

## Деплой на Railway

### 1. Создать проект
- Зайди на [railway.app](https://railway.app) и создай новый проект.

### 2. Добавить PostgreSQL
- В проекте нажми **New** → **Database** → **Add PostgreSQL**.
- Railway создаст базу автоматически и сгенерирует `DATABASE_URL`.

### 3. Загрузить код
- В проекте нажми **New** → **Empty Service**.
- Перейди во вкладку **Settings** сервиса.
- В разделе **Source** выбери **Deploy from GitHub repo** (или используй CLI `railway login` + `railway link`).

### 4. Прокинуть переменные окружения
- Перейди во вкладку **Variables** сервиса.
- Обязательно:
  - `DATABASE_URL` → скопируй значение из сервиса PostgreSQL (раздел Variables базы). Формат: `postgresql://...`
- Рекомендуется:
  - `TRUSTED_PROXY_COUNT` → обычно `1` для одного edge-прокси перед приложением.
  - `ATTRIBUTION_SHARED_SECRET` → случайная длинная строка (если используешь нативную атрибуцию IMEI/serial).
  - `GEOIP_DB_PATH` → путь к `.mmdb` **внутри контейнера**, если базу GeoIP добавляешь в образ или том (иначе регионы останутся пустыми).
- Railway автоматически предоставляет переменную `PORT`, дополнительно её создавать не нужно.

### 5. Задать команду запуска (Start Command)
- Во вкладке **Settings** найди раздел **Deploy** → **Start Command**.
- Укажи: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Либо используй `Procfile` (уже в репозитории), Railway подхватит его автоматически.

### 6. Деплой
- Нажми **Deploy** (или запушь код в подключенный репозиторий).
- Railway соберет и запустит приложение.
- Во вкладке **Deployments** можно посмотреть логи.

### 7. Домен
- После успешного деплоя перейди во вкладку **Settings** → **Domains**.
- Нажми **Generate Domain**, чтобы получить публичный URL.

## API

- `POST /api/links` — создать ссылку (тело: `{ "label": "..." }`, целевой URL задаётся `DEFAULT_TARGET_URL`)
- `GET /api/links` — список всех ссылок со статистикой
- `GET /api/links/{slug}/stats` — агрегаты: клики, уникальные, устройства, ОС, **модели**, **регионы**
- `GET /api/links/{slug}/clicks?limit=50&offset=0` — последние клики с IP, гео и полями устройства
- `GET /api/links/{slug}/device-uniqueness` — отчет по виртуальным устройствам: уникальные и совпадающие `farm_id` по отпечатку IP/гео/User-Agent/модели/ОС/браузера
- `GET /{slug}` — переход по короткой ссылке (редирект + запись клика; запрашиваются Client Hints для модели)
- `POST /api/device-attribution` — приём данных из нативного приложения (IMEI/serial **не** хранятся в открытом виде, только SHA-256 хеши; нужна подпись)
- `GET /api/links/{slug}/attributions` — список записей атрибуции по ссылке

### Подпись для `POST /api/device-attribution`

Строка для HMAC-SHA256 (hex):

```text
message = f"{token}:{timestamp}:{slug}:{device_identifier or ''}"
signature = HMAC_SHA256(key=ATTRIBUTION_SHARED_SECRET, message=message).hexdigest()
```

- `timestamp` — Unix time в секундах; расхождение с сервером не больше **5 минут**.
- Без `ATTRIBUTION_SHARED_SECRET` сервер вернёт `401`.

Пример на Python:

```python
import hmac, hashlib, time, requests

secret = b"твой-секрет"
slug = "abc12345"
token = "one-time-token"
device_id = "optional-stable-id"
ts = int(time.time())
msg = f"{token}:{ts}:{slug}:{device_id}".encode()
sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()

r = requests.post(
    "https://твой-домен/api/device-attribution",
    json={
        "slug": slug,
        "token": token,
        "timestamp": ts,
        "signature": sig,
        "visitor_id": None,
        "device_identifier": device_id,
        "imei": "…",
        "serial_number": "…",
    },
)
print(r.status_code, r.json())
```

Корреляция с веб-кликом: передай тот же `visitor_id`, что в cookie `visitor_id` после перехода по короткой ссылке (cookie `HttpOnly`, читается только вашим приложением/мостом; на практике нативное приложение часто передаёт свой стабильный `device_identifier` и сопоставляет события на бэкенде по времени и ссылке).

## Структура проекта

```
.
├── main.py              # FastAPI приложение
├── static/
│   └── index.html       # Фронтенд дашборд
├── requirements.txt     # Python зависимости
├── Procfile             # Команда запуска для Railway
└── README.md            # Инструкция
```
