# FIKSO MVP — Architecture

Version 1.1 · 2026-10-31 (catalogue management §6a). Requirement IDs refer to `docs/REQUIREMENTS.md`.
Items marked **TD** are technical decisions of this blueprint, not source requirements.

## 1. System overview (source D-Arch, §13)

```
 Client / Master / Admin (mobile browser, installed PWA, desktop)
          │ HTTPS
          ▼
 React + TS PWA (app.fiksoapp.eu)  ◄── deep links from fiksoapp.eu (Hostinger, unchanged)
          │ REST /api/v1 (JSON, OpenAPI)
          ▼
 FastAPI backend ── services (business logic) ──► PostgreSQL (managed, automated backups)
          │
          ├─ integrations/maps     geocoding, autocomplete, routing/ETA
          ├─ integrations/ai       OpenAI (clarification micro-agent only)
          ├─ integrations/sms      SMS provider (notifications)
          ├─ integrations/storage  S3-compatible private object storage (photos)
          └─ AI-ready access API   scoped, revocable service principals (future agents)
```

Separation (§13, §28): frontend, backend and database are independent deployables; business logic lives only
in the backend; the backend is the system's source of truth (§14.1).

## 2. Frontend (React 19 + TypeScript + Vite)

**Boundaries:** UI, form usability validation, routing, display formatting (Europe/Riga time, EUR). No business
rules: no matching, no commission math, no permission decisions (UI hides only for convenience).

**Structure (TD)**
```
src/
  api/        typed client (from OpenAPI), auth token handling, error mapping
  types/      domain types mirrored from OpenAPI
  features/   request-create, ai-clarify, proposal, order-tracking, review, complaint,
              master-availability, master-profile, worksheet, commission-dashboard,
              admin-* (users, masters, catalogue, orders, reviews, complaints, commission, contacts, stats)
  pages/      route components per role: /client, /master, /admin, /pakalpojumi, /pieteikums/jauns
  components/ shared accessible UI
  pwa/        manifest, service worker registration, install prompt
```

**Routing:** `/pieteikums/jauns?w=W0xx` is the deep-link entry (R-WEB; owner decision 2026-11-04, earlier default `/order/new`). Role areas guarded client-side and
enforced server-side. The `w` parameter is preserved through login/registration via `returnTo`.

**Master availability UI:** three large buttons (Available now / Reservations / Unavailable); Busy shown as a
system state, not selectable (R-MST-05/06).

**Location updates:** when the master is "available now" and the app is in the foreground, `navigator.geolocation`
is read every N minutes (default 3) and posted. Permission requested only when the master switches to
"available now", with an explanation. No background tracking (browsers do not support it reliably; not promised).

**Planned dependencies (to be installed at implementation, not now):** `react-router`, `@tanstack/react-query`,
`vite-plugin-pwa`, a map library (`leaflet`/`react-leaflet` or provider SDK — Q-02), form validation (`zod`),
testing (`vitest`, `@testing-library/react`, `playwright`). *Step 4.6 (owner decision):* built without React Query
and Zod (plain hooks, typed client); Playwright is not installed yet — E2E comes with the release phase.

**Admin and master capability screens (step 4.6, OPEN_QUESTIONS "Admin and master UI"):**
- Routes (all behind `RequireRole`, enforced again by the API): `/admin/catalogue` (with the impact dialog),
  `/admin/masters`, `/admin/masters/:id` (decisions, bulk verification, documents), `/admin/review-queue`,
  `/master/capabilities` ("Manas specializācijas un kvalifikācijas").
- `api/client.ts`: `apiRequest` (JSON or multipart `FormData`) and `apiBlob` (private files) share the token,
  refresh-on-401 and the error model `{error: {code, message, details}}` → `ApiError`; `errorMessage` maps codes to
  texts of the current language. Types in `types/` match the OpenAPI response schemas field by field.
- Every change carries what the backend requires: `expected_version` (decisions, catalogue changes), the preview
  `basis` as `expected_basis` (catalogue availability changes), the confirmed bulk preview's items and versions
  with `confirm: true`. Conflicts (409) reload the data and never re-send a stale request automatically.
- Which buttons a status offers is a UX mirror of the backend transition tables (`pages/admin/masters/
  decisions.ts`, `pages/master/MasterCapabilitiesPage.tsx`); availability for bulk verification and all
  eligibility reasons come from the API. Every write is guarded against double submission (in-flight ref plus
  disabled controls).
