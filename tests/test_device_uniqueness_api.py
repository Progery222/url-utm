import importlib
import os
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def load_app(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'tracker.db'}"
    os.environ["CLIENT_HINTS_BRIDGE"] = "0"
    os.environ["API_KEY"] = ""
    for name in ["main", "database", "models"]:
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return main


def test_device_uniqueness_endpoint_returns_summary_devices_and_duplicate_groups(tmp_path):
    main = load_app(tmp_path)
    main.Base.metadata.create_all(bind=main.engine)
    client = TestClient(main.app)

    with main.SessionLocal() as db:
        link = main.Link(slug="abc12345", target_url="https://example.com", label="Test")
        db.add(link)
        db.commit()
        db.refresh(link)
        db.add_all(
            [
                main.Click(
                    link_id=link.id,
                    visitor_id="v1",
                    farm_device_id="device_01",
                    ip_address="203.0.113.10",
                    user_agent="UA",
                    os="Android",
                    device_family="Pixel",
                    device_brand="Google",
                    device_model="Pixel 7",
                    browser_family="Chrome",
                    geo_country="United States",
                    geo_region="California",
                    geo_city="San Francisco",
                    created_at=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
                ),
                main.Click(
                    link_id=link.id,
                    visitor_id="v2",
                    farm_device_id="device_02",
                    ip_address="203.0.113.10",
                    user_agent="UA",
                    os="Android",
                    device_family="Pixel",
                    device_brand="Google",
                    device_model="Pixel 7",
                    browser_family="Chrome",
                    geo_country="United States",
                    geo_region="California",
                    geo_city="San Francisco",
                    created_at=datetime(2026, 4, 28, 12, 1, tzinfo=timezone.utc),
                ),
                main.Click(
                    link_id=link.id,
                    visitor_id="v3",
                    farm_device_id=None,
                    ip_address="198.51.100.20",
                    user_agent="Other UA",
                    created_at=datetime(2026, 4, 28, 12, 2, tzinfo=timezone.utc),
                ),
            ]
        )
        db.commit()

    response = client.get("/api/links/abc12345/device-uniqueness")

    assert response.status_code == 200
    body = response.json()
    assert body["tested_devices"] == 2
    assert body["unique_devices"] == 0
    assert body["duplicate_devices"] == 2
    assert body["untagged_clicks"] == 1
    assert [item["farm_device_id"] for item in body["devices"]] == [
        "device_01",
        "device_02",
    ]
    assert body["devices"][0]["ip_address"] == "203.0.113.10"
    assert body["devices"][0]["status"] == "duplicate"
    assert body["devices"][0]["matches"] == ["device_02"]
    assert body["duplicate_groups"][0]["farm_device_ids"] == ["device_01", "device_02"]


def test_export_analytics_json(tmp_path):
    main = load_app(tmp_path)
    main.Base.metadata.create_all(bind=main.engine)
    client = TestClient(main.app)

    with main.SessionLocal() as db:
        link = main.Link(slug="export01", target_url="https://example.com", label="Export test")
        db.add(link)
        db.commit()
        db.refresh(link)
        db.add(
            main.Click(
                link_id=link.id,
                visitor_id="v1",
                farm_device_id="dev_a",
                ip_address="198.51.100.1",
                user_agent="TestAgent/1",
                os="Android",
                device_model="Pixel",
                geo_region="TestRegion",
            )
        )
        db.commit()

    response = client.get("/api/links/export01/export")

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/json")
    assert "attachment" in (response.headers.get("content-disposition") or "").lower()

    data = response.json()
    assert data["export_version"] == 1
    assert data["link"]["slug"] == "export01"
    assert data["link"]["label"] == "Export test"
    assert data["counts"]["clicks"] == 1
    assert len(data["clicks"]) == 1
    assert data["clicks"][0]["farm_device_id"] == "dev_a"
    assert data["clicks"][0]["user_agent"] == "TestAgent/1"
    assert data["device_uniqueness"]["tested_devices"] == 1
    assert data["stats"]["total_clicks"] == 1
