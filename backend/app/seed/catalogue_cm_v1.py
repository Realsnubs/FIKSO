"""Initial catalogue (CM, owner-approved 2026-10-31). Generated from docs/CATALOGUE_SEED.md — keep identical.

tests/test_catalogue_seed.py fails if this data and the document diverge. Do not edit W-IDs or source refs.
"""

from typing import Any

CATEGORIES: list[dict[str, Any]] = [
    {
        "ref": "cm-c1",
        "name": "Mazā santehnika un mājas meistaru darbi",
        "status": "active",
        "specialisations": [
            {
                "ref": "cm-s01",
                "name": "Poda meistars",
                "description": "podu uzstādīšana, nomaiņa, skalojamo kastu un mehānismu remonts.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W071",
                        "ref": "cm-s01-1",
                        "name": "Tualetes poda uzstādīšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W072",
                        "ref": "cm-s01-2",
                        "name": "Tualetes poda nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W073",
                        "ref": "cm-s01-3",
                        "name": "Skalošanas kastes remonts",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W074",
                        "ref": "cm-s01-4",
                        "name": "Skalošanas mehānisma remonts",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s02",
                "name": "Krānu meistars",
                "description": "virtuves un vannasistabas jaucējkrānu, maisītāju uzstādīšana un nomaiņa.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W075",
                        "ref": "cm-s02-1",
                        "name": "Jaucējkrāna uzstādīšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W076",
                        "ref": "cm-s02-2",
                        "name": "Jaucējkrāna nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s03",
                "name": "Izlietņu meistars",
                "description": "izlietņu uzstādīšana, sifonu nomaiņa, remonts un pieslēgšana.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W077",
                        "ref": "cm-s03-1",
                        "name": "Izlietnes uzstādīšana",
                        "qualification_required": False,
                        "review_note": 'Possible overlap: "Izlietnes uzstādīšana" (Izlietņu '
                        'meistars) and "Izlietnes uzstādīšana vannas istabā" '
                        "(Vannasistabas meistars). Admin decides; not merged "
                        "automatically.",
                    },
                    {
                        "w_id": "W078",
                        "ref": "cm-s03-2",
                        "name": "Sifona nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W079",
                        "ref": "cm-s03-3",
                        "name": "Izlietnes vai sifona remonts",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W080",
                        "ref": "cm-s03-4",
                        "name": "Izlietnes pieslēgšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s04",
                "name": "Tehnikas meistars",
                "description": "veļas un trauku mazgājamo mašīnu pieslēgšana, uzstādīšana.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W081",
                        "ref": "cm-s04-1",
                        "name": "Veļas mazgājamās mašīnas uzstādīšana un pieslēgšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W082",
                        "ref": "cm-s04-2",
                        "name": "Trauku mazgājamās mašīnas uzstādīšana un pieslēgšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s05",
                "name": "Silikona meistars",
                "description": "vecā silikona noņemšana, jaunu silikona šuvju ieklāšana "
                "vannasistabās, dušās un virtuvēs.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W083",
                        "ref": "cm-s05-1",
                        "name": "Vecā silikona noņemšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W084",
                        "ref": "cm-s05-2",
                        "name": "Jaunu silikona šuvju ieklāšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s06",
                "name": "Stiprinājumu meistars",
                "description": "televizoru, plauktu, spoguļu, karnīžu, žalūziju, turētāju un citu "
                "priekšmetu stiprināšana.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W085",
                        "ref": "cm-s06-1",
                        "name": "Televizora stiprināšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W086",
                        "ref": "cm-s06-2",
                        "name": "Plauktu stiprināšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W087",
                        "ref": "cm-s06-3",
                        "name": "Spoguļa uzstādīšana un stiprināšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W088",
                        "ref": "cm-s06-4",
                        "name": "Karnīzes uzstādīšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W089",
                        "ref": "cm-s06-5",
                        "name": "Žalūziju stiprināšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W090",
                        "ref": "cm-s06-6",
                        "name": "Turētāju stiprināšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W091",
                        "ref": "cm-s06-7",
                        "name": "Citu priekšmetu stiprināšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s07",
                "name": "Gaismekļu meistars",
                "description": "lampu, lustru un gaismekļu uzstādīšana un nomaiņa pie esošiem pieslēgumiem.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W092",
                        "ref": "cm-s07-1",
                        "name": "Gaismekļa uzstādīšana pie esoša pieslēguma",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W093",
                        "ref": "cm-s07-2",
                        "name": "Gaismekļa nomaiņa pie esoša pieslēguma",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s08",
                "name": "Mēbeļu meistars",
                "description": "skapju, gultu, galdu un citu mēbeļu montāža, nelieli mēbeļu remonti.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W094",
                        "ref": "cm-s08-1",
                        "name": "Skapja montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W095",
                        "ref": "cm-s08-2",
                        "name": "Gultas montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W096",
                        "ref": "cm-s08-3",
                        "name": "Galda montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W097",
                        "ref": "cm-s08-4",
                        "name": "Citu mēbeļu montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W098",
                        "ref": "cm-s08-5",
                        "name": "Neliels mēbeļu remonts",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s09",
                "name": "Vannasistabas meistars",
                "description": "vannasistabas skapīšu, spoguļskapju, izlietņu un cita aprīkojuma montāža.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W099",
                        "ref": "cm-s09-1",
                        "name": "Vannasistabas skapīšu montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W100",
                        "ref": "cm-s09-2",
                        "name": "Spoguļskapja montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W101",
                        "ref": "cm-s09-3",
                        "name": "Izlietnes uzstādīšana vannas istabā",
                        "qualification_required": False,
                        "review_note": 'Possible overlap: "Izlietnes uzstādīšana" (Izlietņu '
                        'meistars) and "Izlietnes uzstādīšana vannas istabā" '
                        "(Vannasistabas meistars). Admin decides; not merged "
                        "automatically.",
                    },
                    {
                        "w_id": "W102",
                        "ref": "cm-s09-4",
                        "name": "Cita vannasistabas aprīkojuma montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s10",
                "name": "Santehnikas meistars",
                "description": "nelielu noplūžu novēršana, ūdensvada un kanalizācijas mezglu remonts "
                "atbilstoši kvalifikācijai.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W103",
                        "ref": "cm-s10-1",
                        "name": "Nelielas noplūdes novēršana",
                        "qualification_required": True,
                        "review_note": None,
                    },
                    {
                        "w_id": "W104",
                        "ref": "cm-s10-2",
                        "name": "Ūdensvada mezgla remonts",
                        "qualification_required": True,
                        "review_note": None,
                    },
                    {
                        "w_id": "W105",
                        "ref": "cm-s10-3",
                        "name": "Kanalizācijas mezgla remonts",
                        "qualification_required": True,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s11",
                "name": "Īpašumu uzturēšanas meistars",
                "description": "īres dzīvokļu apskate, nelielu defektu novēršana un mājokļu "
                "uzturēšanas darbi.",
                "status": "active",
                "services": [
                    {
                        "w_id": "W106",
                        "ref": "cm-s11-1",
                        "name": "Īres dzīvokļa apskate",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W107",
                        "ref": "cm-s11-2",
                        "name": "Nelielu defektu novēršana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W108",
                        "ref": "cm-s11-3",
                        "name": "Mājokļa uzturēšanas darbi",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
        ],
    },
    {
        "ref": "cm-c2",
        "name": "Specializētie meistari",
        "status": "planned",
        "specialisations": [
            {
                "ref": "cm-s12",
                "name": "Fūgu meistars",
                "description": "veco flīžu šuvju atjaunošana, tīrīšana un pāršuvošana.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W109",
                        "ref": "cm-s12-1",
                        "name": "Flīžu šuvju atjaunošana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W110",
                        "ref": "cm-s12-2",
                        "name": "Flīžu šuvju tīrīšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W111",
                        "ref": "cm-s12-3",
                        "name": "Flīžu pāršuvošana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s13",
                "name": "Elektrības meistars",
                "description": "rozešu, slēdžu, elektroinstalācijas un pieslēgumu darbi atbilstoši "
                "kvalifikācijai.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W112",
                        "ref": "cm-s13-1",
                        "name": "Rozešu darbi",
                        "qualification_required": True,
                        "review_note": None,
                    },
                    {
                        "w_id": "W113",
                        "ref": "cm-s13-2",
                        "name": "Slēdžu darbi",
                        "qualification_required": True,
                        "review_note": None,
                    },
                    {
                        "w_id": "W114",
                        "ref": "cm-s13-3",
                        "name": "Elektroinstalācijas darbi",
                        "qualification_required": True,
                        "review_note": None,
                    },
                    {
                        "w_id": "W115",
                        "ref": "cm-s13-4",
                        "name": "Pieslēgumu darbi",
                        "qualification_required": True,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s14",
                "name": "Apkures meistars",
                "description": "radiatoru, termostatu, apkures cauruļu un sistēmu remonts un nomaiņa.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W116",
                        "ref": "cm-s14-1",
                        "name": "Radiatora remonts vai nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W117",
                        "ref": "cm-s14-2",
                        "name": "Termostata remonts vai nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W118",
                        "ref": "cm-s14-3",
                        "name": "Apkures cauruļu remonts vai nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W119",
                        "ref": "cm-s14-4",
                        "name": "Apkures sistēmas remonts vai nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s15",
                "name": "Logu meistars",
                "description": "logu regulēšana, furnitūras un blīvējumu remonts vai nomaiņa.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W120",
                        "ref": "cm-s15-1",
                        "name": "Logu regulēšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W121",
                        "ref": "cm-s15-2",
                        "name": "Logu furnitūras remonts vai nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W122",
                        "ref": "cm-s15-3",
                        "name": "Logu blīvējumu remonts vai nomaiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s16",
                "name": "Durvju meistars",
                "description": "durvju regulēšana, uzstādīšana, slēdzeņu, rokturu un eņģu maiņa.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W123",
                        "ref": "cm-s16-1",
                        "name": "Durvju regulēšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W124",
                        "ref": "cm-s16-2",
                        "name": "Durvju uzstādīšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W125",
                        "ref": "cm-s16-3",
                        "name": "Slēdzenes maiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W126",
                        "ref": "cm-s16-4",
                        "name": "Roktura maiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W127",
                        "ref": "cm-s16-5",
                        "name": "Eņģu maiņa",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s17",
                "name": "Ūdens skaitītāju meistars",
                "description": "skaitītāju maiņa atbilstoši nepieciešamajai kvalifikācijai.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W128",
                        "ref": "cm-s17-1",
                        "name": "Ūdens skaitītāja maiņa",
                        "qualification_required": True,
                        "review_note": None,
                    }
                ],
            },
            {
                "ref": "cm-s18",
                "name": "Gāzes meistars",
                "description": "gāzes iekārtu un pieslēgumu darbi, tikai atbilstoši kvalificētam "
                "speciālistam.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W129",
                        "ref": "cm-s18-1",
                        "name": "Gāzes iekārtu darbi",
                        "qualification_required": True,
                        "review_note": None,
                    },
                    {
                        "w_id": "W130",
                        "ref": "cm-s18-2",
                        "name": "Gāzes pieslēgumu darbi",
                        "qualification_required": True,
                        "review_note": None,
                    },
                ],
            },
        ],
    },
    {
        "ref": "cm-c3",
        "name": "Papildu specializācijas",
        "status": "planned",
        "specialisations": [
            {
                "ref": "cm-s19",
                "name": "Bruģa mazgāšanas meistars",
                "description": "bruģa mazgāšana ar augstspiediena tehniku, netīrumu, sūnu un apauguma "
                "noņemšana.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W131",
                        "ref": "cm-s19-1",
                        "name": "Bruģa mazgāšana ar augstspiediena tehniku",
                        "qualification_required": False,
                        "review_note": 'Possible same service: "Bruģa mazgāšana ar '
                        'augstspiediena tehniku" and "Netīrumu, sūnu un apauguma '
                        'noņemšana no bruģa". Admin decides; not merged '
                        "automatically.",
                    },
                    {
                        "w_id": "W132",
                        "ref": "cm-s19-2",
                        "name": "Netīrumu, sūnu un apauguma noņemšana no bruģa",
                        "qualification_required": False,
                        "review_note": 'Possible same service: "Bruģa mazgāšana ar '
                        'augstspiediena tehniku" and "Netīrumu, sūnu un apauguma '
                        'noņemšana no bruģa". Admin decides; not merged '
                        "automatically.",
                    },
                ],
            },
            {
                "ref": "cm-s20",
                "name": "Apdares meistars",
                "description": "sienu špaktelēšana, slīpēšana un krāsošana.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W133",
                        "ref": "cm-s20-1",
                        "name": "Sienu špaktelēšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W134",
                        "ref": "cm-s20-2",
                        "name": "Sienu slīpēšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W135",
                        "ref": "cm-s20-3",
                        "name": "Sienu krāsošana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s21",
                "name": "Flīzēšanas meistars",
                "description": "sienu un grīdu flīzēšana.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W136",
                        "ref": "cm-s21-1",
                        "name": "Sienu flīzēšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W137",
                        "ref": "cm-s21-2",
                        "name": "Grīdas flīzēšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s22",
                "name": "Grīdu meistars",
                "description": "lamināta, vinila un grīdlīstu ieklāšana un montāža.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W138",
                        "ref": "cm-s22-1",
                        "name": "Lamināta ieklāšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W139",
                        "ref": "cm-s22-2",
                        "name": "Vinila grīdas ieklāšana",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W140",
                        "ref": "cm-s22-3",
                        "name": "Grīdlīstu montāža",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s23",
                "name": "Ģipškartona meistars",
                "description": "ģipškartona konstrukciju izbūve un remonts.",
                "status": "planned",
                "services": [
                    {
                        "w_id": "W141",
                        "ref": "cm-s23-1",
                        "name": "Ģipškartona konstrukciju izbūve",
                        "qualification_required": False,
                        "review_note": None,
                    },
                    {
                        "w_id": "W142",
                        "ref": "cm-s23-2",
                        "name": "Ģipškartona konstrukciju remonts",
                        "qualification_required": False,
                        "review_note": None,
                    },
                ],
            },
            {
                "ref": "cm-s24",
                "name": "Remontdarbu meistars",
                "description": "dažādi dzīvokļu un mājokļu remonta darbi pēc konkrētās kompetences.",
                "status": "planned",
                "services": [],
            },
        ],
    },
]
