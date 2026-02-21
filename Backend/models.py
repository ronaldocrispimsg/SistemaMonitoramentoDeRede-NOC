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
    http_url = Column(String, nullable=True)

    active = Column(Boolean, default=True)
    active_time = Column(DateTime, nullable=True)

    last_resolved_ip = Column(String, nullable=True)
    hostname_resolved = Column(String, nullable=True)

    status = Column(String)
    status_ping = Column(String)
    status_tcp = Column(String)

    fail_streak = Column(Integer, default=0)
    success_streak = Column(Integer, default=0)
    dns_ttl = Column(Integer, nullable=True)
    dns_ttl_remaining = Column(Integer, nullable=True)
    last_ttl_alert = Column(DateTime, nullable=True)

    latency_ping = Column(Float, nullable=True)
    latency_tcp = Column(Float, nullable=True)

    last_check = Column(DateTime)

    checks = relationship("CheckResult", back_populates="host")
    health_score = Column(Integer, default=0)
    severity = Column(String, default="UNKNOWN")
    
    sla_rolling_ping = Column(Float, nullable=True)
    sla_rolling_tcp = Column(Float, nullable=True)
    sla_rolling_http = Column(Float, nullable=True)

    jitter_ms_ping = Column(Float, nullable=True)
    jitter_ms_tcp = Column(Float, nullable=True)
    jitter_ms_http = Column(Float, nullable=True)
    
    slope = Column(Float, nullable=True)
    trend = Column(String, default="UNKNOWN")

    slope_http = Column(Float, nullable=True)
    trend_http = Column(String, default="UNKNOWN")



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
    alert_type = Column(String)

    old_status = Column(String)
    new_status = Column(String)

    timestamp = Column(DateTime, default=datetime.utcnow)

class DNSCache(Base):
    __tablename__ = "dns_cache"

    id = Column(Integer, primary_key=True)
    hostname = Column(String, unique=True, index=True)

    ip_list = Column(String)
    ttl = Column(Integer)

    resolved_time = Column(DateTime)
    expires_time = Column(DateTime)
