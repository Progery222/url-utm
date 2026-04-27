import os
import uuid
import hashlib
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from user_agents import parse

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

DEFAULT_TARGET_URL = os.environ.get(
    "DEFAULT_TARGET_URL", "https://web-production-2bf7f.up.railway.app"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    target_url = Column(String, nullable=False)
    label = Column(String, nullable=False)

    clicks_rel = relationship("Click", backref="link", cascade="all, delete-orphan")


class Click(Base):
    __tablename__ = "clicks"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("links.id", ondelete="CASCADE"), nullable=False, index=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    device_type = Column(String, nullable=True)
    os = Column(String, nullable=True)
    visitor_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="URL Tracker")

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


@app.get("/api/links/{slug}/stats")
def link_stats(slug: str):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        total = db.query(func.count(Click.id)).filter(Click.link_id == link.id).scalar() or 0
        unique = db.query(func.count(func.distinct(Click.visitor_id))).filter(Click.link_id == link.id).scalar() or 0
        devices = db.query(Click.device_type, func.count(Click.id)).filter(Click.link_id == link.id).group_by(Click.device_type).all()
        os_stats = db.query(Click.os, func.count(Click.id)).filter(Click.link_id == link.id).group_by(Click.os).all()
        return {
            "total_clicks": total,
            "unique_visitors": unique,
            "devices": {d or "Unknown": c for d, c in devices},
            "os": {o or "Unknown": c for o, c in os_stats},
        }
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

        visitor_id = request.cookies.get("visitor_id")
        if not visitor_id:
            ua_string = request.headers.get("user-agent", "")
            ip = request.client.host if request.client else "unknown"
            fallback_hash = hashlib.sha256(f"{ip}:{ua_string}".encode()).hexdigest()[:16]
            visitor_id = f"fb-{fallback_hash}"

        ua_string = request.headers.get("user-agent", "")
        device_type = "Unknown"
        os_family = "Unknown"
        if ua_string:
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
            except Exception:
                pass

        ip = request.client.host if request.client else None

        click = Click(
            link_id=link.id,
            ip_address=ip,
            user_agent=ua_string,
            device_type=device_type,
            os=os_family,
            visitor_id=visitor_id,
        )
        db.add(click)
        db.commit()

        response = RedirectResponse(url=link.target_url)
        if not request.cookies.get("visitor_id"):
            response.set_cookie(
                key="visitor_id",
                value=visitor_id,
                max_age=31536000,
                httponly=True,
                samesite="lax",
            )
        return response
    finally:
        db.close()


app.mount("/static", StaticFiles(directory="static"), name="static")
