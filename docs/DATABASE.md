# FIKSO MVP — Database Design (PostgreSQL)

Version 1.1 · 2026-10-31 (catalogue model per CM). Source entities (D-Data, §14): Users (client, master, admin); Masters (competency,
available/not, work zone); Jobs (client, master, address, time, status); Reviews (rating, comments).
Extended by §14.1, P22.17, A17, F25. Requirement IDs refer to `docs/REQUIREMENTS.md`.

## 1. Conventions

- PostgreSQL 16+ (local dev 18). Migrations with Alembic only; SQLAlchemy 2.x models.
- Primary keys: `uuid` (v7 or `gen_random_uuid()`), so IDs are stable and non-guessable (masters' "stable internal
  identifier", F25.2). W-ID is a separate natural key.
- Timestamps: `timestamptz`, UTC; every table has `created_at`, mutable tables `updated_at`.
- Money: `numeric(12,2)` EUR; rates `numeric(5,4)` (0.2500 = 25 %). Never `float`/`real`.
- Coordinates: `numeric(9,6)` lat/lon (**TD**; PostGIS optional later — Q-03).
- Enums: PostgreSQL `text` + `CHECK` constraints (easier to evolve than native enums).
- Soft delete only where history matters (`users.deleted_at`); business history is never deleted.
- Naming: snake_case, plural table names, FK `<entity>_id`, indexes `ix_<table>_<cols>`.

## 2. Entity overview

```
catalogue_categories 1─* catalogue_specialisations 1─* catalogue_services (UUID + W-ID, both immutable)
qualifications *─* catalogue_services (primary) / catalogue_specialisations (whole-specialisation only)
catalogue_import_batches 1─* catalogue_import_rows ─0..1 catalogue_services (KVC staging)
users 1─1 master_profiles 1─* master_specialisations *─1 catalogue_specialisations
master_profiles 1─* master_competencies *─1 catalogue_services
master_profiles 1─* master_qualifications *─1 qualifications
users 1─* auth_sessions                     master_profiles 1─1 master_locations
master_profiles 1─* master_portfolio_items
service_requests *─1 users(client) *─0..1 catalogue_services   service_requests 1─* attachments
service_requests 1─0..1 ai_clarifications 1─* ai_clarification_messages
service_requests 1─* matching_runs 1─* matching_candidates
service_requests 1─0..1 orders *─1 master_profiles
orders 1─* order_status_history   orders 1─0..1 order_departures   orders 1─* worksheets(versions)
orders 1─0..1 reviews   orders 1─* complaints   orders 1─0..1 commission_ledger(charge)
master_profiles 1─* commission_ledger   master_profiles 1─* commission_limit_changes
contact_click_events *─1 master_profiles, *─0..1 service_requests
domain_events, audit_log, notifications, system_settings, commission_settings, service_principals
```

## 3. Tables

### 3.1 Identity and access
**users** — `id`, `role` CHECK in (`client`,`master`,`admin`), `email` (unique, citext), `phone` (E.164, unique
nullable), `password_hash`, `full_name`, `status` CHECK in (`active`,`blocked`), `blocked_reason`, `last_login_at`,
`deleted_at`. Index: `(role, status)`.

**auth_sessions** — `id`, `user_id` FK, `refresh_token_hash` unique, `expires_at`, `revoked_at`, `user_agent`.
Index: `(user_id) WHERE revoked_at IS NULL`.

**service_principals** (AI-ready access) — `id`, `name`, `api_key_hash` unique, `scopes text[]`, `expires_at`,
`revoked_at`, `created_by` FK users. CHECK scopes ⊆ allowed set (enforced in app).

**audit_log** — `id`, `actor_type` (`user`,`service_principal`,`system`), `actor_id`, `action`, `entity_type`,
`entity_id`, `before jsonb`, `after jsonb` (PII-redacted), `reason`, `created_at`. Append-only. Index:
`(entity_type, entity_id, created_at)`.

### 3.2 Catalogue (R-CAT)
All three levels share: `id uuid` PK (system-generated; immutable — trigger rejects `UPDATE` of `id`), `name`
(Latvian), `description`, `status`, `sort_order int`, `source` CHECK in (`seed_cm_v1`,`kvc_v1`,`admin`),
`source_ref` (row key in the source; unique with `source` when not null — makes seed/import idempotent),
`status_reason`, `version int` (incremented on every change; optimistic concurrency for admin changes via `expected_version`, step 4.5.3.1), `last_sync_hash` (content hash when last written by
an environment import — detects later local edits), `created_by`, `updated_by`, `created_at`, `updated_at`.
No `DELETE` is exposed and a trigger rejects `DELETE` on all catalogue tables; `archived` (and `rejected` for
suggestions) replace deletion (R-CAT-09). FKs `ON DELETE RESTRICT`.
Seed rows use deterministic UUIDs (`uuid5(FIKSO catalogue namespace, source_ref)`), so the seed has the same UUIDs
and W-IDs in every environment.
Partial unique `(parent_id, lower(name)) WHERE status NOT IN ('archived','rejected')` per level.

**catalogue_categories** — `status` CHECK in (`active`,`inactive`,`planned`,`archived`).

**catalogue_specialisations** — `category_id` FK, `status` CHECK in (`active`,`inactive`,`planned`,`archived`),
`qualification_required bool default false` — set only by an admin when the *whole* specialisation requires a
qualification (Q-21); the seed never sets it.

**catalogue_services** (= work type) — `specialisation_id` FK,
`w_id text NOT NULL UNIQUE CHECK (w_id ~ '^W[0-9]{3,}$')`,
`status` CHECK in (`draft`,`active`,`inactive`,`planned`,`hold`,`rejected`,`archived`),
`risk_level` CHECK in (`normal`,`high`), `qualification_required bool default false`, `restrictions text`, `review_note text` (admin-review hint, e.g.
possible duplicate; informational only),
`source_status text` (status as written in the KVC file, verbatim), `activated_by`, `activated_at`.
W-ID policy (Q-20), enforced in the DB:
- Trigger rejects any `UPDATE` of `w_id`; rows are never deleted, so a W-ID stays taken forever — also after
  reject/archive — and `UNIQUE (w_id)` makes reuse impossible.
- `CHECK ((source = 'kvc_v1') = (w_id ~ '^W0(0[1-9]|[1-6][0-9]|70)$'))` — W001–W070 only from the KVC import,
  and KVC rows only inside that range.
- Sequence `catalogue_w_id_seq` (created `START 71`): every admin-created service gets
  `'W' || lpad(nextval, 3, '0')` at insert (W1000+ keeps the `^W[0-9]{3,}$` format; the request body cannot set it).
  Only the `issuer` environment (production) issues W-IDs (R-CAT-16); the sequence is not used on staging.
  The seed inserts its fixed W071–W142 (`docs/CATALOGUE_SEED.md`) and then sets the sequence so the **next W-ID is
  W143**; it aborts if any of W071–W142 is used by a non-seed row. Every insert with explicit W-IDs (seed,
  environment import) ends with `setval(seq, greatest(last_value, max non-KVC number))` in the same transaction —
  the sequence never moves backwards, so W-IDs are never handed out twice.
`draft` = suggested entry awaiting admin review (Q-22); `hold` → `active` only via the explicit HOLD-activation
action (confirmation + reason, audited; R-CAT-04).

**qualifications** — `id`, `name`, `description`, `status` CHECK in (`draft`,`active`,`archived`); verification
rules: `requires_document bool`, `requires_document_number bool`, `requires_expiry_date bool`,
`max_validity_months int NULL`, `verifier_instructions text`; audit columns. Admin-defined; none seeded (Q-21).
Only `active` qualifications count as configured.

**service_qualifications** (primary) / **specialisation_qualifications** (whole-specialisation only) —
`(service_id | specialisation_id, qualification_id)` PK. Effective requirements of a service = its own ∪ its
specialisation's.

**Regulated-service gate:** a service with `qualification_required` (own or via its specialisation) cannot be set
`active`, and is never orderable, while its effective requirement set is empty or contains a non-`active`
qualification (409 `QUALIFICATION_NOT_CONFIGURED`).

**Orderability** (service layer `catalogue.availability`, step 4.5.1; no SQL view — owner decision 2026-11-02, so
the eligibility rule exists only once, in `services/eligibility.py`): service, specialisation and category all
`active` ∧ regulated-service gate passes ∧ ≥1 master passes the eligibility rule for the service (R-MST-11,
R-CAT-03). Computed from current rows on every read; nothing is stored.

*Implemented in migration `0002_catalogue`: all §3.2 tables above this line except the KVC staging tables below,
which are added with the KVC import (step 6).*

**catalogue_import_batches** (KVC, Q-20) — `id`, `file_name`, `file_sha256` unique, `uploaded_by`, `status` CHECK in
(`uploaded`,`mapping`,`applied`,`discarded`), `applied_by`, `applied_at`, `summary jsonb`.

**catalogue_import_rows** — `id`, `batch_id` FK, `row_no`, `w_id`, `raw jsonb` (all source columns verbatim),
`target_specialisation_id` FK NULL (admin-chosen mapping), `decision` CHECK in (`pending`,`create`,`skip`),
`conflict` (`w_id_exists`, `name_similar_to:<service id>`, `invalid_w_id`, …), `resulting_service_id` FK NULL,
`decided_by`, `decided_at`. Applying a batch only **inserts** new services for `create` rows; it never updates,
merges or overwrites existing services. Rows with an existing W-ID can only be `skip`.

**catalogue_sync_imports** (environment transfer into staging, R-CAT-15/16) — `id`, `package_id uuid`, `key_id`
(added by `0003_catalogue_signing`; partial unique on `package_id` where applied), `package_sha256` unique where
applied (same package can't be applied twice), `format_version`, `source_environment`, `exported_at`, `uploaded_by`, `status` CHECK in
(`previewed`,`applied`,`rejected`), `preview jsonb` (per entity: create / update / unchanged / conflict),
`applied_by`, `applied_at`.

### 3.3 Masters (R-MST)
**master_profiles** — `id`, `user_id` FK unique, `approval_status` CHECK in (`pending_approval`,`approved`,`rejected`),
`decided_by`, `decided_at`, `decision_reason`, `version` (migration `0006_master_profile_decisions` renamed
`approved_by`/`approved_at`/`rejection_reason` and added `version`; CHECK: `approved`/`rejected` ⇒ `decided_by` and
`decided_at` NOT NULL), `description`, `photo_attachment_id`,
`availability_mode` CHECK in (`available_now`,`available_for_reservations`,`unavailable`),
`is_busy bool` + `busy_since` (set by active work sheet), `mode_before_busy`,
`work_zone_type` CHECK in (`radius`) (**TD**, Q-03), `work_zone_center_lat/lon`, `work_zone_radius_km numeric(5,1)`,
`whatsapp_phone`, `call_phone`, `rating_avg numeric(3,2)`, `rating_count int`, `completed_jobs int`,
`commission_limit_eur numeric(12,2) NOT NULL` (initial from `commission_settings.default_limit`, 100.00).
Indexes: `(approval_status, availability_mode, is_busy)`.

All master capability tables (migration `0004_master_capabilities`, Phase 2 step 4) keep their history: rows are
never deleted (trigger, as for the catalogue), decisions are also written to `audit_log` and `domain_events`, and a
re-application after rejection/revocation/withdrawal updates the row back to `requested`/`declared` while the earlier
decision remains in the audit trail. `master_id` references `master_profiles.id`. Admin decisions (step 4.4,
`services/master_admin`) lock the master row (`SELECT … FOR UPDATE`, the same lock as the master's own writes),
require the `version` the admin saw (stale → 409) and move only along the approved transitions; `rejected` and
`revoked` are final for a row until the master re-applies (OPEN_QUESTIONS "Admin decisions on masters").

**master_specialisations** — `master_id` FK, `specialisation_id` FK, `status` CHECK in
(`requested`,`approved`,`rejected`,`revoked`,`withdrawn`), `requested_at`, `decided_by`, `decided_at`,
`decision_reason`, `version`, timestamps. PK `(master_id, specialisation_id)`. Index `(specialisation_id, status)`.
CHECK: `status IN ('approved','rejected','revoked') ⇒ decided_by IS NOT NULL AND decided_at IS NOT NULL`.

**master_competencies** — `master_id` FK, `service_id` FK, `status` CHECK in
(`declared`,`verified`,`rejected`,`revoked`,`withdrawn`), `declared_at`, `decided_by`, `decided_at`,
`decision_reason`, `version`, timestamps. PK `(master_id, service_id)`. Index `(service_id, status)`. Same decided-by
CHECK. Service rules: declare only for a service that is not `draft`/`rejected`/`archived` and whose specialisation
the master has `requested` or `approved`; `verified` only while the master profile and that specialisation are
`approved`, the service is not `draft`/`rejected`/`archived`, requirements are configured for a regulated service and
every effective qualification is satisfied (R-MST-11; owner decision 8, checked through `eligibility.explain`).
`declared` never counts for eligibility. Bulk verification: non-regulated services only, all or nothing.

**master_qualifications** — `id`, `master_id` FK, `qualification_id` FK, `status` CHECK in
(`submitted`,`verified`,`rejected`,`revoked`,`withdrawn`), `document_number` (never logged; audit keeps only the
last 4 characters), `valid_until date`, `submitted_at`, `decided_by`, `decided_at`, `decision_reason`, timestamps.
One row per submission (resubmission = new row, full history). Partial unique `(master_id, qualification_id) WHERE
status = 'submitted'` (migration `0005_qualification_renewal`; 0004 also covered `verified`). Renewal (owner,
2026-11-02): a new submission is allowed when the master has no verified submission for the type or every verified
one has expired (Riga calendar); a valid verified one or a pending one blocks it. The check runs under a lock on the
master row (`SELECT … FOR UPDATE`); expired verified rows stay unchanged. Evidence files: `attachments(entity_type='qualification', entity_id=id)`.
Expiry is evaluated at query time with the inclusive rule `valid_until IS NULL OR valid_until >=
(now() AT TIME ZONE 'Europe/Riga')::date`, no background job.

**attachments** (introduced here, reused by requests/work sheets later; always created together with their
owning record, never stand-alone) — `id`, `owner_user_id` FK, `entity_type`
CHECK in (`qualification`,`request`,`worksheet`,`profile`,`portfolio`), `entity_id`, `storage_key` unique (random,
no user data), `mime_type` (detected from content), `size_bytes` CHECK `> 0`, `sha256`, `uploaded_at`. No original
file name is stored. Index `(entity_type, entity_id)`. Never deleted outside the retention policy (Q-12/Q-27).
Views/downloads are logged in `audit_log` (`attachment.viewed`, actor, attachment ID; no content).

**Eligibility** (R-MST-11) is one SQL predicate in `services/eligibility.py`, used by the admin views, the catalogue
capacity count (R-CAT-03) and later by matching: `users.status='active'` ∧ `master_profiles.approval_status='approved'`
∧ `master_specialisations.status='approved'` (service's specialisation) ∧ `master_competencies.status='verified'` ∧
(service and specialisation not `qualification_required` ∨ ≥1 effective requirement) ∧ for each effective required
qualification (service ∪ specialisation requirements): `qualifications.status='active'`
∧ ∃ `master_qualifications` `verified` with `valid_until IS NULL OR valid_until >= business_today` (Europe/Riga,
inclusive). The catalogue's `eligible_masters` count is this predicate, nothing else.

**master_locations** — `master_id` PK/FK, `lat`, `lon`, `accuracy_m`, `updated_at`. One row per master; only the
latest location (no history — privacy, R-MST-07).

**master_portfolio_items** — `id`, `master_id`, `attachment_id`, `caption` (work examples, §4). *Step 4b.*

### 3.4 Requests, AI, matching (R-REQ, R-AI, R-MATCH, R-AIR)
**service_requests** — `id`, `client_id` FK users, `service_id` FK catalogue_services (nullable until classified
or for free-text requests), `catalogue_snapshot jsonb` (category/specialisation/service IDs, names, W-ID at the time
the service was set — historical integrity, R-CAT-09), `free_text_service text` (client's own task name, R-REQ-08),
`initial_description text NOT NULL`, `request_type` CHECK in (`immediate`,`reserved`), `preferred_time_from/to`,
address fields: `address_formatted`, `street`, `house_number`, `city`, `postal_code`, `building_block`,
`stairwell`, `flat`, `access_info`, `parking_info`, `place_provider_id`, `lat`, `lon` NOT NULL,
`status` CHECK in (`draft`,`clarifying`,`matching`,`proposed`,`confirmed`,`unserved`,`cancelled`),
`unserved_reason` (incl. `no_catalogue_service`, `rounds_exhausted`), `source` (`app`,`website_deeplink`; `src=web` →
`website_deeplink`), `deeplink_w_id`, `commercial_terms_id` (planned, C1/D1), `idempotency_key` unique per client,
`submitted_at`. Indexes: `(client_id, created_at desc)`, `(status, created_at)`.

**attachments** — see §3.3 (created in step 4; requests reuse it).

**ai_clarifications** — `id`, `request_id` FK unique, `was_needed bool`, `outcome` CHECK in
(`clear`,`unclear_manual_selection`,`error_fallback`), `resulting_service_id`, `confidence numeric(4,3)`,
`questions_asked smallint CHECK (questions_asked BETWEEN 0 AND 2)`, `model`, `started_at`, `ended_at`.

**ai_clarification_messages** — `id`, `clarification_id`, `seq`, `role` (`assistant`,`client`), `content`, `created_at`.

**matching_runs** — `id`, `request_id`, `run_no`, `service_id`, `request_type`, `eligible_count`,
`available_count`, `proposal_expires_at` (planned D2: client confirmation window 5 min / 30 min), `excluded_counts jsonb` (by reason: mode, zone, limit, busy, specialisation, unverified, qualification; planned D2: stale_location, declined_this_request, overlapping_offer), `params jsonb`,
`created_at`.

**matching_candidates** — `id`, `matching_run_id`, `master_id`, `rank`, `mode`, `distance_km numeric(6,2)`,
`eta_minutes int`, `eta_source` (`routing`,`fallback`), `rating_avg`, `shown_to_client bool`,
`role_in_result` (`proposal`,`alternative`,`not_shown`), `chosen_by_client bool`.
Index `(matching_run_id, rank)`.

### 3.5 Orders (R-ORD, R-WS)
**orders** — `id`, `request_id` FK, `client_id`, `master_id`, `order_type` (`immediate`,`reserved`),
`status` CHECK in (`offered`,`declined`,`accepted`,`scheduled`,`en_route`,`in_progress`,`completed`,`reviewed`,`cancelled`),
`scheduled_start/end`, `estimated_start/end` (planned D2: immediate-order interval for overlap checks, not billing),
`client_confirmed_at`, `offered_at`, `accepted_at`, `en_route_at` (departure), `arrived_at` (planned, owner
2026-11-04), `work_started_at`,
`completed_at`, `cancelled_at`, `cancel_reason`, `cancelled_by`, `commission_rate_snapshot numeric(5,4)`,
`version int` (optimistic lock). Indexes: `(client_id, created_at desc)`, `(master_id, status)`, `(status, updated_at)`.
Partial unique: `(request_id) WHERE status NOT IN ('declined','cancelled')` — one live order per request;
*Planned D2 (owner decision Q-FINAL-03; shape Q-TECH-01):* an order row is created only when the client confirms
(option A) and is the single assignment record: `offered` = active offer, accepted in place (no gap in the block).
`busy_range tstzrange NOT NULL` (forecast interval + buffer, set by the service) and
`EXCLUDE USING gist (master_id WITH =, busy_range WITH &&) WHERE (status IN ('offered','accepted','scheduled',
'en_route','in_progress'))` — requires the `btree_gist` extension; stale offers are expired under the master lock
before insert;
declined/expired offers keep their order row as history.

**order_offers** — `id`, `order_id`, `master_id`, `offered_at`, `expires_at`, `response` (`accepted`,`declined`,
`expired`), `responded_at` (keeps decline/timeout history for re-matching). *Planned (D2):* response value
`cancelled` for offers ended by a request/order cancellation, so no ended offer looks active; unique `(order_id)`
(one offer per order, so the order status and the offer can never diverge). `expires_at` = `offered_at` + master
response timeout (10 min immediate / 120 min reserved, Q-FINAL-02). Exclusion from later rounds only for
`response = 'declined'`.

**order_status_history** — `id`, `order_id`, `from_status`, `to_status`, `actor_type`, `actor_id`, `reason`,
`occurred_at`. Append-only. Index `(order_id, occurred_at)`.

**order_departures** (planned name; earlier `billable_starts` — renamed because, by the owner decision 2026-11-04,
the departure does not start billable time) — `order_id` PK/FK, `master_id`, `departed_at`, `status_history_id` FK
(D-Billable, §10: date, time, order ID, master, status change). Insert-once.

**worksheets** — `id`, `order_id`, `version int`, `is_current bool`, `state` (`active`,`finalised`), `work_start_at`,
`work_end_at`, `travel_start_at`, `travel_end_at`, `travel_minutes`, `billable_minutes`, `work_description`,
`limitations_explained` (incl. temporary repair flag `is_temporary_repair`), `internal_notes`,
`labour_amount_eur numeric(12,2)`, `materials_amount_eur numeric(12,2)`, `external_costs_eur numeric(12,2)`,
`calculation jsonb` (inputs per FIKSO calculation form — Q-01), `author_id`, `created_at`.
Time concepts (owner, 2026-11-04): departure (`travel_start_at` = `orders.en_route_at`), arrival (`travel_end_at` =
`orders.arrived_at`), work start/end (`work_start_at`, `work_end_at`), `travel_minutes` (stored, never billed
automatically), `billable_minutes` (actual work only; rounding/breaks/pauses — Q-01). `labour_amount_eur` is
calculated by the backend: `max(minimum, rate × billable_minutes / 60)` from the request's `commercial_terms`; the
master does not type it.
Unique `(order_id, version)`; partial unique `(order_id) WHERE is_current`. Old versions immutable (R-WS-03).

**worksheet_materials** — `id`, `worksheet_id`, `name`, `quantity numeric(10,3)`, `unit`, `amount_eur numeric(12,2)`.

**client_summaries** — `id`, `order_id`, `worksheet_id`, `content jsonb`, `sent_at`, `channel`.

### 3.6 Commission (R-COM)
**commission_settings** — single active row with history: `id`, `rate numeric(5,4) CHECK (rate >= 0 AND rate <= 1)`
default 0.2500, `default_limit_eur` default 100.00, `effective_from`, `changed_by`.

**commission_ledger** — `id`, `master_id`, `entry_type` CHECK in (`charge`,`payment`,`adjustment`), `order_id`
(charge only; unique where `entry_type='charge'`), `base_labour_eur numeric(12,2)`, `rate numeric(5,4)`,
`amount_eur numeric(12,2)` (charge > 0; payment < 0; adjustment ±), `payment_method` CHECK in (`cash`,`bank_transfer`)
for payments, `reference`, `reason`, `recorded_by`, `created_at`. Append-only.
*Planned addition (owner, 2026-11-04, migration with P2 in `docs/STAGE_C_BACKEND_PLAN.md`):* `paid_on date` — the date
the master paid (payments; `created_at` is the registration time); the admin comment is stored in `reason`
(required for adjustments). Accounting is a balance only: payments are not allocated to charges and there is no
per-order paid status.
Unpaid balance = `SUM(amount_eur)` per master (view `v_master_commission_balance`). Index `(master_id, created_at)`.

**commission_limit_changes** — `id`, `master_id`, `old_limit`, `new_limit`, `approved_by`, `reason`, `created_at`.

Eligibility: `balance < commission_limit_eur` (Q-11). Computed in the matching candidate query via the view.

### 3.7 Feedback, contacts, notifications
**reviews** — `id`, `order_id` unique, `client_id`, `master_id`, `rating smallint CHECK 1..5`, `comment`,
`is_hidden`, `hidden_by`, `created_at`. Master `rating_avg/count` updated in the same transaction.

**complaints** — `id`, `order_id`, `raised_by`, `raised_by_role`, `text`, `status` CHECK in
(`open`,`in_review`,`resolved`,`rejected`), `resolution_note`, `resolved_by`, `resolved_at`.
Index `(status, created_at)`.

**contact_click_events** (R-CT) — `id`, `occurred_at timestamptz NOT NULL`, `channel` CHECK in (`call`,`whatsapp`),
`master_id` FK NOT NULL, `request_id` FK nullable, `order_id` nullable, `clicked_by_user_id` nullable,
`source_screen`, `client_event_id` unique (dedupe retries). Append-only, never deleted.
Indexes `(master_id, occurred_at)`, `(request_id)`, `(occurred_at)`.

**notifications** — `id`, `user_id`, `type`, `payload jsonb`, `channel` (`in_app`,`sms`), `status`
(`pending`,`sent`,`failed`,`read`), `sent_at`, `read_at`. Index `(user_id, status, created_at)`.
*Planned D2 (background worker):* `attempts smallint`, `next_attempt_at`, `last_error` for retries of deferred
deliveries.

**job_runs** (planned D2, background worker monitoring) — `id`, `job_name`, `worker_id`, `started_at`,
`finished_at`, `status` (`running`,`succeeded`,`failed`), `items_processed`, `error`. Used to detect stuck or
failing jobs; no personal data.

### 3.8 AI-ready event log and settings
**domain_events** — `id`, `event_type` (e.g. `request.submitted`, `ai.clarification.completed`, `matching.completed`,
`order.status_changed`, `master.availability_changed`, `worksheet.finalised`, `commission.charged`,
`commission.payment_recorded`, `contact.clicked`), `aggregate_type`, `aggregate_id`, `actor_type`, `actor_id`,
`payload jsonb` (no raw PII), `occurred_at`, `schema_version smallint`. Append-only. Indexes
`(aggregate_type, aggregate_id, occurred_at)`, `(event_type, occurred_at)`. Partition by month when volume requires.

**system_settings** — `key` PK, `value jsonb`, `updated_by`, `updated_at` (matching thresholds, offer timeout,
location interval, photo limits; planned D2: client confirmation windows, immediate-order duration estimate and
buffer between orders).

## 4. Integrity rules enforced in the database
- Unique: email, phone, W-ID, source+source_ref per catalogue level, one live order per request, one review per order, one charge per order, one departure record
  per order, one current worksheet per order.
- CHECK: rating 1–5; amounts ≥ 0 where applicable; rate 0–1; HOLD ⇒ not orderable (status enum: orderable only when `active`); questions_asked ≤ 2.
- FK `ON DELETE RESTRICT` for business history; `CASCADE` only for pure child rows (messages, materials).
- Trigger: catalogue `id` and `catalogue_services.w_id` immutable; no `DELETE` on catalogue tables;
  W001–W070 reserved for `kvc_v1` (CHECK); forbid `UPDATE/DELETE` on append-only tables
  (`order_status_history`, `commission_ledger`, `contact_click_events`, `domain_events`, `audit_log`).

## 5. Financial precision
- Commission charge = `round_half_up(labour_amount_eur × rate, 2)`; computed in Python `Decimal` with
  `ROUND_HALF_UP`, stored with the base and rate used. Example: 80.00 × 0.2500 = 20.00.
- Materials and external costs are stored but never part of the base (F25.1).
- Balance and limit comparisons in SQL on `numeric`; no client-side money math.

## 6. Privacy and retention
- Only the latest master location stored. Matching candidates store distance/ETA, not master coordinates.
- Exact client address lives only on `service_requests`; AI read API and events use coarse location.
- Retention periods for personal data: Q-12 (default: keep while account active; anonymise on account deletion
  while preserving financial and order records required by law).

## 7. Migration strategy
- Alembic, one migration per logical change, reviewed; autogenerate then hand-edit.
- Baseline migrations in order: identity → catalogue → masters → requests/AI/matching → orders/worksheets →
  commission → feedback/contacts/notifications → events/settings → views/triggers.
- Seed migrations: roles/settings defaults (rate 0.25, limit 100.00). Catalogue data is **never** loaded by a
  migration. `seed-catalogue` (idempotent CLI, run once in production or an isolated local/test DB — never on
  staging, which receives it via export/import; R-CAT-16) inserts the CM 3 categories,
  24 specialisations and the 72 suggested services of `docs/CATALOGUE_SEED.md` (all `draft`, fixed W071–W142); it inserts missing rows
  only and never overwrites admin edits. The KVC import runs from the Admin Panel (staging tables above).
  Neither activates any service, HOLD or planned entry.
- Catalogue growth (new categories/specialisations/services/qualifications) is data, not schema: no migration.
- Expand/contract for zero-downtime and rollback compatibility; destructive steps only in a later release after
  approval. `downgrade()` implemented where data-safe.
- CI: `alembic upgrade head` on empty DB + `alembic downgrade -1` smoke test + model/migration drift check.
