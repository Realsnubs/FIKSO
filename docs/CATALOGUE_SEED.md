# FIKSO — Initial catalogue seed (CM, 2026-10-31)

Source: owner clarification "Catalogue Management" (CM §3). Latvian names and descriptions are verbatim.
Loaded by `python -m app.cli seed-catalogue` (idempotent by `source_ref`, `source = seed_cm_v1`) in **production**
only (or an isolated local/test DB); staging receives it through the production export (R-CAT-16, Q-24). See R-CAT-11/12,
`docs/DATABASE.md` §3.2, Q-20..Q-22.

## Rules
- Categories have no seeded description (none supplied); the CM status label is kept here for reference only.
- **Suggested services** are derived only from each specialisation's description — one service per work the
  description names, no additions. All are seeded with status **`draft`** for admin review (edit / approve /
  activate / reject in the Admin Panel). Nothing is activated by the seed.
- W-IDs W071–W142 are fixed here so every environment gets the same W-IDs (website deep links). UUIDs are
  deterministic (`uuid5` of `source_ref`), so they are identical in every environment too (R-CAT-15).
- After seeding, the next W-ID issued is **W143**. W-IDs are unique and never reused — rows are never deleted, so a
  rejected or archived suggestion keeps its W-ID forever.
- `qualification_required = yes` only where the description itself says the work depends on qualification
  ("atbilstoši kvalifikācijai", "atbilstoši nepieciešamajai kvalifikācijai", "tikai atbilstoši kvalificētam
  speciālistam"). It is set on the services, not on the specialisation (Q-21); no qualification types are seeded.
  Such services cannot become active until the admin configures their qualifications.
- Entries listed under **Admin review flags** below are seeded with a `review_note` that the Admin Panel shows on
  the draft. Flags never merge, reject or change anything automatically; all flagged entries stay `draft`.
- Electrical services W112–W115 keep their generic names as drafts; no further electrical services are added.
- **Status: approved by the owner (2026-10-31), incl. "vannas istabā" in W101.** This file is the source of
  `backend/app/seed/catalogue_cm_v1.py`; a test keeps both identical. Once seeded,
  edits happen in the Admin Panel (the W-ID and UUID stay).

## Admin review flags

| W-IDs | `review_note` (seeded) |
|---|---|
| W077, W101 | Possible overlap: "Izlietnes uzstādīšana" (Izlietņu meistars) and "Izlietnes uzstādīšana vannas istabā" (Vannasistabas meistars). Admin decides; not merged automatically. |
| W131, W132 | Possible same service: "Bruģa mazgāšana ar augstspiediena tehniku" and "Netīrumu, sūnu un apauguma noņemšana no bruģa". Admin decides; not merged automatically. |

## Owner corrections applied (2026-10-31)
W071, W072, W073, W075, W076, W087, W088, W092, W093, W101 renamed as instructed. W-IDs, UUIDs (`source_ref`),
qualification flags and statuses unchanged.

Totals: 3 categories · 24 specialisations · 72 suggested services (W071–W142) · 0 qualifications.

## Category 1 — Mazā santehnika un mājas meistaru darbi

Category status: `active` · CM label: Available services · `source_ref` `cm-c1`

### 1. Poda meistars

Specialisation status: `active` · description (verbatim): "podu uzstādīšana, nomaiņa, skalojamo kastu un mehānismu remonts." · `source_ref` `cm-s01`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W071 | Tualetes poda uzstādīšana | no | `cm-s01-1` |
| W072 | Tualetes poda nomaiņa | no | `cm-s01-2` |
| W073 | Skalošanas kastes remonts | no | `cm-s01-3` |
| W074 | Skalošanas mehānisma remonts | no | `cm-s01-4` |

### 2. Krānu meistars

Specialisation status: `active` · description (verbatim): "virtuves un vannasistabas jaucējkrānu, maisītāju uzstādīšana un nomaiņa." · `source_ref` `cm-s02`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W075 | Jaucējkrāna uzstādīšana | no | `cm-s02-1` |
| W076 | Jaucējkrāna nomaiņa | no | `cm-s02-2` |

### 3. Izlietņu meistars

Specialisation status: `active` · description (verbatim): "izlietņu uzstādīšana, sifonu nomaiņa, remonts un pieslēgšana." · `source_ref` `cm-s03`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W077 | Izlietnes uzstādīšana | no | `cm-s03-1` |
| W078 | Sifona nomaiņa | no | `cm-s03-2` |
| W079 | Izlietnes vai sifona remonts | no | `cm-s03-3` |
| W080 | Izlietnes pieslēgšana | no | `cm-s03-4` |

### 4. Tehnikas meistars

Specialisation status: `active` · description (verbatim): "veļas un trauku mazgājamo mašīnu pieslēgšana, uzstādīšana." · `source_ref` `cm-s04`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W081 | Veļas mazgājamās mašīnas uzstādīšana un pieslēgšana | no | `cm-s04-1` |
| W082 | Trauku mazgājamās mašīnas uzstādīšana un pieslēgšana | no | `cm-s04-2` |

### 5. Silikona meistars

Specialisation status: `active` · description (verbatim): "vecā silikona noņemšana, jaunu silikona šuvju ieklāšana vannasistabās, dušās un virtuvēs." · `source_ref` `cm-s05`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W083 | Vecā silikona noņemšana | no | `cm-s05-1` |
| W084 | Jaunu silikona šuvju ieklāšana | no | `cm-s05-2` |

### 6. Stiprinājumu meistars

Specialisation status: `active` · description (verbatim): "televizoru, plauktu, spoguļu, karnīžu, žalūziju, turētāju un citu priekšmetu stiprināšana." · `source_ref` `cm-s06`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W085 | Televizora stiprināšana | no | `cm-s06-1` |
| W086 | Plauktu stiprināšana | no | `cm-s06-2` |
| W087 | Spoguļa uzstādīšana un stiprināšana | no | `cm-s06-3` |
| W088 | Karnīzes uzstādīšana | no | `cm-s06-4` |
| W089 | Žalūziju stiprināšana | no | `cm-s06-5` |
| W090 | Turētāju stiprināšana | no | `cm-s06-6` |
| W091 | Citu priekšmetu stiprināšana | no | `cm-s06-7` |

### 7. Gaismekļu meistars

Specialisation status: `active` · description (verbatim): "lampu, lustru un gaismekļu uzstādīšana un nomaiņa pie esošiem pieslēgumiem." · `source_ref` `cm-s07`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W092 | Gaismekļa uzstādīšana pie esoša pieslēguma | no | `cm-s07-1` |
| W093 | Gaismekļa nomaiņa pie esoša pieslēguma | no | `cm-s07-2` |

### 8. Mēbeļu meistars

Specialisation status: `active` · description (verbatim): "skapju, gultu, galdu un citu mēbeļu montāža, nelieli mēbeļu remonti." · `source_ref` `cm-s08`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W094 | Skapja montāža | no | `cm-s08-1` |
| W095 | Gultas montāža | no | `cm-s08-2` |
| W096 | Galda montāža | no | `cm-s08-3` |
| W097 | Citu mēbeļu montāža | no | `cm-s08-4` |
| W098 | Neliels mēbeļu remonts | no | `cm-s08-5` |

### 9. Vannasistabas meistars

Specialisation status: `active` · description (verbatim): "vannasistabas skapīšu, spoguļskapju, izlietņu un cita aprīkojuma montāža." · `source_ref` `cm-s09`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W099 | Vannasistabas skapīšu montāža | no | `cm-s09-1` |
| W100 | Spoguļskapja montāža | no | `cm-s09-2` |
| W101 | Izlietnes uzstādīšana vannas istabā | no | `cm-s09-3` |
| W102 | Cita vannasistabas aprīkojuma montāža | no | `cm-s09-4` |

### 10. Santehnikas meistars

Specialisation status: `active` · description (verbatim): "nelielu noplūžu novēršana, ūdensvada un kanalizācijas mezglu remonts atbilstoši kvalifikācijai." · `source_ref` `cm-s10`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W103 | Nelielas noplūdes novēršana | yes | `cm-s10-1` |
| W104 | Ūdensvada mezgla remonts | yes | `cm-s10-2` |
| W105 | Kanalizācijas mezgla remonts | yes | `cm-s10-3` |

### 11. Īpašumu uzturēšanas meistars

Specialisation status: `active` · description (verbatim): "īres dzīvokļu apskate, nelielu defektu novēršana un mājokļu uzturēšanas darbi." · `source_ref` `cm-s11`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W106 | Īres dzīvokļa apskate | no | `cm-s11-1` |
| W107 | Nelielu defektu novēršana | no | `cm-s11-2` |
| W108 | Mājokļa uzturēšanas darbi | no | `cm-s11-3` |

## Category 2 — Specializētie meistari

Category status: `planned` · CM label: To be introduced progressively · `source_ref` `cm-c2`

### 12. Fūgu meistars

Specialisation status: `planned` · description (verbatim): "veco flīžu šuvju atjaunošana, tīrīšana un pāršuvošana." · `source_ref` `cm-s12`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W109 | Flīžu šuvju atjaunošana | no | `cm-s12-1` |
| W110 | Flīžu šuvju tīrīšana | no | `cm-s12-2` |
| W111 | Flīžu pāršuvošana | no | `cm-s12-3` |

### 13. Elektrības meistars

Specialisation status: `planned` · description (verbatim): "rozešu, slēdžu, elektroinstalācijas un pieslēgumu darbi atbilstoši kvalifikācijai." · `source_ref` `cm-s13`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W112 | Rozešu darbi | yes | `cm-s13-1` |
| W113 | Slēdžu darbi | yes | `cm-s13-2` |
| W114 | Elektroinstalācijas darbi | yes | `cm-s13-3` |
| W115 | Pieslēgumu darbi | yes | `cm-s13-4` |

### 14. Apkures meistars

Specialisation status: `planned` · description (verbatim): "radiatoru, termostatu, apkures cauruļu un sistēmu remonts un nomaiņa." · `source_ref` `cm-s14`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W116 | Radiatora remonts vai nomaiņa | no | `cm-s14-1` |
| W117 | Termostata remonts vai nomaiņa | no | `cm-s14-2` |
| W118 | Apkures cauruļu remonts vai nomaiņa | no | `cm-s14-3` |
| W119 | Apkures sistēmas remonts vai nomaiņa | no | `cm-s14-4` |

### 15. Logu meistars

Specialisation status: `planned` · description (verbatim): "logu regulēšana, furnitūras un blīvējumu remonts vai nomaiņa." · `source_ref` `cm-s15`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W120 | Logu regulēšana | no | `cm-s15-1` |
| W121 | Logu furnitūras remonts vai nomaiņa | no | `cm-s15-2` |
| W122 | Logu blīvējumu remonts vai nomaiņa | no | `cm-s15-3` |

### 16. Durvju meistars

Specialisation status: `planned` · description (verbatim): "durvju regulēšana, uzstādīšana, slēdzeņu, rokturu un eņģu maiņa." · `source_ref` `cm-s16`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W123 | Durvju regulēšana | no | `cm-s16-1` |
| W124 | Durvju uzstādīšana | no | `cm-s16-2` |
| W125 | Slēdzenes maiņa | no | `cm-s16-3` |
| W126 | Roktura maiņa | no | `cm-s16-4` |
| W127 | Eņģu maiņa | no | `cm-s16-5` |

### 17. Ūdens skaitītāju meistars

Specialisation status: `planned` · description (verbatim): "skaitītāju maiņa atbilstoši nepieciešamajai kvalifikācijai." · `source_ref` `cm-s17`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W128 | Ūdens skaitītāja maiņa | yes | `cm-s17-1` |

### 18. Gāzes meistars

Specialisation status: `planned` · description (verbatim): "gāzes iekārtu un pieslēgumu darbi, tikai atbilstoši kvalificētam speciālistam." · `source_ref` `cm-s18`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W129 | Gāzes iekārtu darbi | yes | `cm-s18-1` |
| W130 | Gāzes pieslēgumu darbi | yes | `cm-s18-2` |

## Category 3 — Papildu specializācijas

Category status: `planned` · CM label: Planned for future activation · `source_ref` `cm-c3`

### 19. Bruģa mazgāšanas meistars

Specialisation status: `planned` · description (verbatim): "bruģa mazgāšana ar augstspiediena tehniku, netīrumu, sūnu un apauguma noņemšana." · `source_ref` `cm-s19`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W131 | Bruģa mazgāšana ar augstspiediena tehniku | no | `cm-s19-1` |
| W132 | Netīrumu, sūnu un apauguma noņemšana no bruģa | no | `cm-s19-2` |

### 20. Apdares meistars

Specialisation status: `planned` · description (verbatim): "sienu špaktelēšana, slīpēšana un krāsošana." · `source_ref` `cm-s20`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W133 | Sienu špaktelēšana | no | `cm-s20-1` |
| W134 | Sienu slīpēšana | no | `cm-s20-2` |
| W135 | Sienu krāsošana | no | `cm-s20-3` |

### 21. Flīzēšanas meistars

Specialisation status: `planned` · description (verbatim): "sienu un grīdu flīzēšana." · `source_ref` `cm-s21`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W136 | Sienu flīzēšana | no | `cm-s21-1` |
| W137 | Grīdas flīzēšana | no | `cm-s21-2` |

### 22. Grīdu meistars

Specialisation status: `planned` · description (verbatim): "lamināta, vinila un grīdlīstu ieklāšana un montāža." · `source_ref` `cm-s22`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W138 | Lamināta ieklāšana | no | `cm-s22-1` |
| W139 | Vinila grīdas ieklāšana | no | `cm-s22-2` |
| W140 | Grīdlīstu montāža | no | `cm-s22-3` |

### 23. Ģipškartona meistars

Specialisation status: `planned` · description (verbatim): "ģipškartona konstrukciju izbūve un remonts." · `source_ref` `cm-s23`

| W-ID | Suggested service | `qualification_required` | `source_ref` |
|---|---|---|---|
| W141 | Ģipškartona konstrukciju izbūve | no | `cm-s23-1` |
| W142 | Ģipškartona konstrukciju remonts | no | `cm-s23-2` |

### 24. Remontdarbu meistars

Specialisation status: `planned` · description (verbatim): "dažādi dzīvokļu un mājokļu remonta darbi pēc konkrētās kompetences." · `source_ref` `cm-s24`

No suggested services: the description names no specific works ("pēc konkrētās kompetences"). The admin creates services.

