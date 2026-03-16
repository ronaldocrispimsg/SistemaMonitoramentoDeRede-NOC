from pydantic import BaseModel
from typing import Optional, List

class LoginRequest(BaseModel):
    username: str
    password: str

class PasswordChangeRequest(BaseModel):
    current_password: Optional[str] = None
    new_password: str

class HostUpdate(BaseModel):
    address: str
    port: Optional[int] = None
    ports: Optional[List[int]] = None
    url: Optional[str] = None
    http_url: Optional[str] = None
    http_enabled: Optional[bool] = None
    snmp_enabled: Optional[bool] = None

class HostCreate(BaseModel):
    name: str
    address: str
    port: Optional[int] = None
    ports: Optional[List[int]] = None
    url: Optional[str] = None
    http_url: Optional[str] = None
    http_enabled: bool = True
    snmp_enabled: bool = False


class NetworkDiscoveryRequest(BaseModel):
    subnet: str


class NetworkImportHostItem(BaseModel):
    name: str
    address: str


class NetworkImportRequest(BaseModel):
    hosts: List[NetworkImportHostItem]
