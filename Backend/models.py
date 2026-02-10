from sqlalchemy import Column, Float, Integer, String, DateTime
from datetime import datetime
from Backend.database import Base

class Host(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    address = Column(String)
    port = Column(Integer, nullable=True)
    status = Column(String, default="UNKNOWN")
    last_check = Column(DateTime, nullable=True)


class CheckResult(Base):
    __tablename__ = "checks"

    id = Column(Integer, primary_key=True, index=True)
    host_name = Column(String)
    success = Column(String)
    latency = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
