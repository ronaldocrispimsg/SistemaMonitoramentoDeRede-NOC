from sqlalchemy import Boolean, Column, Float, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from Backend.database import Base


class Host(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    address = Column(String)
    port = Column(Integer, nullable=True)

    active = Column(Boolean, default=True)
    active_time = Column(DateTime, nullable=True)

    status = Column(String)
    status_ping = Column(String)
    status_tcp = Column(String)

    latency_ping = Column(Float, nullable=True)
    latency_tcp = Column(Float, nullable=True)

    last_check = Column(DateTime)

    checks = relationship("CheckResult", back_populates="host")


class CheckResult(Base):
    __tablename__ = "checks"

    id = Column(Integer, primary_key=True, index=True)

    host_id = Column(Integer, ForeignKey("hosts.id"))
    host_name = Column(String)

    check_type = Column(String)

    success = Column(Boolean)
    latency = Column(Float, nullable=True)
    error = Column(String, nullable=True)

    timestamp = Column(DateTime, default=datetime.utcnow)

    host = relationship("Host", back_populates="checks")

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    host_id = Column(Integer)
    old_status = Column(String)
    new_status = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

class DNSCache(Base):
    __tablename__ = "dns_cache"

    id = Column(Integer, primary_key=True)
    hostname = Column(String, unique=True, index=True)

    ip_list = Column(String)          # json string dos IPs
    ttl = Column(Integer)

    resolved_at = Column(DateTime)
    expires_at = Column(DateTime)
