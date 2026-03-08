from pydantic import BaseModel
from typing import Optional

class HostUpdate(BaseModel):
    address: str
    port: Optional[int] = None
    http_url: Optional[str] = None

class HostCreate(BaseModel):
    name: str
    address: str
    port: Optional[int] = None
    http_url: Optional[str] = None