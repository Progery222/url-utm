import hashlib
import hmac
import ipaddress
import json
import os
from urllib.parse import quote
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func
from user_agents import parse

from database import SessionLocal, engine, ensure_click_schema
from device_uniqueness import build_device_uniqueness_report
from models import Base, Click, DeviceAttribution, Link

try:
    import geoip2.database
    from geoip2.errors import AddressNotFoundError
except Exception:  # pragma: no cover - optional dependency in some environments
    geoip2 = None

    class AddressNotFoundError(Exception):
        pass

DEFAULT_TARGET_URL = os.environ.get(
    "DEFAULT_TARGET_URL", "https://web-production-2bf7f.up.railway.app"
)
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "1"))
GEOIP_DB_PATH = os.environ.get("GEOIP_DB_PATH", "GeoLite2-City.mmdb")
ATTRIBUTION_SHARED_SECRET = os.environ.get("ATTRIBUTION_SHARED_SECRET", "")
FARM_ID_SIGNING_SECRET = os.environ.get("FARM_ID_SIGNING_SECRET", "")
CLIENT_HINTS_BRIDGE = os.environ.get("CLIENT_HINTS_BRIDGE", "1").lower() in ("1", "true", "yes")
API_KEY = os.environ.get("API_KEY", "")
FARM_DEVICE_ID_MAX_LEN = 256

app = FastAPI(title="URL Tracker")


@app.on_event("startup")
def _db_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_click_schema()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateLinkRequest(BaseModel):
    label: str


class LinkListItem(BaseModel):
    id: int
    slug: str
    target_url: str
    label: str
    total_clicks: int
    unique_visitors: int

    class Config:
        from_attributes = True


class DeviceAttributionPayload(BaseModel):
    slug: str
    token: str
    timestamp: int
    signature: str
    visitor_id: Optional[str] = None
    source: Optional[str] = None
    imei: Optional[str] = None
    serial_number: Optional[str] = None
    device_identifier: Optional[str] = None
    farm_device_id: Optional[str] = None


def _extract_forwarded_ip(header_value: str) -> Optional[str]:
    candidates = [item.strip() for item in header_value.split(",") if item.strip()]
    if not candidates:
        return None
    idx = len(candidates) - TRUSTED_PROXY_COUNT - 1
    if idx < 0:
        idx = 0
    candidate = candidates[idx]
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        return None


def get_real_client_ip(request: Request) -> Optional[str]:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = _extract_forwarded_ip(xff)
        if ip:
            return ip

    for header_name in ("cf-connecting-ip", "true-client-ip", "x-real-ip"):
        value = request.headers.get(header_name)
        if not value:
            continue
        try:
            ipaddress.ip_address(value.strip())
            return value.strip()
        except ValueError:
            continue

    if request.client and request.client.host:
        return request.client.host
    return None


def enrich_with_geo(ip_address: Optional[str]) -> dict:
    if not ip_address or not geoip2:
        return {"country": None, "region": None, "city": None}
    if not os.path.exists(GEOIP_DB_PATH):
        return {"country": None, "region": None, "city": None}

    try:
        with geoip2.database.Reader(GEOIP_DB_PATH) as reader:
            record = reader.city(ip_address)
            region_name = record.subdivisions.most_specific.name if record.subdivisions else None
            return {
                "country": record.country.name,
                "region": region_name,
                "city": record.city.name,
            }
    except (AddressNotFoundError, ValueError):
        return {"country": None, "region": None, "city": None}


