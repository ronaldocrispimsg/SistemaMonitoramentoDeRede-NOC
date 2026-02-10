from pydantic import BaseModel
from typing import Optional

class HostCreate(BaseModel):
    name: str
    address: str
    port: Optional[int] = None
