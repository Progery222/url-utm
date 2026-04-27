import os
import uuid
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    target_url = Column(String, nullable=False)
    label = Column(String, nullable=False)
    clicks = Column(Integer, default=0, nullable=False)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="URL Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateLinkRequest(BaseModel):
    target_url: HttpUrl
    label: str


class LinkResponse(BaseModel):
    id: int
    slug: str
    target_url: str
    label: str
    clicks: int

    class Config:
        from_attributes = True


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.post("/api/links", response_model=LinkResponse)
def create_link(payload: CreateLinkRequest):
    db = SessionLocal()
    try:
        slug = str(uuid.uuid4())[:8]
        link = Link(
            slug=slug,
            target_url=str(payload.target_url),
            label=payload.label,
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        return link
    finally:
        db.close()


@app.get("/api/links", response_model=List[LinkResponse])
def list_links():
    db = SessionLocal()
    try:
        return db.query(Link).order_by(Link.id.desc()).all()
    finally:
        db.close()


@app.get("/{slug}")
def redirect(slug: str):
    db = SessionLocal()
    try:
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        link.clicks += 1
        db.commit()
        return RedirectResponse(url=link.target_url)
    finally:
        db.close()


app.mount("/static", StaticFiles(directory="static"), name="static")