def parse_device(ua_string: str) -> dict:
    device_type = "Unknown"
    os_family = "Unknown"
    device_family = None
    device_brand = None
    device_model = None
    browser_family = None
    if not ua_string:
        return {
            "device_type": device_type,
            "os_family": os_family,
            "device_family": device_family,
            "device_brand": device_brand,
            "device_model": device_model,
            "browser_family": browser_family,
        }

    try:
        ua = parse(ua_string)
        if ua.is_mobile:
            device_type = "Mobile"
        elif ua.is_tablet:
            device_type = "Tablet"
        elif ua.is_pc:
            device_type = "Desktop"
        else:
            device_type = "Other"

        os_family = ua.os.family or "Unknown"
        browser_family = ua.browser.family or None
        device_family = ua.device.family or None

        brand = getattr(ua.device, "brand", None)
        model = getattr(ua.device, "model", None)
        if brand:
            device_brand = brand
        if model:
            device_model = model
    except Exception:
        pass

    return {
        "device_type": device_type,
        "os_family": os_family,
        "device_family": device_family,
        "device_brand": device_brand,
        "device_model": device_model,
        "browser_family": browser_family,
    }


def model_from_client_hints(request: Request) -> Optional[str]:
    model = request.headers.get("sec-ch-ua-model")
    if not model:
        return None
    return model.strip().strip('"')


def hash_identifier(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.strip().encode()).hexdigest()


def is_valid_attribution_signature(
    token: str,
    timestamp: int,
    slug: str,
    device_identifier: Optional[str],
    signature: str,
) -> bool:
    if not ATTRIBUTION_SHARED_SECRET:
        return False
    payload = f"{token}:{timestamp}:{slug}:{device_identifier or ''}".encode()
    expected = hmac.new(ATTRIBUTION_SHARED_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_farm_device_id(request: Request) -> Optional[str]:
    raw = request.query_params.get("farm_id") or request.query_params.get("did")
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if len(raw) > FARM_DEVICE_ID_MAX_LEN:
        raw = raw[:FARM_DEVICE_ID_MAX_LEN]

    if FARM_ID_SIGNING_SECRET:
        farm_ts = request.query_params.get("farm_ts")
        farm_sig = request.query_params.get("farm_sig")
        if not farm_ts or not farm_sig:
            return None
        try:
            ts = int(farm_ts)
        except ValueError:
            return None
        now = int(datetime.now(tz=timezone.utc).timestamp())
        if abs(now - ts) > 86400:
            return None
        msg = f"{raw}:{farm_ts}".encode()
        expected = hmac.new(FARM_ID_SIGNING_SECRET.encode(), msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, farm_sig.lower()):
            return None

    return raw


def client_hints_bridge_page(click_id: int, enrich_token: str) -> HTMLResponse:
    path = json.dumps(f"/api/clicks/{click_id}/enrich")
    body = json.dumps({"token": enrich_token})
    script = f"""
fetch({path}, {{
  method: "POST",
  credentials: "same-origin",
  headers: {{ "Content-Type": "application/json" }},
  body: {body}
}})
  .then(r => r.json())
  .then(d => {{ if (d && d.next) location.replace(d.next); }})
  .catch(() => {{}});
"""
    page = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Redirect</title></head><body>"
        f"<script>{script}</script></body></html>"
    )
    return HTMLResponse(content=page, media_type="text/html; charset=utf-8")


@app.middleware("http")
async def enforce_api_key(request: Request, call_next):
    path = request.url.path
    if API_KEY and path.startswith("/api/"):
        if path.rstrip("/").endswith("/enrich") and "/clicks/" in path:
            return await call_next(request)
        if path.rstrip("/") == "/api/device-attribution":
            return await call_next(request)
        if request.headers.get("x-api-key") != API_KEY:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


