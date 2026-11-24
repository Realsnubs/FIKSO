import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.public import Language

RightsBasis = Literal["own", "client_consent", "licence"]


class MediaOut(BaseModel):
    id: uuid.UUID
    width: int
    height: int
    urls: dict[str, str]
    alt: dict[str, str]
    status: str
    rights_basis: RightsBasis
    rights_reference: str | None
    consent_given_on: date | None
    consent_withdrawn_at: datetime | None
    created_at: datetime


class MediaArchiveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PageText(BaseModel):
    """One language of a page (OQ-7 limits). Plain text only — the frontend escapes it."""

    title: str | None = Field(default=None, max_length=120)
    lead: str | None = Field(default=None, max_length=600)
    can_do: list[str] = Field(default_factory=list, max_length=30)
    prepare: list[str] = Field(default_factory=list, max_length=30)
    faq: list["FaqPair"] = Field(default_factory=list, max_length=30)
    seo_title: str | None = Field(default=None, max_length=120)
    seo_description: str | None = Field(default=None, max_length=300)
    name: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _items(self) -> "PageText":
        for item in [*self.can_do, *self.prepare]:
            if not item.strip() or len(item) > 300:
                raise ValueError("Each list item must be 1–300 characters.")
        return self


class FaqPair(BaseModel):
    q: str = Field(min_length=1, max_length=300)
    a: str = Field(min_length=1, max_length=600)


class GalleryImage(BaseModel):
    media_id: uuid.UUID
    kind: Literal["before", "after"] = "after"
    caption: dict[Language, str] = Field(default_factory=dict)


class ContentData(BaseModel):
    locales: dict[Language, PageText] = Field(default_factory=dict)
    card_image: uuid.UUID | None = None
    gallery: list[GalleryImage] = Field(default_factory=list, max_length=12)
    # Service descriptions and name translations, keyed by catalogue service ID.
    services: dict[uuid.UUID, dict[Language, str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _service_texts(self) -> "ContentData":
        for texts in self.services.values():
            for text in texts.values():
                if len(text) > 600:
                    raise ValueError("A service text may be at most 600 characters.")
        return self


class ContentDraftIn(BaseModel):
    data: ContentData
    expected_version: int


class ContentSlugIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    expected_version: int


class ContentActionIn(BaseModel):
    expected_version: int


class ContentVersionOut(BaseModel):
    id: uuid.UUID
    version_no: int
    state: str
    data: ContentData
    created_at: datetime
    updated_at: datetime | None
    published_at: datetime | None


class ContentOut(BaseModel):
    id: uuid.UUID
    specialisation_id: uuid.UUID
    specialisation_name: str
    slug: str
    version: int
    published_version_no: int | None
    draft: ContentVersionOut | None
    published: ContentVersionOut | None
    history: list[ContentVersionOut]


class ContentListItem(BaseModel):
    specialisation_id: uuid.UUID
    specialisation_name: str
    category_name: str
    status: str
    content_id: uuid.UUID | None
    slug: str | None
    has_draft: bool
    published: bool
