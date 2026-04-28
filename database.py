import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_click_schema() -> None:
    inspector = inspect(engine)

    # Старая схема хранила счётчик в links.clicks (NOT NULL). В текущем коде клики только в таблице
    # `clicks`; колонка не в модели → INSERT в links без неё даёт NULL и NotNullViolation в PostgreSQL.
    if "links" in inspector.get_table_names():
        link_columns = {col["name"] for col in inspector.get_columns("links")}
        if "clicks" in link_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE links DROP COLUMN clicks"))

    columns = {col["name"] for col in inspector.get_columns("clicks")}
    required_columns = {
        "device_family": "TEXT",
        "device_brand": "TEXT",
        "device_model": "TEXT",
        "browser_family": "TEXT",
        "geo_country": "TEXT",
        "geo_region": "TEXT",
        "geo_city": "TEXT",
        "farm_device_id": "TEXT",
        "enrichment_token": "TEXT",
    }
    with engine.begin() as conn:
        for column_name, column_type in required_columns.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE clicks ADD COLUMN {column_name} {column_type}"))

    if "device_attributions" in inspector.get_table_names():
        attr_columns = {col["name"] for col in inspector.get_columns("device_attributions")}
        if "farm_device_id" not in attr_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE device_attributions ADD COLUMN farm_device_id TEXT"))