class EnrichClickBody(BaseModel):
    token: str


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.post("/api/links", response_model=LinkListItem)
def create_link(payload: CreateLinkRequest):
    db = SessionLocal()
    try:
        slug = str(uuid.uuid4())[:8]
        link = Link(
            slug=slug,
            target_url=DEFAULT_TARGET_URL,
            label=payload.label,
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        return {
            "id": link.id,
            "slug": link.slug,
            "target_url": link.target_url,
            "label": link.label,
            "total_clicks": 0,
            "unique_visitors": 0,
        }
    finally:
        db.close()


@app.get("/api/links", response_model=List[LinkListItem])
def list_links():
    db = SessionLocal()
    try:
        links = db.query(Link).order_by(Link.id.desc()).all()
        result = []
        for link in links:
            total = db.query(func.count(Click.id)).filter(Click.link_id == link.id).scalar() or 0
            unique = db.query(func.count(func.distinct(Click.visitor_id))).filter(Click.link_id == link.id).scalar() or 0
            result.append({
                "id": link.id,
                "slug": link.slug,
                "target_url": link.target_url,
                "label": link.label,
                "total_clicks": total,
                "unique_visitors": unique,
            })
        return result
    finally:
        db.close()


def _link_stats_dict(db, link: Link) -> dict:
    total = db.query(func.count(Click.id)).filter(Click.link_id == link.id).scalar() or 0
    unique = db.query(func.count(func.distinct(Click.visitor_id))).filter(Click.link_id == link.id).scalar() or 0
    devices = db.query(Click.device_type, func.count(Click.id)).filter(Click.link_id == link.id).group_by(Click.device_type).all()
    os_stats = db.query(Click.os, func.count(Click.id)).filter(Click.link_id == link.id).group_by(Click.os).all()
    model_stats = (
        db.query(Click.device_model, func.count(Click.id))
        .filter(Click.link_id == link.id)
        .group_by(Click.device_model)
        .all()
    )
    region_stats = (
        db.query(Click.geo_region, func.count(Click.id))
        .filter(Click.link_id == link.id)
        .group_by(Click.geo_region)
        .all()
    )
    unique_farm_devices = (
        db.query(func.count(func.distinct(Click.farm_device_id)))
        .filter(
            Click.link_id == link.id,
            Click.farm_device_id.isnot(None),
            Click.farm_device_id != "",
        )
        .scalar()
        or 0
    )
    unique_ip_addresses = (
        db.query(func.count(func.distinct(Click.ip_address)))
        .filter(Click.link_id == link.id, Click.ip_address.isnot(None))
        .scalar()
        or 0
    )
    return {
        "total_clicks": total,
        "unique_visitors": unique,
        "unique_farm_devices": unique_farm_devices,
        "unique_ip_addresses": unique_ip_addresses,
        "devices": {d or "Unknown": c for d, c in devices},
        "os": {o or "Unknown": c for o, c in os_stats},
        "models": {m or "Unknown": c for m, c in model_stats},
        "regions": {r or "Unknown": c for r, c in region_stats},
    }


def _click_export_dict(click: Click) -> dict:
    return {
        "id": click.id,
        "visitor_id": click.visitor_id,
        "ip_address": click.ip_address,
        "user_agent": click.user_agent,
        "device_type": click.device_type,
        "os": click.os,
        "device_family": click.device_family,
        "device_brand": click.device_brand,
        "device_model": click.device_model,
        "browser_family": click.browser_family,
        "geo_country": click.geo_country,
        "geo_region": click.geo_region,
        "geo_city": click.geo_city,
        "farm_device_id": click.farm_device_id,
        "created_at": click.created_at.isoformat() if click.created_at else None,
    }


def _attribution_export_dict(item: DeviceAttribution) -> dict:
    return {
        "id": item.id,
        "visitor_id": item.visitor_id,
        "token": item.token,
        "source": item.source,
        "imei_hash": item.imei_hash,
        "serial_hash": item.serial_hash,
        "device_identifier_hash": item.device_identifier_hash,
        "farm_device_id": item.farm_device_id,
        "raw_payload": item.raw_payload,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@app.get("/api/links/{slug}/stats")
def link_stats(slug: str):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        return _link_stats_dict(db, link)
    finally:
        db.close()


@app.get("/api/links/{slug}/export")
def export_link_analytics(slug: str):
    """Полная выгрузка аналитики по ссылке (JSON для внешнего анализа, в т.ч. ИИ)."""
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        clicks_q = db.query(Click).filter(Click.link_id == link.id).order_by(Click.id.asc())
        clicks = clicks_q.all()
        stats = _link_stats_dict(db, link)
        device_uniqueness = build_device_uniqueness_report(clicks)
        clicks_data = [_click_export_dict(c) for c in clicks]

        attributions = (
            db.query(DeviceAttribution)
            .filter(DeviceAttribution.link_id == link.id)
            .order_by(DeviceAttribution.id.asc())
            .all()
        )
        attributions_data = [_attribution_export_dict(a) for a in attributions]

        exported_at = datetime.now(tz=timezone.utc).isoformat()
        payload = {
            "export_version": 1,
            "exported_at": exported_at,
            "link": {
                "id": link.id,
                "slug": link.slug,
                "label": link.label,
                "target_url": link.target_url,
            },
            "stats": stats,
            "device_uniqueness": device_uniqueness,
            "clicks": clicks_data,
            "device_attributions": attributions_data,
            "counts": {
                "clicks": len(clicks_data),
                "device_attributions": len(attributions_data),
            },
        }

        body = json.dumps(payload, ensure_ascii=False, indent=2)
        filename = f"url-tracker-{slug}-analytics.json"
        content_disp = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'

        return Response(
            content=body.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": content_disp},
        )
    finally:
        db.close()


@app.get("/api/links/{slug}/clicks")
def link_clicks(slug: str, limit: int = 50, offset: int = 0):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        query = db.query(Click).filter(Click.link_id == link.id).order_by(Click.id.desc())
        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        items = []
        for click in rows:
            items.append(
                {
                    "id": click.id,
                    "visitor_id": click.visitor_id,
                    "ip_address": click.ip_address,
                    "device_type": click.device_type,
                    "os": click.os,
                    "device_family": click.device_family,
                    "device_brand": click.device_brand,
                    "device_model": click.device_model,
                    "browser_family": click.browser_family,
                    "geo_country": click.geo_country,
                    "geo_region": click.geo_region,
                    "geo_city": click.geo_city,
                    "farm_device_id": click.farm_device_id,
                    "created_at": click.created_at.isoformat() if click.created_at else None,
                }
            )
        return {"total": total, "limit": limit, "offset": offset, "items": items}
    finally:
        db.close()


@app.get("/api/links/{slug}/device-uniqueness")
def link_device_uniqueness(slug: str):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        clicks = (
            db.query(Click)
            .filter(Click.link_id == link.id)
            .order_by(Click.id.asc())
            .all()
        )
        return build_device_uniqueness_report(clicks)
    finally:
        db.close()


@app.post("/api/clicks/{click_id}/enrich")
def enrich_click_with_client_hints(click_id: int, body: EnrichClickBody, request: Request):
    db = SessionLocal()
    try:
        click = db.query(Click).filter(Click.id == click_id).first()
        if not click or not click.enrichment_token or click.enrichment_token != body.token:
            raise HTTPException(status_code=404, detail="Not found")

        hinted = model_from_client_hints(request)
        if hinted:
            click.device_model = hinted
        plat = request.headers.get("sec-ch-ua-platform")
        if plat:
            plat = plat.strip().strip('"')
            if plat and (not click.os or click.os == "Unknown"):
                click.os = plat

        link_row = db.query(Link).filter(Link.id == click.link_id).first()
        if not link_row:
            raise HTTPException(status_code=404, detail="Link not found")
        target = link_row.target_url

        click.enrichment_token = None
        db.commit()
        return {"ok": True, "next": target}
    finally:
        db.close()


@app.post("/api/device-attribution")
def ingest_device_attribution(payload: DeviceAttributionPayload):
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    if abs(now_ts - payload.timestamp) > 300:
        raise HTTPException(status_code=400, detail="Expired attribution payload")
    if not is_valid_attribution_signature(
        token=payload.token,
        timestamp=payload.timestamp,
        slug=payload.slug,
        device_identifier=payload.device_identifier,
        signature=payload.signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == payload.slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        farm_id_val = (payload.farm_device_id or "").strip()
        if farm_id_val and len(farm_id_val) > FARM_DEVICE_ID_MAX_LEN:
            farm_id_val = farm_id_val[:FARM_DEVICE_ID_MAX_LEN]

        record = DeviceAttribution(
            link_id=link.id,
            visitor_id=payload.visitor_id,
            token=payload.token,
            source=payload.source or "app",
            imei_hash=hash_identifier(payload.imei),
            serial_hash=hash_identifier(payload.serial_number),
            device_identifier_hash=hash_identifier(payload.device_identifier),
            farm_device_id=farm_id_val or None,
            raw_payload=json.dumps(payload.model_dump(mode="json"), ensure_ascii=True),
        )
        db.add(record)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/links/{slug}/attributions")
def list_device_attributions(slug: str, limit: int = 50, offset: int = 0):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        query = db.query(DeviceAttribution).filter(DeviceAttribution.link_id == link.id).order_by(DeviceAttribution.id.desc())
        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        items = []
        for item in rows:
            items.append(
                {
                    "id": item.id,
                    "visitor_id": item.visitor_id,
                    "token": item.token,
                    "source": item.source,
                    "imei_hash": item.imei_hash,
                    "serial_hash": item.serial_hash,
                    "device_identifier_hash": item.device_identifier_hash,
                    "farm_device_id": item.farm_device_id,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
            )
        return {"total": total, "limit": limit, "offset": offset, "items": items}
    finally:
        db.close()


@app.post("/api/links/{slug}/reset", response_model=LinkListItem)
def reset_clicks(slug: str):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        db.query(Click).filter(Click.link_id == link.id).delete()
        db.commit()
        db.refresh(link)
        return {
            "id": link.id,
            "slug": link.slug,
            "target_url": link.target_url,
            "label": link.label,
            "total_clicks": 0,
            "unique_visitors": 0,
        }
    finally:
        db.close()


@app.delete("/api/links/{slug}")
def delete_link(slug: str):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        db.delete(link)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/{slug}")
def redirect(slug: str, request: Request):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        farm_device_id = parse_farm_device_id(request)

        visitor_id = request.cookies.get("visitor_id")
        real_ip = get_real_client_ip(request)
        if not visitor_id:
            ua_string = request.headers.get("user-agent", "")
            ip = real_ip or "unknown"
            fallback_hash = hashlib.sha256(f"{ip}:{ua_string}".encode()).hexdigest()[:16]
            visitor_id = f"fb-{fallback_hash}"

        ua_string = request.headers.get("user-agent", "")
        device_data = parse_device(ua_string)
        hinted_model = model_from_client_hints(request)
        if hinted_model:
            device_data["device_model"] = hinted_model
        geo = enrich_with_geo(real_ip)

        enrich_tok = secrets.token_urlsafe(18) if CLIENT_HINTS_BRIDGE else None

        click = Click(
            link_id=link.id,
            ip_address=real_ip,
            user_agent=ua_string,
            device_type=device_data["device_type"],
            os=device_data["os_family"],
            device_family=device_data["device_family"],
            device_brand=device_data["device_brand"],
            device_model=device_data["device_model"],
            browser_family=device_data["browser_family"],
            geo_country=geo["country"],
            geo_region=geo["region"],
            geo_city=geo["city"],
            farm_device_id=farm_device_id,
            enrichment_token=enrich_tok,
            visitor_id=visitor_id,
        )
        db.add(click)
        db.commit()
        db.refresh(click)

        if CLIENT_HINTS_BRIDGE and enrich_tok:
            resp = client_hints_bridge_page(click.id, enrich_tok)
        else:
            resp = RedirectResponse(url=link.target_url)

        resp.headers["Accept-CH"] = "Sec-CH-UA-Model, Sec-CH-UA-Platform, Sec-CH-UA-Mobile"
        resp.headers["Critical-CH"] = "Sec-CH-UA-Model"
        resp.headers["Vary"] = "Sec-CH-UA-Model, Sec-CH-UA-Platform, Sec-CH-UA-Mobile"
        if not request.cookies.get("visitor_id"):
            resp.set_cookie(
                key="visitor_id",
                value=visitor_id,
                max_age=31536000,
                httponly=True,
                samesite="lax",
            )
        return resp
    finally:
        db.close()


app.mount("/static", StaticFiles(directory="static"), name="static")
