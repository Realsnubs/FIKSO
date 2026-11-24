"""Reference data for city-based work zones and communication languages (owner decision 2026-11-05).

Both are data-driven: adding a city or a language is a row, never a code change. Interface languages
(LV/EN/RU) are a separate, fixed system in the frontend and are not stored here.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt


class City(Base):
    """A Latvian city a master can work in and a request can be located in."""

    __tablename__ = "cities"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="code_format"),
        CheckConstraint("max_distance_km > 0", name="max_distance"),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_lv: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    # Centre point: ETA origin for a master without a fresh location; plausibility check of a request point.
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    lon: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    # A request point farther than this from the centre does not count as "in this city" (ask the client).
    max_distance_km: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class CommunicationLanguage(Base):
    """A language a master can serve clients in (not an interface language)."""

    __tablename__ = "communication_languages"
    __table_args__ = (CheckConstraint("code ~ '^[a-z]{2,3}$'", name="code_format"),)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_lv: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    native_name: Mapped[str] = mapped_column(Text, nullable=False)
    flag: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class MasterCity(CreatedAt, Base):
    """Cities a master works in. One primary city now; the table already allows more later."""

    __tablename__ = "master_cities"
    __table_args__ = (
        Index("uq_master_cities_one_primary", "master_id", unique=True, postgresql_where=text("is_primary")),
    )

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    city_code: Mapped[str] = mapped_column(ForeignKey("cities.code", ondelete="RESTRICT"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MasterLanguage(CreatedAt, Base):
    __tablename__ = "master_languages"

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    language_code: Mapped[str] = mapped_column(
        ForeignKey("communication_languages.code", ondelete="RESTRICT"), primary_key=True
    )
