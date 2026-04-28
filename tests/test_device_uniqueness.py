from datetime import datetime, timezone
from types import SimpleNamespace

from device_uniqueness import build_device_uniqueness_report


def click(**overrides):
    values = {
        "id": 1,
        "farm_device_id": "device_01",
        "ip_address": "203.0.113.10",
        "user_agent": "Mozilla/5.0 Android Chrome",
        "os": "Android",
        "device_family": "Pixel",
        "device_brand": "Google",
        "device_model": "Pixel 7",
        "browser_family": "Chrome",
        "geo_country": "United States",
        "geo_region": "California",
        "geo_city": "San Francisco",
        "created_at": datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_marks_devices_with_same_observed_fingerprint_as_duplicates():
    report = build_device_uniqueness_report(
        [
            click(id=1, farm_device_id="device_01"),
            click(id=2, farm_device_id="device_02"),
        ]
    )

    assert report["tested_devices"] == 2
    assert report["unique_devices"] == 0
    assert report["duplicate_devices"] == 2
    assert [group["farm_device_ids"] for group in report["duplicate_groups"]] == [
        ["device_01", "device_02"]
    ]
    statuses = {item["farm_device_id"]: item["status"] for item in report["devices"]}
    assert statuses == {"device_01": "duplicate", "device_02": "duplicate"}


def test_marks_devices_with_different_observed_fingerprints_as_unique():
    report = build_device_uniqueness_report(
        [
            click(id=1, farm_device_id="device_01", ip_address="203.0.113.10"),
            click(id=2, farm_device_id="device_02", ip_address="198.51.100.20"),
        ]
    )

    assert report["tested_devices"] == 2
    assert report["unique_devices"] == 2
    assert report["duplicate_devices"] == 0
    assert report["duplicate_groups"] == []
    assert {item["status"] for item in report["devices"]} == {"unique"}


def test_uses_latest_click_for_each_farm_device_id():
    older = click(
        id=1,
        farm_device_id="device_01",
        ip_address="203.0.113.10",
        created_at=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
    )
    latest = click(
        id=2,
        farm_device_id="device_01",
        ip_address="198.51.100.20",
        created_at=datetime(2026, 4, 28, 12, 5, tzinfo=timezone.utc),
    )

    report = build_device_uniqueness_report([older, latest])

    assert report["tested_devices"] == 1
    assert report["devices"][0]["ip_address"] == "198.51.100.20"
    assert report["devices"][0]["click_count"] == 2


def test_counts_untagged_clicks_without_participating_in_uniqueness_groups():
    report = build_device_uniqueness_report(
        [
            click(id=1, farm_device_id=None),
            click(id=2, farm_device_id=""),
            click(id=3, farm_device_id="device_01"),
        ]
    )

    assert report["untagged_clicks"] == 2
    assert report["tested_devices"] == 1
    assert report["unique_devices"] == 1
    assert report["duplicate_groups"] == []
