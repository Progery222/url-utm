# URL Tracker

Минималистичный сервис для создания коротких ссылок и отслеживания переходов.

## Стек

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy + PostgreSQL
- HTML + Tailwind CSS (CDN)

## Локальный запуск

```bash
# Установка зависимостей
pip install -r requirements.txt

# Переменная окружения
export DATABASE_URL="postgresql://user:pass@localhost:5432/urltracker"

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
- Добавь переменную:
  - `DATABASE_URL` → скопируй значение из сервиса PostgreSQL (раздел Variables базы). Формат: `postgresql://...`
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

- `POST /api/links` — создать ссылку (`target_url`, `label`)
- `GET /api/links` — список всех ссылок со статистикой
- `GET /{slug}` — переход по короткой ссылке (редирект + +1 клик)

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
