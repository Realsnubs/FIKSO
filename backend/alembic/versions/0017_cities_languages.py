"""City-based work zones and communication languages (owner decision 2026-11-05).

Reference data is seeded here; no master gets a city or a language automatically (they set them before
receiving offers), and the old radius columns stay untouched but are no longer used by matching.

cities and languages

Revision ID: 0017_cities_languages
Revises: 0016_production_readiness
Create Date: 2026-11-05 00:10:52.604655
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_cities_languages"
down_revision: str | None = "0016_production_readiness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, lv, en, ru, lat, lon, max_distance_km)
CITIES = [
    ("riga", "Rīga", "Riga", "Рига", "56.949600", "24.105200", "20"),
    ("daugavpils", "Daugavpils", "Daugavpils", "Даугавпилс", "55.874700", "26.536200", "12"),
    ("liepaja", "Liepāja", "Liepaja", "Лиепая", "56.504700", "21.010800", "12"),
    ("jelgava", "Jelgava", "Jelgava", "Елгава", "56.651100", "23.721400", "10"),
    ("jurmala", "Jūrmala", "Jurmala", "Юрмала", "56.968000", "23.770400", "20"),
    ("ventspils", "Ventspils", "Ventspils", "Вентспилс", "57.389400", "21.560600", "10"),
    ("rezekne", "Rēzekne", "Rezekne", "Резекне", "56.509900", "27.331900", "10"),
    ("valmiera", "Valmiera", "Valmiera", "Валмиера", "57.538400", "25.426400", "10"),
    ("jekabpils", "Jēkabpils", "Jekabpils", "Екабпилс", "56.499500", "25.857200", "10"),
    ("ogre", "Ogre", "Ogre", "Огре", "56.816200", "24.614000", "10"),
    ("tukums", "Tukums", "Tukums", "Тукумс", "56.966900", "23.155300", "8"),
    ("cesis", "Cēsis", "Cesis", "Цесис", "57.311900", "25.270600", "8"),
    ("salaspils", "Salaspils", "Salaspils", "Саласпилс", "56.860300", "24.349600", "8"),
    ("sigulda", "Sigulda", "Sigulda", "Сигулда", "57.151400", "24.859700", "8"),
    ("kuldiga", "Kuldīga", "Kuldiga", "Кулдига", "56.967700", "21.968100", "8"),
    ("talsi", "Talsi", "Talsi", "Талси", "57.244700", "22.587800", "8"),
    ("bauska", "Bauska", "Bauska", "Бауска", "56.407900", "24.193400", "8"),
    ("dobele", "Dobele", "Dobele", "Добеле", "56.625800", "23.278800", "8"),
    ("olaine", "Olaine", "Olaine", "Олайне", "56.785300", "23.938300", "8"),
    ("saldus", "Saldus", "Saldus", "Салдус", "56.663700", "22.488100", "8"),
    ("madona", "Madona", "Madona", "Мадона", "56.853900", "26.216900", "8"),
    ("smiltene", "Smiltene", "Smiltene", "Смилтене", "57.424500", "25.901600", "8"),
    ("gulbene", "Gulbene", "Gulbene", "Гулбене", "57.177500", "26.752500", "8"),
    ("limbazi", "Limbaži", "Limbazi", "Лимбажи", "57.513300", "24.713600", "8"),
    ("aluksne", "Alūksne", "Aluksne", "Алуксне", "57.422900", "27.046400", "8"),
    ("ludza", "Ludza", "Ludza", "Лудза", "56.545900", "27.717300", "8"),
    ("kraslava", "Krāslava", "Kraslava", "Краслава", "55.895100", "27.168100", "8"),
    ("preili", "Preiļi", "Preili", "Прейли", "56.294200", "26.724600", "8"),
    ("balvi", "Balvi", "Balvi", "Балви", "57.131300", "27.265400", "8"),
    ("aizkraukle", "Aizkraukle", "Aizkraukle", "Айзкраукле", "56.604700", "25.255000", "8"),
    ("adazi", "Ādaži", "Adazi", "Адажи", "57.075800", "24.324200", "8"),
    ("marupe", "Mārupe", "Marupe", "Марупе", "56.907000", "24.035000", "8"),
    ("kekava", "Ķekava", "Kekava", "Кекава", "56.827800", "24.229700", "8"),
    ("balozi", "Baloži", "Balozi", "Баложи", "56.876200", "24.119400", "6"),
    ("ropazi", "Ropaži", "Ropazi", "Ропажи", "56.965800", "24.630300", "8"),
    ("saulkrasti", "Saulkrasti", "Saulkrasti", "Саулкрасты", "57.263500", "24.415700", "8"),
    ("kandava", "Kandava", "Kandava", "Кандава", "57.033700", "22.776600", "6"),
    ("ikskile", "Ikšķile", "Ikskile", "Икшкиле", "56.834300", "24.499500", "6"),
    ("lielvarde", "Lielvārde", "Lielvarde", "Лиелварде", "56.718600", "24.809600", "6"),
    ("iecava", "Iecava", "Iecava", "Иецава", "56.597900", "24.205400", "6"),
]
# (code, lv, en, ru, native, flag)
LANGUAGES = [
    ("lv", "Latviešu", "Latvian", "Латышский", "Latviešu", "🇱🇻"),
    ("ru", "Krievu", "Russian", "Русский", "Русский", "🇷🇺"),
    ("en", "Angļu", "English", "Английский", "English", "🇬🇧"),
    ("de", "Vācu", "German", "Немецкий", "Deutsch", "🇩🇪"),
    ("fr", "Franču", "French", "Французский", "Français", "🇫🇷"),
    ("es", "Spāņu", "Spanish", "Испанский", "Español", "🇪🇸"),
    ("it", "Itāļu", "Italian", "Итальянский", "Italiano", "🇮🇹"),
    ("pl", "Poļu", "Polish", "Польский", "Polski", "🇵🇱"),
    ("uk", "Ukraiņu", "Ukrainian", "Украинский", "Українська", "🇺🇦"),
    ("lt", "Lietuviešu", "Lithuanian", "Литовский", "Lietuvių", "🇱🇹"),
    ("et", "Igauņu", "Estonian", "Эстонский", "Eesti", "🇪🇪"),
    ("be", "Baltkrievu", "Belarusian", "Белорусский", "Беларуская", None),
    ("pt", "Portugāļu", "Portuguese", "Португальский", "Português", "🇵🇹"),
    ("nl", "Nīderlandiešu", "Dutch", "Нидерландский", "Nederlands", "🇳🇱"),
    ("sv", "Zviedru", "Swedish", "Шведский", "Svenska", "🇸🇪"),
    ("no", "Norvēģu", "Norwegian", "Норвежский", "Norsk", "🇳🇴"),
    ("da", "Dāņu", "Danish", "Датский", "Dansk", "🇩🇰"),
    ("fi", "Somu", "Finnish", "Финский", "Suomi", "🇫🇮"),
    ("tr", "Turku", "Turkish", "Турецкий", "Türkçe", "🇹🇷"),
    ("ar", "Arābu", "Arabic", "Арабский", "العربية", None),
    ("zh", "Ķīniešu", "Chinese", "Китайский", "中文", "🇨🇳"),
    ("ja", "Japāņu", "Japanese", "Японский", "日本語", "🇯🇵"),
    ("ko", "Korejiešu", "Korean", "Корейский", "한국어", "🇰🇷"),
    ("hi", "Hindi", "Hindi", "Хинди", "हिन्दी", "🇮🇳"),
]


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "cities",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_lv", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ru", sa.Text(), nullable=False),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("max_distance_km", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint("code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_cities_code_format")),
        sa.CheckConstraint("max_distance_km > 0", name=op.f("ck_cities_max_distance")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_cities")),
    )
    op.create_table(
        "communication_languages",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_lv", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ru", sa.Text(), nullable=False),
        sa.Column("native_name", sa.Text(), nullable=False),
        sa.Column("flag", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint("code ~ '^[a-z]{2,3}$'", name=op.f("ck_communication_languages_code_format")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_communication_languages")),
    )
    op.create_table(
        "master_cities",
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("city_code", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["city_code"],
            ["cities.code"],
            name=op.f("fk_master_cities_city_code_cities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_master_cities_master_id_master_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("master_id", "city_code", name=op.f("pk_master_cities")),
    )
    op.create_index(
        "uq_master_cities_one_primary",
        "master_cities",
        ["master_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.create_table(
        "master_languages",
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("language_code", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["language_code"],
            ["communication_languages.code"],
            name=op.f("fk_master_languages_language_code_communication_languages"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_master_languages_master_id_master_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("master_id", "language_code", name=op.f("pk_master_languages")),
    )
    op.add_column("commission_ledger", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.create_index(
        "uq_commission_ledger_idempotency",
        "commission_ledger",
        ["master_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.add_column("orders", sa.Column("communication_language", sa.Text(), nullable=True))
    op.add_column("service_requests", sa.Column("city_code", sa.Text(), nullable=True))
    op.add_column("service_requests", sa.Column("communication_language", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_service_requests_city_code_cities"),
        "service_requests",
        "cities",
        ["city_code"],
        ["code"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_service_requests_communication_language_communication_languages"),
        "service_requests",
        "communication_languages",
        ["communication_language"],
        ["code"],
        ondelete="RESTRICT",
    )
    cities = sa.table(
        "cities",
        sa.column("code"),
        sa.column("name_lv"),
        sa.column("name_en"),
        sa.column("name_ru"),
        sa.column("lat"),
        sa.column("lon"),
        sa.column("max_distance_km"),
        sa.column("sort_order"),
    )
    op.bulk_insert(
        cities,
        [
            {
                "code": c,
                "name_lv": lv,
                "name_en": en,
                "name_ru": ru,
                "lat": lat,
                "lon": lon,
                "max_distance_km": dist,
                "sort_order": i,
            }
            for i, (c, lv, en, ru, lat, lon, dist) in enumerate(CITIES)
        ],
    )
    languages = sa.table(
        "communication_languages",
        sa.column("code"),
        sa.column("name_lv"),
        sa.column("name_en"),
        sa.column("name_ru"),
        sa.column("native_name"),
        sa.column("flag"),
        sa.column("sort_order"),
    )
    op.bulk_insert(
        languages,
        [
            {
                "code": c,
                "name_lv": lv,
                "name_en": en,
                "name_ru": ru,
                "native_name": native,
                "flag": flag,
                "sort_order": i,
            }
            for i, (c, lv, en, ru, native, flag) in enumerate(LANGUAGES)
        ],
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(
        op.f("fk_service_requests_communication_language_communication_languages"),
        "service_requests",
        type_="foreignkey",
    )
    op.drop_constraint(op.f("fk_service_requests_city_code_cities"), "service_requests", type_="foreignkey")
    op.drop_column("service_requests", "communication_language")
    op.drop_column("service_requests", "city_code")
    op.drop_column("orders", "communication_language")
    op.drop_index(
        "uq_commission_ledger_idempotency",
        table_name="commission_ledger",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_column("commission_ledger", "idempotency_key")
    op.drop_table("master_languages")
    op.drop_index(
        "uq_master_cities_one_primary", table_name="master_cities", postgresql_where=sa.text("is_primary")
    )
    op.drop_table("master_cities")
    op.drop_table("communication_languages")
    op.drop_table("cities")
    # ### end Alembic commands ###
