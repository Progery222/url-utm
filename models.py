from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

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
    device_family = Column(String, nullable=True)
    device_brand = Column(String, nullable=True)
    device_model = Column(String, nullable=True)
    browser_family = Column(String, nullable=True)
    geo_country = Column(String, nullable=True)
    geo_region = Column(String, nullable=True)
    geo_city = Column(String, nullable=True)
    farm_device_id = Column(String, nullable=True, index=True)
    enrichment_token = Column(String, nullable=True, index=True)
    visitor_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class DeviceAttribution(Base):
    __tablename__ = "device_attributions"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("links.id", ondelete="CASCADE"), nullable=False, index=True)
    visitor_id = Column(String, nullable=True, index=True)
    token = Column(String, nullable=False)
    source = Column(String, nullable=True)
    imei_hash = Column(String, nullable=True)
    serial_hash = Column(String, nullable=True)
    device_identifier_hash = Column(String, nullable=True)
    farm_device_id = Column(String, nullable=True, index=True)
    raw_payload = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