- Shared components: `components/ConfirmDialog` (modal, focus trap, Escape, focus back to the opener or `#main`),
  `components/Documents` (evidence files: authorised fetch → temporary Blob URL for images, revoked on close,
  on switching file and on unmount; PDF/HEIC download only, URL revoked right after the click; no public links),
  `i18n/format.ts` (Riga timestamps in the current language's locale, calendar dates as stored).
- Languages (Q-18, 2026-11-04): `i18n/lv.ts` (default), `en.ts`, `ru.ts` share one shape (`Dict`). Components read the
  live object `t`; `i18n/language.ts` copies the chosen dictionary into it in place (module-level references stay
  valid), sets `<html lang>` and stores the choice; the App root holds the language as state, so a switch
  re-renders the tree without losing component state. Backend error codes and reason codes are translated in the
  frontend; data (catalogue names, reasons typed by admins) is shown as stored.
- Upload limits (≤ 5 files, ≤ 10 MB, PDF/JPEG/PNG/WebP/HEIC) are pre-checked in `pages/master/uploads.ts` for the
  master's convenience only; the backend validates the content (magic bytes) and all limits.

## 3. Backend (FastAPI)

**Layers:** routers (HTTP, auth dependencies, schemas) → services (rules, transactions) → repositories/models
(SQLAlchemy) → PostgreSQL. Integrations behind interfaces with fakes for tests.

**Key services**

| Service | Responsibility |
|---|---|
| `auth` | registration, login, tokens, sessions, blocking |
| `catalogue` | categories → specialisations → services (W-ID), qualifications, status rules, HOLD guard, ordering, snapshots, orderability (verified capacity), seed/KVC import |
| `master_capabilities` | specialisation requests/decisions, service competencies, qualification evidence/verification, eligibility predicates used by matching |
| `requests` | create request, address validation, photos, idempotency |
| `clarification` | decides whether AI is needed, runs ≤2-question loop, validates AI output |
| `matching` | filters, ETA, ranking, snapshot, proposal + alternatives, re-matching |
| `orders` | state machine, departure (START) and arrival records, cancellations, admin override |
| `availability` | modes, Busy derivation, location updates |
| `worksheet` | work sheet versions, time calculation, client summary |
| `commission` | rate/limit config, ledger, eligibility check, payments, limit increases |
| `contacts` | contact click events, reveal of contact links |
| `reviews`, `complaints` | feedback and resolution |
| `notifications` | in-app inbox + SMS dispatch |
| `admin_stats` | aggregate queries |
| `events` | append `domain_event` within the caller's transaction |
| `ai_access` | service principals, scopes, token issuing/revocation |

**Python:** target 3.12+ (local machine has 3.14; pin the version supported by the hosting provider).

## 4. API design

- Base `/api/v1`, JSON, OpenAPI at `/api/v1/openapi.json`, docs UI only in non-production (**TD**).
- Resource-oriented paths; role areas: `/me`, `/client/...`, `/master/...`, `/admin/...`, `/public/...`, `/ai/...`.
- Errors: `{"error": {"code": "ORDER_INVALID_TRANSITION", "message": "...", "details": {...}}}`; no stack traces.
- Pagination: `?limit=&cursor=` returning `{items, next_cursor}`.
- Idempotency: `Idempotency-Key` header on request creation, payments, and status transitions.
- Concurrency: status transitions use `SELECT … FOR UPDATE` on the order row.

**Endpoint map (indicative)**

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register/client`, `POST /auth/register/master`, `POST /auth/guest/client`, `POST /auth/sms-code`, `POST /auth/sms-code/verify`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /me`, `POST /me/password` |
| Public | `GET /public/catalogue` (tree of orderable entries only), `GET /public/catalogue/services/by-w-id/{w_id}` |
| Address | `GET /geo/autocomplete?q=`, `POST /geo/resolve` (place id → address + coordinates) |
| Requests | `POST /client/requests`, `POST /client/requests/{id}/photos`, `POST /client/requests/{id}/clarification/answer`, `GET /client/requests/{id}` |
| Matching | `POST /client/requests/{id}/match`, `GET /client/requests/{id}/proposal`, `POST /client/requests/{id}/confirm` `{master_id}` |
| Orders (client) | `GET /client/orders`, `GET /client/orders/{id}`, `POST /client/orders/{id}/cancel`, `GET /client/orders/{id}/summary` |
| Contacts | `POST /contacts/click` `{master_id, channel, request_id?}` → `{href}` |
| Master | `GET/PUT /master/profile`, `GET /master/catalogue`, `GET /master/capabilities`, `POST /master/specialisations` (request), `POST /master/competencies` (declare), `POST /master/qualifications` (multipart with evidence), `…/withdraw` (§6b), `PUT /master/availability`, `POST /master/location`, `GET /master/offers`, `POST /master/orders/{id}/accept|decline|en-route|start|complete`, `POST /master/orders/{id}/schedule` |
| Work sheet | `POST /master/orders/{id}/worksheet`, `PATCH .../worksheet`, `POST .../worksheet/finalise`, `GET /master/commission` |
| Reviews / complaints | `POST /client/orders/{id}/review`, `POST /orders/{id}/complaints` |
| Notifications | `GET /me/notifications`, `POST /me/notifications/{id}/read` |
| Admin | users, masters (approve/reject/block), catalogue (§6a), master specialisations/competencies/qualifications (approve/verify/reject/revoke), requests without catalogue service, orders (status override), reviews, complaints, commission (settings, master limits, payments, limit increases, ledger), contact events (list/CSV), stats, audit log, AI principals |
| AI access | `GET /ai/v1/requests`, `/ai/v1/orders`, `/ai/v1/events`, `/ai/v1/masters/capacity`, `/ai/v1/contact-events` (read-only, scoped) |

## 5. Order state machine (R-ORD)

```
draft ──(submit)──► clarifying ──► matching ──► proposed ──(client confirm)──► offered
  (AI only if needed)        └─(no candidates)─► unserved
offered ──(master accept)──► accepted ──(immediate)──► en_route* ──► in_progress ──► completed ──► reviewed
        └─(decline/timeout)──► declined; request ► matching (next candidate, client confirms again)  ▲
accepted ──(reserved)──► scheduled (time agreed = reservation) ─┘ (en_route* on the day)
any pre-in_progress ──► cancelled (by client/master/admin, reason required)
* en_route writes the departure (START) record (D-Billable); arrival is recorded separately (`arrived_at`, no extra
  status); billable time = actual work time only (owner, 2026-11-04; rules Q-01)
```

- `draft`…`proposed`/`unserved` are **request** statuses (`service_requests.status`); `offered` onwards are
  **order** statuses (`orders.status`). An order row is created at client confirmation; a declined/expired order
  stays as history and a new order is created for the next confirmed candidate.
- Immediate flow = D-Immediate. Reserved flow maps D-Reserved "time agreement → reservation" to `scheduled`,
  "work" to `in_progress`.
- Reserved orders pass through `en_route` on the work day so the departure (START) is recorded consistently (Q-04).
- `reviewed` is terminal; `completed` remains valid without a review.
- Admin override: any transition with mandatory reason, audited, still writes history and events.
- Sequence (owner, 2026-11-04, Q-FINAL-01): option A only — client confirms the shown master, then the order row is
  created in `offered`. Master response timeout (Q-FINAL-02): 10 min immediate / 120 min reserved
  (`order_offers.expires_at`); configurable.
- Double assignment (planned D2, Q-FINAL-03): the `orders` row is the single assignment record from `offered` to
  `in_progress`; `orders.busy_range` + `EXCLUDE USING gist (master_id WITH =, busy_range WITH &&)` for those statuses
  (needs `btree_gist`), always under a lock on the master row (`docs/STAGE_C_BACKEND_PLAN.md` §14.8; storage shape
  Q-TECH-01).
- Rounds (owner, 2026-11-04): one matching run = one round; at most 3 per request; after the third declined/expired
  offer, or when a run has no candidate, the request becomes `unserved` and the client gets an in-app notification.
- Commission is charged only when the work sheet is finalised (Q-11), never on request, confirmation or acceptance.
- Client confirmation window (owner, 2026-11-04): 5 min (immediate) / 30 min (reserved), client-only timer. An
  unconfirmed or rejected proposal ends the round (`proposed → matching` or `unserved`); a shown master is not
  blocked and not excluded (Q-FINAL-03).
- Timers are run by a separate background worker process (Q-FINAL-03; plan §14.5).
- A master who reaches the commission limit keeps an already issued offer until it expires (may accept or decline);
  no new offer is created for them while `balance ≥ limit`.

## 6. Matching algorithm (R-MATCH)

1. Resolve service (W-ID optional) → its specialisation and effective qualification set; service chain must be `active`.
2. Candidate SQL: approved ∧ ¬blocked ∧ approved specialisation ∧ verified competency for the service ∧ every
   required qualification verified with `valid_until` ≥ today ∧ mode ∈ allowed(request type) ∧ ¬busy ∧
   unpaid_commission < limit ∧ request point inside work zone ∧ (immediate ⇒ location updated within freshness window,
   default 15 min).
3. Pre-sort by straight-line distance, take top K (default 10), call routing for ETA (fallback: distance / average
   urban speed, default 30 km/h).
4. Rank by ETA, then average rating (Bayesian-smoothed), then completed jobs count.
5. Proposal = #1; alternatives = next ≤2 whose ETA is within a configurable margin of #1 (default +10 min) (R-MATCH-04).
6. Persist `matching_run` + `matching_candidate` rows; emit `matching.completed`.

Also excluded (owner, 2026-11-04): masters who explicitly declined an offer for this request (an expired offer alone
does not exclude — Q-FINAL-03), and masters with an
active offer or live order for an overlapping time (definition and locking: `docs/STAGE_C_BACKEND_PLAN.md` §14).
Client confirmation re-checks the candidate under a lock on the master row before the offer is created.

All thresholds live in `system_settings` and are admin-editable later without deploy (**TD**).

## 6a. Catalogue management (R-CAT, CM)

**Model:** Category → Specialisation → Service. Every entity has an immutable UUID used internally; every service
also has an immutable, never-reused W-ID (W001–W070 only from the KVC import, W071+ assigned at creation to all
other services — Q-20). Statuses: categories and specialisations `active|inactive|planned|archived`; services
`draft|active|inactive|planned|hold|rejected|archived`. Effective status of a service = the most restrictive of its
chain, so deactivating a category hides everything below it without touching child rows.

**Admin API** (`/api/v1/admin/catalogue/...`, `AdminUser` dependency on the router; frontend checks are cosmetic):
- `GET tree` — whole catalogue (all statuses) + qualifications + `catalogue_role`/`can_create`; filtering and search
  happen in the admin UI (catalogue size is small). *Implemented.* Every service also carries (step 4.5.2, R-CAT-03)
  `eligible_masters`, `orderable` and `orderable_reasons` [{code, details}] from `catalogue.availability`, computed
  on every read from current rows (nothing stored, a fixed number of queries): orderable = service, its
  specialisation and category all `active` (`SERVICE_NOT_ACTIVE`, `SPECIALISATION_NOT_ACTIVE`,
  `CATEGORY_NOT_ACTIVE`), the
  regulated-service gate passes (`QUALIFICATION_NOT_CONFIGURED`) and ≥ 1 master passes the one eligibility rule
  `eligibility.eligible` (R-MST-11; else `NO_ELIGIBLE_MASTERS`). "Verified matching capacity" (R-CAT-03) is this
  rule only; availability mode, work zone and commission limit are added by matching (R-MATCH-02). Services under
  non-active parents are listed with their reasons, never dropped. Only the tree carries these fields.
- `POST categories|specialisations|services` — create; parent must exist and not be archived; services get the
  next W-ID from `catalogue_w_id_seq` in the same transaction (the request body cannot set it).
- `PATCH .../{id}` — name, description, restrictions, `review_note`, `qualification_required`, `risk_level`, parent move
  (`category_id` / `specialisation_id`). Unknown fields such as `id` and `w_id` are rejected (422 `VALIDATION_ERROR`).
- `POST .../{id}/status` `{status, reason?}` — allowed transitions per level, e.g. service `draft → inactive|planned|
  active|rejected` (approve/reject a suggestion, reason required for reject); `hold → active` only via
  `POST services/{id}/activate-hold` `{confirm: true, reason}`; regulated-service gate blocks `active`
  (409 `QUALIFICATION_NOT_CONFIGURED`); missing capacity does not block `active` but the service stays
  non-orderable (R-CAT-03), shown as such in the UI.
- `PUT categories/order`, `PUT categories/{id}/specialisations/order`, `PUT specialisations/{id}/services/order`
  `{ids: [...]}` — must list exactly the current non-archived siblings.
- `GET|POST|PATCH qualifications` (incl. verification rules, `draft → active → archived`),
  `PUT services/{id}/qualifications` (primary), `PUT specialisations/{id}/qualifications` (whole specialisation only).
- `POST impact` (R-CAT-18, step 4.5.4.2; read-only) `{entity: category|specialisation|service, id, change}` with
  `change.kind` = `status {status, reason?}` (all three), `move {target_id}`, `qualification_required {value}`,
  `requirements {qualification_ids}` (specialisation, service), `activate_hold {reason}` (service); anything else
  422 `IMPACT_CHANGE_NOT_SUPPORTED`, unknown entry 404. It locks the scope (category → specialisation → service →
  qualification type; `lock_timeout` 3 s → 409 `CATALOGUE_BUSY`), runs the real `prepare_*` inside `dry_run`
  (an invalid change returns exactly the real 409/422) and rolls back: nothing written, audited or announced, all
  locks released. Response: `basis` [{kind, id, version}] of every row the impact depends on; per affected
  service `before`/`after` {orderable, eligible_masters, reasons}; `stops_being_orderable`, `becomes_orderable`;
  `masters` {by_specialisation_status, by_competency_status, losing_eligibility {total, items ≤ 100 of
  {master_id, full_name}}} (no contact data); `open_requests: null` (requests arrive in step 5); `notes`;
  `computed_at` — master counts are a snapshot (master decisions do not change catalogue versions).
- Applying a previewed change (step 4.5.4.3): the change routes the preview covers (`status` of category /
  specialisation / service, `PATCH` of specialisation / service, `PUT …/qualifications`, `activate-hold`) accept an
  optional `expected_basis` (the preview's `basis`, ≤ 2000 unique entries). When it is sent, the same scope is
  locked (same order and modes) and must equal it exactly — same rows, nothing added or gone (new or moved
  services/specialisations, both branches of a move, old and new qualification types), same versions —
  otherwise 409 `IMPACT_PREVIEW_OUTDATED` `{changed, added, removed}` and nothing is written. The operation then
  runs in the same transaction under those locks (no window, no lock upgrade). A `PATCH` with a new parent uses the
  move scope; any other `PATCH` the entry's own scope. Without `expected_basis` the behaviour is unchanged
  (row locks + `expected_version`). The admin UI of step 4.6 always previews and sends the basis.
- *Planned (step 6, needs the KVC file):* KVC import (Q-20): `POST imports` (file upload → staged rows), `GET imports/{id}/rows`, `PATCH imports/{id}/rows/{row}`
  `{target_specialisation_id, decision}`, `POST imports/{id}/apply` `{confirm: true}`, `POST imports/{id}/discard`.
  Apply inserts new services only; it never updates or merges existing ones. File parsing (CSV/XLSX — adds
  `openpyxl` for XLSX and `python-multipart` for uploads) is finalised when the file is available (Q-01b).
- Environment transfer (R-CAT-15/16), *implemented:* `GET export` (production) → Ed25519-signed JSON package (R-CAT-17);
  `POST sync-imports` (staging; the package is sent as the JSON body → preview),
  `POST sync-imports/{id}/apply` `{confirm: true, apply_updates: [uuid…], keep_active: [uuid…]}`.
Every mutation runs in one transaction with `record_audit(before, after)` and a `catalogue.*` domain event.

**Concurrency (step 4.5.3.1, owner decision 2026-11-02):** every change of an existing category, specialisation or
service (`PATCH`, `status`, `qualifications`, `activate-hold`) and every qualification-type status change requires
`expected_version` (the version of the entry as loaded; missing → 422). The service locks the rows first, in one
order for all operations — category → specialisation → service → qualification types, ascending ID within a level,
a parent never after its child: the changed row `FOR UPDATE`, parents that are only checked `FOR SHARE` (move
target, the service's specialisation for the regulated-service gate, required qualification types). It then
re-reads the locked row, compares `version` (≠ → 409 `VERSION_CONFLICT` with the current `version` and `status`;
nothing is written, audited or announced), runs the usual checks and bumps `version` from the current value.
Qualification-type edits (`PATCH qualifications/{id}`) and creation take no version. Known gap: the order endpoints
(`PUT …/order`) take no version and no lock — they do not affect orderability; to be addressed later (IMPLEMENTATION_PLAN).
The admin UI sends the loaded `version`; on `VERSION_CONFLICT` it shows the message and reloads the tree.

**Environment export/import (production → staging, R-CAT-15/16)**
- *Package:* JSON `{format: "fikso-catalogue/1", source_environment, catalogue_role, key_id, signature, exported_at, categories,
  specialisations, services, qualifications, requirement links}`; each entity with its UUID, W-ID (services),
  parent UUID, fields, status, `version`. Excludes masters, requests, KVC staging, audit, user IDs.
- *Matching rule:* entities are matched by UUID **and** W-ID together.
  - UUID and W-ID both absent in the target → **create** with the same UUID and W-ID.
  - Same UUID and same W-ID, content equal → **unchanged**.
  - Same UUID and same W-ID, content differs → **update candidate**: applied only if the admin selects it **and**
    the target row has not been edited locally since its last import/creation (`last_sync_hash` matches);
    otherwise a conflict. Never applied by default.
  - UUID exists with another W-ID, W-ID exists with another UUID, KVC W-ID with non-KVC source (or vice versa),
    or a parent missing from both target and package → **identity conflict**: the whole package is rejected
    with a report; nothing is written.
- *Safety:* preview first (dry run, nothing written); one transaction on apply; package checksum verified and
  recorded, so the same package cannot be applied twice; sequence advanced past imported W-IDs; the target's own
  entities not in the package are never touched (no deletes, no archive by omission).
- *Status:* `draft`, `inactive`, `planned`, `hold`, `rejected`, `archived` are carried as-is; `active` arrives as
  `inactive` unless the admin ticks "keep active" per entity, and the regulated-service gate still applies. HOLD is
  never activated by an import.
- *W-ID authority (Q-24, R-CAT-16):* setting `CATALOGUE_ROLE` = `issuer` (production only — startup fails if
  production has another value, or a non-production environment claims `issuer`), `receiver` (staging) or
  `isolated` (local/test, throwaway DBs with fixtures). Only `issuer` may create catalogue entries (categories,
  specialisations, services, qualifications), run the seed or the KVC import (`receiver`: 409
  `W_ID_AUTHORITY_REQUIRED`; `isolated` may create fixture entries in its throwaway DB). `receiver` accepts only
  production packages with a valid signature; `issuer` accepts none (export only). Edits made on staging that diverge from production are reported as conflicts on the next refresh,
  never overwritten.

**Signing (R-CAT-17, Ed25519, replaces HMAC):**
- Production: `CATALOGUE_SIGNING_PRIVATE_KEY` (PEM/base64 Ed25519 private key) + `CATALOGUE_SIGNING_KEY_ID`. It signs
  the canonical JSON of the package (sorted keys, no whitespace); the package carries `key_id` and `signature`.
- Staging: `CATALOGUE_TRUSTED_PUBLIC_KEYS` = JSON map `{key_id: public key}`; several entries allow rotation (add the
  new key on staging, switch production, then remove the old key). Unknown `key_id` → `PACKAGE_KEY_UNKNOWN`.
- Startup check: `issuer` needs the private key and key ID; `receiver` needs ≥1 trusted public key and must **not**
  have a private key; `isolated` may sign with a throwaway local key (tests), which no other environment trusts —
  and non-`issuer` packages are refused by the role check anyway. Holding only public keys, staging cannot sign a package that verifies as Production.
- Library: `cryptography` (Ed25519). `CATALOGUE_EXPORT_KEY` is removed.
- *Coverage:* the signature covers the **entire** package — every field except `signature` itself: format, source
  environment, role, `key_id`, `package_id`, `exported_at`, all entities with UUIDs, W-IDs, parents, statuses,
  versions, and all requirement links. Any change anywhere invalidates it.
- *Replay protection:* each package has a unique `package_id`; staging records `package_id`, `package_sha256` and
  `exported_at` of applied packages; a package already applied (same ID or hash) is refused
  (`PACKAGE_ALREADY_APPLIED`), and a package exported *before* the newest applied one is refused
  (`PACKAGE_OUTDATED`) so an old production state cannot be replayed over a newer one.
- *Key revocation:* `CATALOGUE_REVOKED_KEY_IDS` (staging) lists retired key IDs; packages signed with them are
  refused (`PACKAGE_KEY_REVOKED`) even if the key is still in the trusted map. Rotation: add new public key →
  production switches `key_id` → revoke the old ID → remove it.
- *Key secrecy:* the private key is a `SecretStr`, never serialised into packages, API responses, logs, audit or
  events; only `key_id` appears. Covered by tests.

**Master capabilities:** master requests specialisations (active/planned only) and declares competencies for
services under them (not `draft`/`rejected`/`archived`); admin approves/rejects/revokes each; qualification
evidence uploaded by the master and verified by an admin against the qualification's rules. Revoking a
specialisation or qualification makes the dependent competencies ineligible at once (checked by the matching
predicate; status rows keep history).

**Client flow:** `GET /public/catalogue` → category → specialisation → service (only orderable entries; R-CAT-03);
"Nav sarakstā / neesmu pārliecināts" opens free text → AI clarification (§9.1), which may map only to an orderable
service → otherwise unserved `no_catalogue_service` for admin review (Q-23). The client never selects a master.
Deep link `?w=` resolves through `by-w-id`. The request stores a `catalogue_snapshot`.

**Seed:** `python -m app.cli seed-catalogue` (run once in production — or in an isolated local/test DB; staging gets
it via export/import): CM 3 categories, 24 specialisations
and the suggested services in `docs/CATALOGUE_SEED.md`, `source=seed_cm_v1`, services `draft` with the fixed W071–W142;
idempotent by `source_ref`, insert-missing only, never activates anything. Everything after setup — including
seed review and KVC import — is done in the Admin Panel.

## 6b. Master specialisations, competencies and qualifications (Phase 2 step 4; R-MST-08..16, R-AUTH-03)

**Services:** `master_capabilities` (applications and admin decisions), `eligibility` (one SQL predicate +
reason explainer), `uploads` + `integrations/storage` (evidence files), `master_admin` (admin decision core).

**Master API** (`/api/v1/master/...`, role master; every query filtered by the caller's own master profile — other
masters' IDs return 404):
- `GET capabilities` — own approval status, specialisations, competencies, qualifications, each competency with
  `eligible` and `reasons[]`; expiry warnings.
- `GET catalogue` — specialisations `active|planned` with their services (not `draft|rejected|archived`) and required
  qualification types (names and rules only).
- `POST specialisations` `{specialisation_id}`, `POST specialisations/{id}/withdraw`.
- `POST competencies` `{service_id}`, `POST competencies/{service_id}/withdraw`.
- `POST qualifications` (multipart: `qualification_id`, `document_number?`, `valid_until?`, `files[]`) — validated
  against the qualification's rules; `POST qualifications/{id}/withdraw`; `GET qualifications/{id}/files/{file_id}`.
- Errors: `SPECIALISATION_ALREADY_EXISTS`, `SPECIALISATION_NOT_AVAILABLE`, `SPECIALISATION_NOT_REQUESTED`,
  `COMPETENCY_ALREADY_EXISTS`, `SERVICE_NOT_AVAILABLE`, `CANNOT_WITHDRAW`, `MASTER_PROFILE_REJECTED`,
  `QUALIFICATION_TYPE_NOT_ACTIVE`, `DOCUMENT_REQUIRED`, `DOCUMENT_NUMBER_REQUIRED`, `EXPIRY_DATE_REQUIRED`,
  `VALID_UNTIL_IN_PAST`, `VALIDITY_TOO_LONG`, `QUALIFICATION_SUBMISSION_PENDING`, `QUALIFICATION_STILL_VALID`,
  `TOO_MANY_FILES`, `FILE_EMPTY`, `FILE_TOO_LARGE` (413), `UNSUPPORTED_FILE_TYPE` (415); not-found IDs → 404.
  Owner decisions 2026-11-02 (OPEN_QUESTIONS "Master withdrawals", "Rejected master profile", "Submission checks"):
  only pending items can be withdrawn (`CANNOT_WITHDRAW` otherwise); a `rejected` profile is read-only — every
  write, withdrawals included, returns `MASTER_PROFILE_REJECTED`; submissions only for `active` types, `valid_until`
  not in the past and ≤ today + `max_validity_months` (Riga calendar).
- Submission (renewal decision 2026-11-02): one transaction with the master row locked; allowed when no verified
  submission of the type is still valid and none is pending; the new row is `submitted`, older rows never change.
- The reverse proxy must cap the request body (≈ 55 MB for 5 × 10 MB plus form overhead): the API checks each file
  while reading it, but the multipart body is received before the endpoint runs — also for a request that is then
  refused by the upload rate limit (`RATE_LIMIT_UPLOAD`, per client IP, in-process; failed attempts count).
- Known limitation: the files of one submission are listed by upload time, then ID; their upload order is not stored
  or guaranteed (no requirement asks for it).

**Admin API** (`/api/v1/admin/masters/...`, role admin, every decision audited + `master.*` domain event):
- `GET /admin/masters` (filters: `approval_status`, `has_pending`; newest first; `limit`/`cursor`; per master the
  number of pending specialisations, competencies and qualifications), `GET /admin/masters/{id}` (profile decision
  and `version`; every specialisation, competency and submission incl. history with `decided_by`, `version`,
  full document number, file metadata and expiry flags; per competency `eligible` + `reasons` from the same
  read model as the master's screen, i.e. `eligibility.explain`; verifier instructions of the submitted types),
  `GET /admin/review-queue` (`?kind=`; `requested` specialisations, `declared` competencies, `submitted`
  qualifications across masters, oldest first, with `version` for the decision). Accounts with `deleted_at` are
  not listed (404 on detail). Reads are not audited; storage keys and hashes are never returned.
- Every decision body carries `expected_version` (the version the admin saw).
- `POST {id}/approve` `{expected_version}`, `POST {id}/reject` `{expected_version, reason}` (R-AUTH-03, step 4.4.4;
  reason 1–1000 chars, required; unknown fields → 422); both return the admin detail. Approval clears
  `decision_reason`, so an earlier rejection is never shown as current (it stays in `audit_log`). A profile
  decision never changes the user's block status (`/admin/users/{id}/block|unblock`). Deleted accounts → 404
  `MASTER_NOT_FOUND` for every decision.
- `POST {id}/specialisations/{spec_id}/approve` `{expected_version}`, `.../reject|revoke` `{expected_version, reason}`
  (step 4.4.5; `spec_id` = catalogue specialisation UUID, the row key with the master; reason required for reject
  and revoke by owner instruction 2026-11-02, none accepted on approve). Approval needs the catalogue entry still
  `active`/`planned` (else 409 `SPECIALISATION_NOT_AVAILABLE`; reject stays possible) and changes no competency or
  qualification; revocation excludes the master through eligibility, competency rows unchanged. Another master's
  or a never-requested specialisation → 404 `SPECIALISATION_NOT_FOUND`.
- `POST {id}/competencies/{service_id}/verify` `{expected_version}`, `.../reject|revoke` `{expected_version, reason}`
  (step 4.4.6; `service_id` = catalogue service UUID, the row key with the master; reason required for reject and
  revoke, none accepted on verify — owner decision 2026-11-02). Verification runs under the master row lock and is
  refused with 409 (code = first failing reason, `details.reasons` = all) unless: the service is not
  `draft/rejected/archived` (`SERVICE_NOT_AVAILABLE`), and `eligibility.explain` reports none of
  `PROFILE_NOT_APPROVED`, `SPECIALISATION_NOT_APPROVED`, `QUALIFICATION_NOT_CONFIGURED`,
  `QUALIFICATION_TYPE_NOT_ACTIVE`, `QUALIFICATION_EXPIRED`, `QUALIFICATION_REVOKED`, `QUALIFICATION_MISSING`
  (Riga date, `valid_until` inclusive). `inactive`, `planned`, `hold` and `active` services are verifiable;
  verification never changes the service status (HOLD is never activated automatically). `USER_NOT_ACTIVE` does
  not block verification and the verification never lifts the block; eligibility still excludes a blocked master.
  Revocation changes only the competency row (owner decisions 2026-11-02).
- Bulk competency verification (step 4.4.8; R-MST-14, Q-28, owner decision 5): only explicitly selected `declared`
  competencies of one master, only for non-regulated services — no `qualification_required` flag on the service or
  its specialisation and no effective qualification requirement (`eligibility.required_qualification_ids`);
  regulated competencies are verified one by one. No bulk reject/revoke, no automatic selection, nothing else
  changes (specialisation, service, user). At most 50 items per request (`BULK_VERIFY_MAX`; enforced by the API
  schema and again by the service: 422 `BULK_VERIFY_INVALID` for an empty, duplicate or oversized selection).
  - `POST {id}/competencies/bulk-verify/preview` `{service_ids}` (1–50, unique): per selected item `status`,
    `expected_version`, `verifiable` and every `reasons[]` (`COMPETENCY_NOT_FOUND`, `VERSION_CONFLICT`,
    `INVALID_TRANSITION`, `REGULATED_SERVICE`, then the verification blockers of single verification), plus
    `applicable` for the whole set. Reads only; nothing is written or audited.
  - `POST {id}/competencies/bulk-verify` `{items: [{service_id, expected_version}], confirm: true}` (1–50, unique;
    `confirm` must be the JSON value `true`): one transaction — master row `FOR UPDATE`, then the selected
    competency rows `FOR UPDATE` in `service_id` order (stable lock order), every check of the preview repeated
    under the locks. Any failing item → 409 `BULK_VERIFY_REJECTED` with `details.items` = every failing item and
    its reasons (stale versions show the current `status`/`version`), nothing written. Otherwise every item is
    verified with decider and time, `version + 1`, one `audit_log` entry and one `domain_event` each, and one
    commit; an error while writing rolls back every decision of the request. Unknown/deleted master → 404.
- `POST {id}/qualifications/{mq_id}/verify` `{expected_version}`, `.../reject|revoke` `{expected_version, reason}`
  (step 4.4.7; `mq_id` = the submission's own UUID, checked against the master). Verified exactly as submitted: no
  document fields or reason accepted (422); `submitted → verified|rejected`, `verified → revoked`; rejected and
  revoked rows are final (the master submits again; renewal rows never touch earlier ones). Verification is
  refused (409, all reasons in `details.reasons`) for an inactive qualification type
  (`QUALIFICATION_TYPE_NOT_ACTIVE`) or a document already expired on the Riga date (`QUALIFICATION_EXPIRED`;
  `valid_until` inclusive). Decisions never change document data or files; eligibility follows at query time
  (revocation excludes at once, competency rows unchanged).
- `GET {id}/qualifications/{mq_id}/files/{file_id}?mode=view|download` (step 4.4.3): the file is resolved by master, submission, file ID, entity type `qualification` and owner together; any mismatch, an
  unknown ID or a deleted account → the same 404 `FILE_NOT_FOUND`; a missing stored object → 404
  `FILE_UNAVAILABLE`, nothing logged. Served by the same `file_response` as the master route (headers, inline
  only with CSP sandbox, file name = attachment UUID + extension of the detected type); `attachment.viewed` /
  `attachment.downloaded` is committed with the admin as actor, master and submission before streaming.
- Decision core (`services/master_admin.decide`, owner decisions 2026-11-02): one transaction with the master row
  locked (`SELECT … FOR UPDATE`, the same lock as the master's own writes); `expected_version` ≠ current →
  409 `VERSION_CONFLICT` (also for a repeated request), source status not allowed → 409 `INVALID_TRANSITION`,
  missing required reason (profile reject; specialisation, competency and qualification reject/revoke) → 422
  `REASON_REQUIRED`, other master's or unknown record → 404, non-admin or the
  master's own account → 403 `DECISION_FORBIDDEN`. Transitions: profile `pending_approval|rejected → approved`,
  `pending_approval → rejected` (an approved master is restricted by blocking the user); specialisation
  `requested → approved|rejected`, `approved → revoked`; competency `declared → verified|rejected`,
  `verified → revoked`; qualification `submitted → verified|rejected`, `verified → revoked`. `rejected` and
  `revoked` are final for the row: a new review starts only with the master's re-application. Each decision
  sets `decided_by`, `decided_at`, `decision_reason`, bumps `version`, and writes `audit_log` (full state before
  and after, incl. the earlier decision) + a `master.<kind>.<status>` event (without the free-text reason).
- Catalogue additions (step 4.5, §6a): `POST /admin/catalogue/impact` (R-CAT-18; read-only impact preview) and
  `eligible_masters` / `orderable` / `orderable_reasons` per service in `GET /admin/catalogue/tree` (R-CAT-03).
  `eligible_masters` is computed **only** by the R-MST-11 predicate (`eligibility.eligible`, no separate query), so
  declared competencies, unapproved profiles, revoked specialisations and expired qualifications are never
  counted.

**Rules:** see DATABASE §3.3 and R-MST-11..16. Verification errors are explicit (`SPECIALISATION_NOT_APPROVED`,
`QUALIFICATION_MISSING`, `QUALIFICATION_EXPIRED`, `QUALIFICATION_TYPE_NOT_ACTIVE`, `SERVICE_NOT_AVAILABLE`, …): the
error code is the first failing reason and `details.reasons` lists every reason with its failing item. Revocation/expiry never rewrites competency rows; the eligibility predicate excludes the
master at once. Master approval/rejection follows the same pattern; a rejected master keeps their history.
Competency verification also refuses a regulated service without configured requirements
(`QUALIFICATION_NOT_CONFIGURED`), using the eligibility building blocks, never a separate check
(`master_admin.verification_blockers`).

**Eligibility reasons** (R-MST-12, `services/eligibility.explain`): every failing condition is reported, in this
order, with the failing item in `details`: `USER_NOT_ACTIVE`, `PROFILE_NOT_APPROVED`, `SPECIALISATION_NOT_APPROVED`
(`status` or none), `COMPETENCY_NOT_VERIFIED` (`status` or none), `QUALIFICATION_NOT_CONFIGURED` (regulated
service with no effective requirement), then per required qualification (by name)
`QUALIFICATION_TYPE_NOT_ACTIVE`, `QUALIFICATION_EXPIRED` (`valid_until`), `QUALIFICATION_REVOKED` or
`QUALIFICATION_MISSING` (`latest_status`: submitted, rejected, withdrawn or none). The reasons are built from the same
SQL expressions as `eligible()`; a mismatch is a programming error and raises.

**Evidence binding and orphans:**
- Files are uploaded only **in the same multipart request** that creates the qualification submission — there is no
  stand-alone upload endpoint, so a file cannot exist before or apart from its submission.
- Each attachment row stores `owner_user_id`, `entity_type='qualification'` and `entity_id` = that submission. Downloads
  resolve the file by **all** of: attachment ID, submission ID from the URL, entity type, and (for masters) the
  submission's `master_id` = caller's profile. Any mismatch (other master, other submission, guessed ID) → 404.
- Storage writes happen before the DB commit; if the transaction fails, the written objects are deleted in the same
  request. A `cleanup-orphan-files` CLI removes storage objects that have no attachment row and are older than 24 h
  (crash safety); it never touches files that have a row.
- Withdrawing, rejecting or revoking a submission keeps its files linked to it (history, R-MST-16); they are removed
  only by the retention policy (Q-12/Q-27).

**Evidence files:** `integrations/storage` interface (`put`, `open`, no URL generation); `LocalStorage` (dev/test,
directory outside any static root, `STORAGE_LOCAL_DIR`), S3-compatible private bucket later (Q-10). Upload:
multipart via `python-multipart`; size and count limits (10 MB, 5 files); type by magic bytes (PDF `%PDF-`, JPEG
`FF D8 FF`, PNG signature, WebP `RIFF…WEBP`, HEIC `ftyp` brands `heic/heix/mif1/msf1`); random storage key; sha256;
rate-limited (`RATE_LIMIT_UPLOAD`). Access: streamed by the API after the ownership/admin check with
`X-Content-Type-Options: nosniff`, `Cache-Control: no-store`; `?mode=download` (`Content-Disposition: attachment`)
or `?mode=view` (inline, images/PDF only, with `Content-Security-Policy: sandbox`). Every access is logged in
`audit_log` as `attachment.viewed` or `attachment.downloaded` (actor, attachment, submission; no content).

**Qualification validity:** `valid_until` is **inclusive** — valid through the end of that calendar day, expired
from the next day. "Today" is always the business date in `Europe/Riga` (`BUSINESS_TIMEZONE`), computed in one
helper (`business_today()`, SQL `(now() AT TIME ZONE 'Europe/Riga')::date`), used by eligibility, verification, UI
warnings and tests (which pass an explicit date).

**UI:** master area "Manas specializācijas un kvalifikācijas"; admin "Meistari" (list, detail, review queue) and
catalogue additions (eligible count, impact dialog). Latvian strings in `lv.ts`.

## 7. Authentication and authorisation (R-AUTH, R-ROLE)

- **Login:** email or phone + password (Q-06 default: email + password, verified phone stored). Passwords hashed
  with Argon2id.
- **Tokens (TD):** short-lived JWT access token (15 min) in memory; refresh token (30 days) as `HttpOnly; Secure;
  SameSite=Lax` cookie, stored hashed in `auth_session` so it is revocable (logout, block, password change).
- **Authorisation:** FastAPI dependencies `require_role(...)` + service-level ownership checks
  (`order.client_id == user.id`, `order.master_id == user.master.id`). Never trust IDs from the client alone.
- **Field-level privacy:** masters receive approximate area until assignment; exact address/phone after the master accepts the offer (`accepted`).
  Clients receive master phone/WhatsApp link only via `POST /contacts/click` (recorded) (R-CT).
- **Rate limits:** login, registration, contact clicks, uploads, AI clarification (per IP + per user).
- **Audit:** `audit_log` for admin and service-principal writes.

## 8. Integrations

| Integration | Use | Fallback | Status |
|---|---|---|---|
| Maps / geocoding / autocomplete | Address autocomplete, coordinates (R-REQ-03) | Retry message; request blocked without coordinates | Provider: Q-02 |
| Routing / ETA | ETA (R-MAP-05) | Distance-based estimate | Provider: Q-02 |
| Map tiles | Client map (R-MAP) | — | Provider: Q-02 |
| OpenAI | Clarification micro-agent (R-AI) | Manual category selection | Model via env `OPENAI_MODEL` |
| SMS | Notifications (§18) | In-app only | Provider: Q-08 |
| Object storage | Photos (R-REQ-05, R-WS-01) | — | S3-compatible, private |

**Notifications (TD event set, minimal):** master receives new offer; client: master accepted / en route / order
completed (with work summary link) / no master found; master: approved/rejected, commission limit reached.
In-app inbox always; SMS for "new offer" and "master accepted/en route" (time-critical) where SMS is configured.

## 9. AI layer

### 9.1 Clarification micro-agent (R-AI)
- Trigger: backend decides — if client selected an orderable service and description ≥ minimal length, skip AI;
  otherwise call AI classifier.
- Call: OpenAI with structured (JSON schema) output `{status: "clear"|"needs_question"|"unclear", service_id?, confidence,
  question?}`; input = description + previous Q/A + list of orderable services (service ID, W-ID if any,
  names of service/specialisation/category). No PII.
- Loop limit enforced by backend: max 2 questions. Stop when `clear` with confidence ≥ threshold.
- AI `service_id` validated against the orderable catalogue; otherwise treated as unclear → manual category choice
  or free-text request for admin review (R-REQ-08). AI never creates catalogue entries.
- Persist `ai_clarification` + messages; emit `ai.clarification.completed`.

### 9.2 AI-ready data and access API (R-AIR)
- **Data:** `domain_event` append-only log (type, aggregate, actor, payload JSON, occurred_at) + normalised tables
  (requests, matching runs, orders, status history, work sheets, ledger, contact events).
- **Access:** `service_principal` with hashed API keys, explicit scopes (`read:requests`, `read:orders`,
  `read:events`, `read:masters`, `read:contacts`; write scopes reserved, none granted in MVP), expiry,
  revocation, IP allow-list optional, every call audited.
- **PII:** AI read endpoints return pseudonymised IDs and coarse location (district/grid), no phone/full address
  unless a dedicated scope is granted by the owner.
- **Proof (R-AIR-05):** contract tests showing an AI principal can read events/orders, is denied without scope,
  and is denied immediately after revocation.

## 10. PWA (R-PWA)

- Web app manifest (name, icons 192/512 + maskable, `display: standalone`, theme colour, `start_url`).
- iOS meta tags (`apple-touch-icon`, `apple-mobile-web-app-capable`), install instructions screen for iOS.
- Service worker: precache app shell and static assets; API calls network-only (no stale business data);
  offline page. Update prompt on new version.
- No promises of push notifications, background location or native features.

## 11. Website integration (R-WEB)

- fiksoapp.eu stays on Hostinger, unchanged URLs. Only the "Pasūtīt meistaru" button hrefs change to
  `https://<app domain>/pieteikums/jauns?w=W0xx` (route decided 2026-11-04; domain per Q-09).
- Website buttons add `&src=web` (owner, 2026-11-04); the app keeps `w` and `src` through login/registration and
  sends `src` with the request; the backend maps listed values only (`web` → `source='website_deeplink'`, otherwise
  `app`).
- App resolves `w` via `by-w-id`; unknown/non-orderable/HOLD → generic start. Optional `utm_*` passthrough is not required.
- CORS: only the app origin may call the API; the website never calls the API directly.

## 12. Deployment and operations (R-OPS)

- **Environments:** local (docker-compose: Postgres + backend + frontend dev), staging, production.
- **Hosting (TD, Q-10):** managed PaaS for backend (container), static hosting/CDN for the PWA, managed PostgreSQL
  with automated daily backups + point-in-time recovery, S3-compatible storage. All accounts owned by FIKSO.
- **CI (GitHub Actions):** lint, typecheck, tests, build, migration check on every PR; deploy on tag.
- **Rollback (D-Rollback):** immutable versioned releases; redeploy previous version in one step. Migrations follow
  expand/contract so the previous app version remains compatible with the migrated schema.
- **Backups:** daily automated + PITR; monthly restore test to staging documented.
- **Observability:** structured JSON logs with PII redaction, request IDs, error tracking, uptime check.
- **Config:** env vars (`CATALOGUE_ROLE`, `CATALOGUE_SIGNING_*`, `CATALOGUE_TRUSTED_PUBLIC_KEYS`, `STORAGE_*`,
  `UPLOAD_*`, `DATABASE_URL`, `JWT_SECRET`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `MAPS_*`, `SMS_*`,
  `STORAGE_*`, `APP_ORIGIN`, `CORS_ORIGINS`), documented in `.env.example`.
