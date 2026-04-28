from collections import defaultdict
from typing import Any, Iterable, Optional


FINGERPRINT_FIELDS = (
    "ip_address",
    "geo_country",
    "geo_region",
    "geo_city",
    "user_agent",
    "os",
    "device_family",
    "device_brand",
    "device_model",
    "browser_family",
)


def _value(click: Any, field: str) -> Optional[str]:
    value = getattr(click, field, None)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def device_fingerprint(click: Any) -> tuple[Optional[str], ...]:
    return tuple(_value(click, field) for field in FINGERPRINT_FIELDS)


def _created_at_value(click: Any) -> Any:
    return getattr(click, "created_at", None)


def _click_sort_key(click: Any) -> tuple[Any, int]:
    return (_created_at_value(click), int(getattr(click, "id", 0) or 0))


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _fingerprint_payload(fingerprint: tuple[Optional[str], ...]) -> dict[str, Optional[str]]:
    return dict(zip(FINGERPRINT_FIELDS, fingerprint))


def build_device_uniqueness_report(clicks: Iterable[Any]) -> dict[str, Any]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    untagged_clicks = 0

    for click in clicks:
        farm_device_id = _value(click, "farm_device_id")
        if not farm_device_id:
            untagged_clicks += 1
            continue
        grouped[farm_device_id].append(click)

    latest_by_device: dict[str, Any] = {}
    for farm_device_id, items in grouped.items():
        latest_by_device[farm_device_id] = max(items, key=_click_sort_key)

    devices_by_fingerprint: dict[tuple[Optional[str], ...], list[str]] = defaultdict(list)
    for farm_device_id, click in latest_by_device.items():
        devices_by_fingerprint[device_fingerprint(click)].append(farm_device_id)

    for farm_device_ids in devices_by_fingerprint.values():
        farm_device_ids.sort()

    devices = []
    for farm_device_id in sorted(latest_by_device):
        click = latest_by_device[farm_device_id]
        fingerprint = device_fingerprint(click)
        matches = [
            item for item in devices_by_fingerprint[fingerprint] if item != farm_device_id
        ]
        status = "duplicate" if matches else "unique"
        devices.append(
            {
                "farm_device_id": farm_device_id,
                "status": status,
                "matches": matches,
                "click_count": len(grouped[farm_device_id]),
                "last_click_id": getattr(click, "id", None),
                "last_seen_at": _iso(_created_at_value(click)),
                "ip_address": _value(click, "ip_address"),
                "geo_country": _value(click, "geo_country"),
                "geo_region": _value(click, "geo_region"),
                "geo_city": _value(click, "geo_city"),
                "user_agent": _value(click, "user_agent"),
                "os": _value(click, "os"),
                "device_family": _value(click, "device_family"),
                "device_brand": _value(click, "device_brand"),
                "device_model": _value(click, "device_model"),
                "browser_family": _value(click, "browser_family"),
                "fingerprint": _fingerprint_payload(fingerprint),
            }
        )

    duplicate_groups = []
    for fingerprint, farm_device_ids in devices_by_fingerprint.items():
        if len(farm_device_ids) < 2:
            continue
        duplicate_groups.append(
            {
                "farm_device_ids": farm_device_ids,
                "fingerprint": _fingerprint_payload(fingerprint),
            }
        )
    duplicate_groups.sort(key=lambda item: item["farm_device_ids"][0])

    duplicate_devices = sum(1 for item in devices if item["status"] == "duplicate")

    return {
        "tested_devices": len(devices),
        "unique_devices": len(devices) - duplicate_devices,
        "duplicate_devices": duplicate_devices,
        "untagged_clicks": untagged_clicks,
        "devices": devices,
        "duplicate_groups": duplicate_groups,
    }
