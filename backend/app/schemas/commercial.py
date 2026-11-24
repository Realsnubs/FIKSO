import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.public import Language, LocalizedText, Money


class CommercialTermsIn(BaseModel):
    hourly_rate_eur: Money = Field(gt=0)
    minimum_order_eur: Money
    materials_note: LocalizedText
    reason: str = Field(min_length=3, max_length=500)


class CommercialTermsOut(BaseModel):
    id: uuid.UUID
    hourly_rate_eur: Decimal
    minimum_order_eur: Decimal
    materials_note: LocalizedText
    effective_from: datetime
    reason: str | None
    created_at: datetime


class PublicTermsOut(BaseModel):
    hourly_rate_eur: Decimal
    minimum_order_eur: Decimal
    materials_note: str
    materials_note_lang: Language
