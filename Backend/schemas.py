from pydantic import BaseModel
from typing import Optional

class LoginRequest(BaseModel):
    username: str
    password: str

class PasswordChangeRequest(BaseModel):
    current_password: Optional[str] = None
    new_password: str

class HostUpdate(BaseModel):
    address: str
    port: Optional[int] = None
    http_url: Optional[str] = None
    snmp_enabled: Optional[bool] = None

class HostCreate(BaseModel):
    name: str
    address: str
    port: Optional[int] = None
    http_url: Optional[str] = None
    snmp_enabled: bool = False
