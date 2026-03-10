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
    deleted_at = Column(DateTime, nullable=True)
    baseline_pending = Column(Boolean, default=True, nullable=False)

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
    last_preventive_alert = Column(DateTime, nullable=True)

    cpu_usage = Column(Float, nullable=True)
    ram_usage = Column(Float, nullable=True)
    disk_usage = Column(Float, nullable=True)
    disk_remaining = Column(Float, nullable=True)
    network_traffic = Column(Float, nullable=True)
    network_in_bps = Column(Float, nullable=True)
    network_out_bps = Column(Float, nullable=True)

    last_net_in_octets = Column(Float, nullable=True)
    last_net_out_octets = Column(Float, nullable=True)
    last_net_check = Column(DateTime, nullable=True)
    snmp_community = Column(String, default="noc-lite")
    last_snmp_check = Column(DateTime, nullable=True)

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
    status_code = Column(Integer, nullable=True)
    
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

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    host_name = Column(String, index=True)
    status = Column(String, default="OPEN")
    reason = Column(String)
    started_time = Column(DateTime, default=datetime.utcnow)
    ended_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

class DNSCache(Base):
    __tablename__ = "dns_cache"

    id = Column(Integer, primary_key=True)
    hostname = Column(String, unique=True, index=True)

    ip_list = Column(String)
    ttl = Column(Integer)

    resolved_time = Column(DateTime)
    expires_time = Column(DateTime)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    attempts = Column(Integer, default=0)
    locked = Column(Boolean, default=False)
    must_change_password = Column(Boolean, default=True)
    locked_until = Column(DateTime, nullable=True)

class SNMPMetric(Base):
    __tablename__ = "snmp_metrics"

    id = Column(Integer, primary_key=True)

    host_id = Column(Integer)
    cpu = Column(Float)
    ram = Column(Float)
    disk = Column(Float)
    network_in_bps = Column(Float, nullable=True)
    network_out_bps = Column(Float, nullable=True)
    network_total_bps = Column(Float, nullable=True)

    timestamp = Column(DateTime, default=datetime.utcnow)
