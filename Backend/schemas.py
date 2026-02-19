from pydantic import BaseModel
from typing import Optional

class HostCreate(BaseModel):
    name: str
    address: str
    port: Optional[int] = None

class HostUpdate(BaseModel):
    address: str
    port: Optional[int] = None

class HostCreate(BaseModel):
    name: str
    address: str
    port: Optional[int] = None
    http_url: Optional[str] = None