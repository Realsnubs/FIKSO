"""Shared building blocks of the Stage C/D schemas."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

Language = Literal["lv", "en", "ru"]
LANGUAGES: tuple[Language, ...] = ("lv", "en", "ru")
Money = Annotated[Decimal, Field(ge=0, le=Decimal("100000"), max_digits=12, decimal_places=2)]


class LocalizedText(BaseModel):
    """Latvian is the source and required; EN/RU only when an approved translation exists (OQ-6)."""

    lv: str = Field(min_length=1, max_length=600)
    en: str | None = Field(default=None, max_length=600)
    ru: str | None = Field(default=None, max_length=600)

    @field_validator("lv", "en", "ru")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    def pick(self, lang: Language) -> tuple[str, Language]:
        text = getattr(self, lang)
        return (text, lang) if text else (self.lv, "lv")
