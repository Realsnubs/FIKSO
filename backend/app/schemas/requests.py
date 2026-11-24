import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

RequestType = Literal["immediate", "reserved"]


class RequestCreateIn(BaseModel):
    w_id: str = Field(pattern=r"^[Ww]\d{3,5}$")
    description: str = Field(min_length=10, max_length=2000)
    request_type: RequestType = "immediate"
    preferred_time_from: datetime | None = None
    preferred_time_to: datetime | None = None
    address: str = Field(min_length=5, max_length=300)
    flat: str | None = Field(default=None, max_length=40)
    access_info: str | None = Field(default=None, max_length=500)
    # Optional point from the device ("use my location"); otherwise the address is geocoded.
    lat: Decimal | None = Field(default=None, ge=-90, le=90, decimal_places=6)
    lon: Decimal | None = Field(default=None, ge=-180, le=180, decimal_places=6)
    src: str | None = Field(default=None, max_length=20)
    # City of the job (required for city-based matching) and the client's communication language ("any" or a
    # code from /public/communication-languages; never derived from the interface language).
    city: str = Field(min_length=2, max_length=40)
    communication_language: str = Field(default="any", min_length=2, max_length=10)

    @field_validator("description", "address")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _window(self) -> "RequestCreateIn":
        if len(self.description) < 10:
            raise ValueError("The description must be 10–2000 characters.")
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Give both coordinates or none.")
        if self.request_type == "reserved":
            if not (self.preferred_time_from and self.preferred_time_to):
                raise ValueError("A reservation needs a preferred time window.")
            if self.preferred_time_to <= self.preferred_time_from:
                raise ValueError("The time window must end after it starts.")
            for value in (self.preferred_time_from, self.preferred_time_to):
                if value.tzinfo is None:
                    raise ValueError("Times need a time zone.")
        else:
            self.preferred_time_from = self.preferred_time_to = None
        return self


class RequestUpdateIn(BaseModel):
    description: str | None = Field(default=None, min_length=10, max_length=2000)
    access_info: str | None = Field(default=None, max_length=500)
    flat: str | None = Field(default=None, max_length=40)
    expected_version: int


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class PhotoOut(BaseModel):
    id: uuid.UUID
    size_bytes: int
    uploaded_at: datetime


class ServiceRef(BaseModel):
    id: uuid.UUID
    w_id: str
    name: str
    specialisation: str
    category: str


class ProposalMaster(BaseModel):
    """What the client sees about a proposed master — no contacts and no exact location before assignment."""

    candidate_id: uuid.UUID
    role: Literal["proposal", "alternative"]
    first_name: str
    description: str | None
    rating_avg: Decimal | None
    rating_count: int
    completed_jobs: int
    eta_minutes: int
    distance_km: Decimal


class ProposalOut(BaseModel):
    round: int
    expires_at: datetime
    masters: list[ProposalMaster]


class OrderSummary(BaseModel):
    id: uuid.UUID
    status: str
    master_name: str
    master_phone: str | None
    offered_at: datetime
    accepted_at: datetime | None
    en_route_at: datetime | None
    arrived_at: datetime | None
    work_started_at: datetime | None
    work_completed_at: datetime | None
    completed_at: datetime | None
    estimated_start: datetime
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    master_location: dict[str, float] | None
    labour_amount_eur: Decimal | None
    materials_amount_eur: Decimal | None
    billable_minutes: int | None
    work_description: str | None
    review_rating: int | None


class RequestOut(BaseModel):
    id: uuid.UUID
    status: str
    unserved_reason: str | None
    service: ServiceRef
    description: str
    request_type: RequestType
    preferred_time_from: datetime | None
    preferred_time_to: datetime | None
    address: str
    flat: str | None
    access_info: str | None
    geocode_source: str
    city: dict[str, Any] | None
    communication_language: str
    source: str
    current_round: int
    photos: list[PhotoOut]
    created_at: datetime
    submitted_at: datetime | None
    cancelled_at: datetime | None
    version: int
    proposal: ProposalOut | None = None
    order: OrderSummary | None = None


class RequestListItem(BaseModel):
    id: uuid.UUID
    status: str
    w_id: str
    service_name: str
    created_at: datetime
    order_status: str | None
