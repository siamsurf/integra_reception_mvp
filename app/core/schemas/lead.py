from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    service_type: str = Field(pattern="^(delivery|supplier_check)$")
    client_name: str
    phone: str
    email: str | None = None
    raw_text: str
