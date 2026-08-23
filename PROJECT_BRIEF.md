# Ticket Booking System — Project Brief

## Objective (from assignment)
Build a ticket booking platform for movies/concerts where customers book seats
from a visual seat map, held seats auto-release on checkout abandonment,
sold-out events have a waitlist with automatic seat assignment on cancellation,
and every confirmed booking produces an email with a QR code ticket.

## Scope of Work
- **Admin** creates/manages venues with seat layout and seat categories (e.g. Premium, Standard)
- **Organiser** registers, logs in, creates movie/event listings with venue, date, time,
  per-category pricing
- **Customer** registers, logs in, browses/filters events, views a visual seat map with
  real-time seat status (available / held / booked)
- Customer selects seats → system places a hold with configurable TTL (default 10 min);
  held seats show as unavailable to others
- Checkout abandonment → held seats auto-release; seat map updates in real time
- Two customers must never hold/book the same seat (concurrency protection)
- Successful booking → email with QR code ticket; QR encodes booking reference
- Sold-out event → customer can join a waitlist for a specific seat category
- Booking cancelled → seat offered to next waitlisted customer for that category;
  they get an email with a time-limited link to complete booking
- If waitlisted customer doesn't complete booking in time → seat offered to next in line
- Customer can view booking history and cancel a booking
- Organiser can view booking summary and revenue per event

## Technical Expectations
- Backend API, Frontend, Database with role-based auth (customer / organiser / admin)
- Seat map stored per show with per-seat status; visual grid on frontend
- Seat hold TTL enforced via scheduler or DB-level expiry
- Concurrency protection: simultaneous attempts for the same seat must not both succeed
- Waitlist queue per seat category; auto-assignment + time-limited offer flow on cancellation
- QR code generation on booking; email delivery (any free-tier service)

## Deliverables
1. Zip file with complete source code
2. README: setup guide, `.env.example`, API docs, DB schema, hold/waitlist logic explanation
3. Hosted application URL (Vercel, Render, Railway, or similar)
4. System design write-up (800 words max) — seat hold/TTL, concurrency prevention,
   waitlist auto-assignment flow, time-limited offer handling
   → **already drafted, see `system_design_writeup.docx`, exactly 800 words**

## Evaluation Focus
- Seat hold TTL and auto-release mechanism
- Concurrency protection for simultaneous seat selection
- Waitlist auto-assignment and time-limited offer flow
- Seat map data model and real-time status updates
- QR code generation and email delivery
- API design, code structure, and documentation

## Submission Guidelines
- GitHub repo, branch `main`, public, fully downloadable — OR public Google Drive link (<1GB)
- Exclude: `node_modules`, `.env`, build artifacts (`dist/`, `.next/`, `out/`), editor folders
- No unnecessary packages; keep dependencies minimal
- App must run without errors; properly structured/named files; documented where needed

---

## Architecture Decisions Made
- **Backend:** Flask + SQLAlchemy, Flask-JWT-Extended (auth), APScheduler (TTL expiry),
  `qrcode` (QR generation), email via Brevo's HTTP API using plain `requests` — **changed
  from the original decision of smtplib** after deployment: Render blocks outbound SMTP
  traffic entirely (confirmed by testing — valid SMTP credentials authenticate
  successfully from an unrestricted network, then time out on every port when the exact
  same code runs on Render). An HTTP POST on port 443 is immune to that. Still "no extra
  email SDK" in spirit — bare `requests` against Brevo's REST endpoint, not a vendor SDK
  — but the payload shape is now Brevo-specific rather than protocol-agnostic like SMTP
  was. See `app/utils/email.py`'s docstring and the deployment log at the bottom of this
  file for the full story.
- **Database:** **PostgreSQL only** — no Redis. Seat holds and waitlist offers live as rows
  with `*_expires_at` timestamps; APScheduler sweeps every ~30s to expire them.
  Chosen for simpler hosting/single dependency over Redis-based TTL (which was considered
  and rejected for this project's scale).
- **Concurrency:** `SELECT ... FOR UPDATE` (row-level pessimistic lock) inside the hold and
  checkout transactions, backed by a DB unique constraint on `(event_id, seat_id)` in
  `seat_status`. First transaction to commit wins; loser gets 409. This is explicit FIFO
  ordering under contention.
- **Frontend:** **Plain HTML/CSS/JS** — no React/Vite. Chosen for simplicity; the seat map
  is a rendered grid with periodic polling of `/api` for live status, not a SPA framework.
- **Hosting:** Backend + Postgres on Render/Railway; frontend as static files (can be served
  from the same Flask app or a separate static host).
- **Migrations:** None — `db.create_all()` on startup. Simpler for a single deploy.
- **No microservices, no Kafka/RabbitMQ, no Elasticsearch, no CDN.** Those ideas from the
  two BookMyShow system-design references (Medium article by Prithwish Samanta, and the
  GeeksforGeeks "Design BookMyShow" article) were reviewed and deliberately NOT adopted —
  they're for distributed, high-scale systems; this is a single-instance gradeable app.
  The *concepts* (two-phase tentative→confirm booking, TTL-based seat blocking, FIFO
  ordering, lease-style waitlist offers) were kept; the infrastructure was dropped.
  This trade-off is explained in the "How This Scales" section of the design write-up.

## Data Model (implemented)
- `User` — id, name, email, password_hash, role (customer/organiser/admin)
- `Venue` — id, name, address, created_by (admin)
- `SeatCategory` — id, venue_id, name (Premium/Standard)
- `Seat` — id, venue_id, category_id, row_label, seat_number; unique per venue position
- `Event` — id, organiser_id, venue_id, title, event_type, description, starts_at
- `EventPricing` — id, event_id, category_id, price; unique per (event, category)
- `SeatStatus` — id, event_id, seat_id, status (available/held/booked), held_by, hold_key,
  hold_expires_at; unique (event_id, seat_id). **This is the concurrency core.**
- `Booking` — id, ref (12-char UUID-derived), event_id, customer_id, total, status
  (confirmed/cancelled), created_at, cancelled_at, hold_key (unique, added in step 4 —
  the consumed seat_status.hold_key, so `checkout()` can be idempotent on retry)
- `BookingSeat` — id, booking_id, seat_id, label (snapshot e.g. "A12")
- `Waitlist` — id, event_id, category_id, customer_id, status (waiting/offered/converted/
  expired/cancelled), created_at, offer_token, offer_seat_id, offer_expires_at

## What's Built So Far
- Project scaffold: `config.py`, `app/extensions.py`, `app/__init__.py` (app factory),
  `run.py`, `requirements.txt`, `.env.example`, `.gitignore`
- All models above, in `app/models/`, wired into `db.create_all()`. `Event` now also
  has a `seat_statuses` relationship with `cascade="all, delete-orphan"` (added while
  building step 3 — see note below).
- `app/routes/auth.py` — register (with role, blocks self-registered admin), login, `/me`
  — **tested and passing** (health check, register, duplicate email 409, admin-blocked 403,
  login, bad login 401, `/me` with/without token)
- `app/routes/venues.py` — **admin routes**, `role_required(ROLE_ADMIN)`, scoped to the
  creating admin (cross-admin access → 404): venue CRUD, seat category CRUD
  (create/rename/delete, 409 on dup name or delete-with-seats), bulk seat creation
  (generative `rows` + `seats_per_row` + `category_id`, or an explicit `seats` list;
  409 on any conflicting seat position). Bulk seat creation also backfills
  `SeatStatus` rows for any events already created against that venue.
  — **tested and passing**, 26/26 smoke-test checks.
- `app/routes/events.py` — **organiser routes** at `/api/organiser`, `role_required(ROLE_ORGANISER)`,
  scoped to the owning organiser (cross-organiser access → 404): read-only venue browsing
  (to pick a venue + see its categories), event CRUD (venue_id immutable after create),
  per-category pricing (inline on create, or upsert/delete via `PUT`/`DELETE .../pricing`),
  booking summary + revenue-per-event (`GET .../summary`), per-event booking list
  (`GET .../bookings`). Event creation seeds one `SeatStatus` row per venue seat
  (`available`) — this is what the seat map reads and what the hold/checkout
  transactions will `SELECT ... FOR UPDATE` against in step 4.
  — **tested and passing**, 36/36 smoke-test checks.
- `app/routes/browse.py` — **public customer browse + seat-map routes** at `/api/events`,
  no auth required: `GET /api/events` (filter by `event_type`, `venue_id`, `q` title search,
  `date` or `from`/`to`, defaults to upcoming-only, paginated, includes `price_from` per
  event), `GET /api/events/<id>` (detail + per-category availability counts + `sold_out`
  flag), `GET /api/events/<id>/seatmap` (seats grouped by row with live
  available/held/booked status, no PII). — **tested and passing**, 28/28 smoke-test checks.
- `app/utils/auth.py` — `role_required(*roles)` decorator, `current_user()` helper
- `app/utils/dates.py` — `parse_iso_datetime()` / `parse_date()`, shared by events.py and browse.py
- `app/utils/email.py` — email sender (HTML + attachments), fails soft. Originally an
  SMTP stub; rewritten post-deployment to use Brevo's HTTP API instead — see the
  "Architecture Decisions Made" section above and the deployment log at the bottom of
  this file.
- `app/scheduler.py` — APScheduler wired to call `release_expired_holds()` and
  `expire_stale_offers()` every `SCHEDULER_INTERVAL_SECONDS` (default 30s). These two
  functions **do not exist yet** — scheduler lazily imports them from
  `app/services/seat_service.py` and `app/services/waitlist_service.py` (not yet created),
  so the app runs fine without erroring in the meantime.

**Note on `SeatStatus` lifecycle:** rows are created (all `available`) when an event is
created, covering every seat the venue has at that moment, and backfilled if an admin
adds more seats to the venue afterward. `Event.seat_statuses` cascades on delete (they're
ephemeral live state); `Booking` has no such cascade, so an event with real bookings still
correctly blocks deletion with a 409 — only an event with zero bookings can be deleted,
even though it always owns `seat_status` rows from the moment it's created.

- `app/services/seat_service.py` — the concurrency core, per the architecture decisions
  above: every read-then-write of a `seat_status` row happens inside `SELECT ... FOR
  UPDATE` (via `_lock_for_update()`, which no-ops on SQLite — dev-sandbox only, since
  SQLite has no row locking — and applies the real lock on Postgres/MySQL in
  production), seat_ids sorted before locking to fix lock order and avoid deadlocks
  on multi-seat holds. Functions: `hold_seats()`, `release_hold()` (voluntary early
  release), `release_expired_holds()` (the scheduler target — `app/scheduler.py`'s
  lazy import now resolves), `checkout()` (consumes a hold_key into a confirmed
  `Booking`; idempotent — replaying the same hold_key returns the existing booking via
  the new `Booking.hold_key` column instead of erroring or double-booking), and
  `cancel_booking()` (frees seats back to available; lazily calls
  `waitlist_service.offer_next_in_line()` per freed category — that module landed in
  step 5, below, so this now actually fires instead of hitting the `ImportError` no-op).
  Refactored during step 5 to split out `checkout_uncommitted()` (validates + writes,
  no commit) from `checkout()` (adds the commit/rollback) — `waitlist_service.claim_offer()`
  needed to extend the same open transaction with its own Waitlist-row update so the
  two land atomically (see step 5's race notes below for why).
- `app/routes/bookings.py` — customer-facing routes (`role_required(ROLE_CUSTOMER)`) at
  `/api`: `POST /events/<id>/hold`, `DELETE /holds/<hold_key>`, `POST /checkout`.
  `cancel_booking()` has no route yet — that wiring, alongside booking history, is step 7
  per this plan; the service function itself is done now.
  — **tested and passing**, 39/39 smoke-test checks (hold contention, checkout,
  idempotent replay, wrong-owner 403s, TTL expiry via `release_expired_holds()`,
  expired-but-unswept 410, `cancel_booking()` freeing a seat for someone else to grab).
  Note: SQLite can't demonstrate the actual `FOR UPDATE` locking guarantee (no
  concurrent-request race was run) — only Postgres does, so that guarantee is
  unverified until this runs against real Postgres. The business-rule behavior
  (second party blocked while a hold is live, freed/expired seats become grabbable,
  idempotent checkout) is what's covered here.
- **Waitlist trigger scope, as built:** `cancel_booking()` is the only thing that
  offers freed seats to the waitlist, matching the brief's literal wording ("booking
  cancelled → seat offered to next waitlisted customer"). `release_expired_holds()`
  does **not** trigger waitlist offers — an expired hold returning to available is
  normal churn, not a sold-out category opening up. Worth flagging if that's not the
  intended interpretation.
- `app/services/waitlist_service.py` — FIFO queue per (event, category). An "offer"
  reuses the seat_status hold mechanism directly: the seat flips to `held` with the
  Waitlist entry's `offer_token` as its `hold_key`, so `hold_seats()`/`checkout()`
  already treat it as correctly unavailable to everyone else, and claiming an offer
  is literally `checkout_uncommitted()` with `offer_token` as the `hold_key`.
  `join_waitlist()` only allows joining when the category currently has zero
  available seats (else 409 — book directly instead). `offer_next_in_line()` loops
  while a waiting entry and an available seat both exist, so one cancellation that
  frees several seats in a category can produce several offers in one call.
  `expire_stale_offers()` is the scheduler target: frees a lapsed offer's seat, marks
  the entry `expired`, and cascades to the next waiting entry in the *same* sweep
  (not the next scheduler cycle). Every Waitlist row this module writes is locked
  (`SELECT ... FOR UPDATE`, same `lock_for_update()` helper as seat_service.py,
  factored out to `app/utils/locking.py` in this step) with a re-check-after-lock
  pattern, so a claim landing at the same instant as the expiry sweep can't leave an
  entry in the wrong terminal status. One accepted gap, documented in the module
  docstring: picking "the next waiting entry" isn't perfectly linearizable if two
  cancellations for the *same* category race at the exact same instant — can't cause
  a double-booked seat (seat_status locking still guarantees that), worst case is a
  seat sitting offered a beat longer than ideal before its own TTL sweep frees it.
  Consistent with the brief's other single-instance-scale trade-offs.
  `_send_offer_email()` sends the time-limited claim link now (via the existing
  `app/utils/email.py` stub — fails soft without SMTP configured) since it's core to
  the waitlist flow itself, not the booking-confirmation QR email that's step 6.
- `app/routes/waitlist.py` — customer-facing (`role_required(ROLE_CUSTOMER)`):
  `POST /events/<id>/waitlist` (join), `POST /waitlist/claim` (claim an offer by
  token). No "my waitlist entries" listing route yet — not asked for by this step;
  a natural future addition alongside step 7's booking history.
  — **tested and passing**, 52/52 smoke-test checks: join gated on sold-out (409
  while seats remain, 400/404 validation, 409 on duplicate join), FIFO offer
  ordering across two separate cancellations, claim success + idempotent replay +
  wrong-owner 403 + unknown-token 404, and the expire→cascade behavior verified
  end-to-end (an entry's offer is forced into the past, `expire_stale_offers()` is
  called directly, and the *next* waiting entry is confirmed offered the same freed
  seat within that one call).
  **A real bug surfaced and got fixed here**: `claim_offer()` originally rejected a
  replayed claim with 410 because it checked `entry.status == WL_OFFERED` *before*
  reaching the idempotent `checkout_uncommitted()` path — but a successful claim
  flips the entry to `converted`, so the replay never got there. Fixed by also
  accepting `WL_CONVERTED` at that gate (a replay looks exactly like that), letting
  `checkout_uncommitted()`'s existing-hold_key lookup do the idempotency. Caught by
  the smoke test's explicit replay case, not by inspection.
- `app/services/ticket_service.py` — `generate_qr_png(data)` (QR-encodes a string,
  e.g. `booking.ref`, to PNG bytes via `qrcode`) and `send_booking_confirmation_email(booking)`
  (builds the confirmation HTML — event/venue/when/seats/total/ref — and sends it via
  `app/utils/email.py`'s existing stub with the QR PNG as a file attachment named
  `ticket-<ref>.png`). QR encodes just the booking ref as plain text, per the brief's
  literal wording ("QR encodes booking reference"), not a verification URL.
  Best-effort/fails soft: any exception here is caught and logged, never propagated —
  a ticket/email bug must not fail the booking itself.
  Wired into both places a booking is actually created — `seat_service.checkout()`
  and `waitlist_service.claim_offer()` — each gated on `created=True` so an
  idempotent replay of either never sends a duplicate ticket email. This is a
  separate email from `waitlist_service._send_offer_email()` (the "a seat opened up,
  claim it" notification sent when an offer goes out, not when it's claimed) — both
  now coexist, verified distinct by content/attachment-presence in the smoke test.
  — **tested and passing**, 37/37 smoke-test checks, using a monkeypatched
  `send_email` to capture calls instead of actually sending (no SMTP server in this
  sandbox): exactly one confirmation email per fresh booking (direct checkout and
  waitlist claim both verified), none on replay of either, correct PNG magic bytes
  and filename on the attachment, and the fails-soft behavior (email raising an
  exception returns `False`, doesn't propagate). **Caveat**: the QR's actual decoded
  *content* wasn't verified end-to-end — that needs `pyzbar`, which needs the system
  `zbar` library, not present in this sandbox and not worth installing system
  packages just to strengthen one assertion. What's verified is that a well-formed
  PNG is produced and attached; correctness of `qrcode`'s encoding itself is trusted
  (it's a standard, widely-used library), not independently confirmed here.
- `app/routes/bookings.py` extended with the step-7 booking history + cancel routes
  (`role_required(ROLE_CUSTOMER)`, scoped to the owning customer — cross-customer
  access → 404, same pattern as everywhere else): `GET /bookings` (history, both
  confirmed and cancelled, newest first), `GET /bookings/<id>` (detail), `DELETE
  /bookings/<id>` (cancel — thin wrapper around the `cancel_booking()` service
  function already built in step 4; idempotent — cancelling an already-cancelled
  booking is a 200 no-op, not an error, since `cancel_booking()` was already built
  that way). No cancellation-deadline restriction (e.g. "can't cancel within N hours
  of the show") — not asked for by the brief, so not added.
  — **tested and passing**, 32/32 smoke-test checks: gating, ownership isolation on
  both list and detail, idempotent re-cancel, and — the one that actually mattered
  to verify here since the service logic was already covered in step 5 — that
  cancelling through this **HTTP route** (not a direct service call, unlike the step-5
  test) still correctly cascades a waitlist offer end-to-end.

All routes files were smoke-tested with Flask's test client against an in-memory
SQLite DB (with `PRAGMA foreign_keys=ON` to mirror Postgres's FK-restrict behavior) —
Postgres wasn't available in the dev sandbox. Production config/DB is untouched.
Running total: 250/250 backend smoke-test checks passing across all seven suites.

- **`frontend/`** — plain HTML/CSS/JS (no build step), per the architecture decision.
  Served directly by the Flask app itself: `app/__init__.py` now constructs `Flask(...,
  static_folder=FRONTEND_DIR, static_url_path="")` and adds `GET /` → `index.html`;
  every other page/asset (`/login.html`, `/css/style.css`, `/js/api.js`, ...) is
  auto-served by Flask's static handling since `static_url_path` is `""`. The
  `/api/*` blueprint routes still take precedence (Werkzeug routes by specificity,
  not registration order) — confirmed by the full backend regression suite passing
  unchanged after this change.
  - `frontend/js/api.js` — shared `fetch()` wrapper (`api()`, adds the JWT bearer
    header, throws with `.status`/`.data` on non-2xx), token/user storage
    (`localStorage`), `requireAuth(role)` gate, `showAlert()`/`clearAlert()`,
    `landingPageFor(role)` (shared by login/register so both send a freshly
    authenticated user to the right dashboard), date/money formatters. `API_BASE`
    is `''` (same-origin) by default — the one line to edit if the frontend is ever
    hosted separately from the API.
  - `frontend/js/nav.js` — renders the top nav from `localStorage` auth state on
    every page.
  - **Pages**: `index.html` (public browse/filter — type, title search, date,
    pagination, `price_from` per event), `login.html`/`register.html`, `event.html`
    (event detail + live seat map + hold/checkout flow), `bookings.html` (customer
    history + cancel), `claim-offer.html` (the waitlist offer link target —
    `?token=...` → claim), `organiser.html` (create event with per-category pricing,
    manage existing events: summary/revenue, pricing, bookings, delete), `admin.html`
    (venue CRUD, categories, bulk seat creation, read-only seat-map preview).
  - **`event.html`'s hold/checkout flow** (the most involved page): seat map polls
    `GET .../seatmap` every 5s; a click toggles local `selectedSeatIds` (no network
    call); "Hold Selected Seats" calls the hold endpoint and switches to
    `activeHold` state, which the renderer force-overrides to "selected" (blue)
    regardless of raw poll status — necessary because the seatmap API deliberately
    never reveals *who* holds a seat (no PII, see browse.py), so without this
    override a customer's own hold would repaint as generic "held by someone" on
    the very next poll tick. A `setInterval` countdown reads `hold_expires_at`
    client-side (no server round-trip needed for the ticking display) and turns red
    under 60s remaining; hitting 0 clears the hold state and refreshes. Checkout,
    release, and expiry all trigger a full `refreshSeatmap()` (not just a local
    re-render) so the Availability panel's counts stay server-truthful.
  - **`organiser.html`'s datetime-local → UTC conversion**: the browser's
    `datetime-local` input has no timezone info and is otherwise silently
    mis-stored as UTC; `new Date(value).toISOString()` converts it correctly before
    sending, matching how the rest of the frontend already displays stored
    timestamps back in the viewer's local time (`formatDateTime()` in `api.js`).

  **Verification**: no test-runner exists for a plain-JS frontend, so this was
  verified by actually running it — `python run.py` against a throwaway file-based
  SQLite DB (`DATABASE_URL=sqlite:////tmp/....db`, Postgres unavailable in this
  sandbox) with Flask serving the frontend itself, driven end-to-end by a
  Playwright script (headless Chromium, no `chromium-cli`/project run-skill
  available here, so this was a one-off driver rather than a reusable skill) through
  the full path: register organiser + customer → seed an admin row directly (no
  self-registration by design) → admin creates venue/category/bulk seats → organiser
  creates a priced event → event appears on the public browse page → customer
  selects a seat, holds it (countdown visible), checks out → booking confirmation
  shown → booking appears in history → cancel it. All steps passed, zero browser
  console errors, screenshots captured at each step.
  **Two real bugs found by this run and fixed** (not caught by inspection or by the
  backend's own test suite, since neither is backend behavior):
  1. `login.html` had no role-based redirect (only `next` or `/index.html`), unlike
     `register.html` (which sent organisers to their dashboard) — an inconsistency
     a real user would hit on every login. Fixed by factoring `landingPageFor(role)`
     into `api.js` and using it from both pages.
  2. `bookings.html`'s cancel flow called `showAlert('Booking cancelled...')` then
     `await loadBookings()` — but `loadBookings()` calls `clearAlert()` at its own
     start (needed for its role as the plain page-load path), which wiped the
     success message before it was ever visible. Fixed by reordering: reload first,
     show the success message after.
  A third issue was a gap rather than a bug: right after a successful hold,
  `event.html` only did a local re-render, so the Availability panel's counts
  (e.g. "10/10 available") stayed stale until the next 5s poll tick even though the
  seat was already held. Fixed by awaiting a full `refreshSeatmap()` on hold
  success, same as checkout/release already did.

## What's Next (in order)
1. ~~**Admin routes**~~ — done, see above
2. ~~**Organiser routes**~~ — done, see above
3. ~~**Customer browse/seat-map routes**~~ — done, see above
4. ~~**`app/services/seat_service.py`**~~ — done, see above
5. ~~**`app/services/waitlist_service.py`**~~ — done, see above
6. ~~**QR + email**~~ — done, see above
7. ~~**Customer booking history + cancel** endpoint~~ — done, see above
8. ~~**Frontend**~~ — done, see above
9. **README** — setup guide, `.env.example` (already exists), API docs, DB schema, hold/
   waitlist logic explanation
10. ~~**Deploy**~~ — done, see below

## Deployed (step 10)
- **Live URL**: https://ticket-booking-api-1sps.onrender.com — Render Blueprint deploy
  (`render.yaml` in repo root), web service (`gunicorn run:app --workers 1` — single
  worker deliberately, see the comment in `render.yaml`: avoids multiple independent
  APScheduler instances, one per gunicorn worker process, all sweeping the same rows)
  + a managed Postgres instance, wired together automatically by the Blueprint.
  Repo: https://github.com/balaji2005239/ticket-booking (public, `main`).
- **`.python-version` pinned to `3.12`** — `psycopg2-binary==2.9.9` only ships wheels
  through cp312; Render's default for new services is 3.14, which would hit the exact
  build failure this pin avoids (confirmed locally: no wheel, no local `pg_config` to
  build from source either).
- **Verified against the live deployment, not just locally**: `/api/health` (200),
  frontend root + static assets (200), `GET /api/events` and `POST /api/auth/register`
  (both exercise real Postgres reads/writes, not SQLite) — all passing.
- **The concurrency guarantee — flagged as unverified throughout steps 4-8 because every
  prior test ran against SQLite (no real row locking) — is now confirmed against real
  Postgres.** Seeded a throwaway admin/organiser/2 customers/venue/seat/event directly
  via the app's own models (admins can't self-register, so this needed direct DB access
  — external connection string, not exposed to the deployed app), then fired two
  genuinely simultaneous `POST /hold` requests (Python `threading.Barrier` releasing
  both at once, over real HTTPS to the live URL, not sequential and not a direct DB
  test) for the same seat from two different customers. Result: exactly one `201`, one
  `409`, and the seat_status row consistent with the winner — the `SELECT ... FOR
  UPDATE` locking correctly serializes concurrent access under real Postgres. All test
  data cleaned up afterward (verified via direct query: 0 rows in every table except
  the 1 pre-existing real user the operator had already created).
- **Known limits of the free tier** (not code issues — Render's terms): free Postgres
  expires 30 days after creation (14-day grace to upgrade before deletion); free web
  service sleeps after 15 min idle (~1 min cold start) and gets 750 instance-hours/month
  workspace-wide. Fine for a graded demo; would need a paid Postgres plan for anything
  longer-lived.
- **Real email delivery: got it working, but it took discovering a platform-level
  problem along the way.** Chronology, since it's a useful debugging trail:
  1. Set up a free Brevo account, verified a sender, generated an SMTP key, put
     `SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD` etc. in Render's dashboard (the
     `sync: false` fields in the SMTP-era `render.yaml`). Triggered a real booking on
     the live app — no email arrived. Render's logs: `Email send failed ...: timed out`.
  2. First hypothesis: wrong SMTP login (used the Brevo account email; Brevo's actual
     SMTP login is a generated `xxxxx@smtp-brevo.com` identifier, found under SMTP &
     API -> SMTP). Fixed it, redeployed, tested again — same timeout.
  3. Tested the corrected credentials directly from an unrestricted local machine (raw
     `smtplib`, ports 587/2525/465): **all three connected and authenticated
     successfully**, no timeout at all. That ruled out the credentials and pointed
     squarely at Render's network specifically being unable to reach
     `smtp-relay.brevo.com` — cloud/PaaS platforms blocking outbound SMTP to fight spam
     abuse is a common practice, and this behavior (TCP connection never completing,
     not an active rejection) is exactly its signature.
  4. **Fix: stopped using SMTP entirely.** Rewrote `app/utils/email.py` to call Brevo's
     HTTP REST API (`POST https://api.brevo.com/v3/smtp/email`, plain `requests`, port
     443) instead of `smtplib`. Verified directly with `curl` before touching
     Render — Brevo accepted the request (`201`, returned a `messageId`) and the test
     email actually arrived. Reworked config accordingly: `BREVO_API_KEY` (Brevo
     dashboard -> SMTP & API -> **API Keys** tab — a third, different credential from
     both the SMTP login and the SMTP key) replaces the old `SMTP_*` vars;
     `EMAIL_FROM_ADDRESS`/`EMAIL_FROM_NAME` replace `SMTP_FROM_EMAIL`/`SMTP_FROM_NAME`.
     `requests` added to `requirements.txt`. This is a real, deliberate reversal of the
     original "smtplib, no extra email SDK" architecture decision — recorded there too.
  5. Redeployed with the new code + `BREVO_API_KEY` on Render, triggered one more real
     booking (ref `340A0FF86B6B`) against the live app to confirm the deployed app
     itself — not just the `curl` test from step 4 — sends real mail post-redeploy.
  **Full regression (250/250) reran clean after the rewrite** — the smoke tests
  monkeypatch `send_email()` itself, so they're implementation-agnostic and didn't need
  changes. That "worth a quick manual check rather than taking this as fully closed"
  caveat turned out to matter — see the next entry, which picks up exactly there.

- **The step-5 caveat above was right to flag: the live-app-triggered emails were NOT
  actually arriving**, and it took three more rounds of debugging (spread across the
  waitlist-email and OTP-email work below) to find the real cause. Chronology:
  6. Testing the waitlist "seat available" offer email specifically (a different
     function, `_send_offer_email()`, from the booking-confirmation one, though both
     call the same `send_email()`): direct `curl` reproductions of the exact payload
     always succeeded and arrived; the same email triggered *through the app* never
     arrived, with no error visible anywhere. Two false leads chased first:
     - A stale deploy: Render had silently reverted to an older commit (predating a
       later push) — likely a build-ordering race from pushing several commits in
       quick succession. Fixed with a manual "Deploy latest commit" click, and from
       then on every deploy was verified via an observable behavior change (e.g.
       whether `register()` returned a token) rather than trusted blindly, since a
       plain health check can't distinguish which commit is actually live.
     - `app.logger` was silently dropping `.info()`-level logs: Flask's logger
       defaults to `WARNING` outside debug mode, so diagnostic logging added to
       `_send_offer_email()`/`_send_otp()` (see below) wasn't reaching Render's log
       stream at all — searching for it came back "no matching logs", which was
       itself the clue. Fixed with `app.logger.setLevel(logging.INFO)` in
       `create_app()` (`app/__init__.py`) — an app-wide fix, not just for these two
       call sites.
  7. Both `_send_offer_email()` and `_send_otp()` (`app/routes/auth.py`) were rewritten
     to match `ticket_service.send_booking_confirmation_email()`'s existing pattern —
     explicit logging on entry and on the `send_email()` result, wrapped in try/except.
     Neither had had this before, so a bug or failure in either was structurally
     invisible: no exception reached the caller (both callers have no try/except of
     their own either, so a real raise would have surfaced as a 500 on the triggering
     request — which never happened, meaning the code really was completing without
     error) and nothing was logged regardless of outcome.
  8. With logging actually visible, the real answer showed up immediately:
     `send_email()` was returning `True` (Brevo's API call itself succeeding, 2xx,
     real `messageId`) but the email still never arrived. Checking Brevo's own
     **Transactional -> Email Activity** logs (not visible from our side at all) gave
     the actual reason: *"Sending has been rejected because the sender you used
     noreply@yourticketapp.com is not valid. Validate your sender or authenticate your
     domain."* — `EMAIL_FROM_ADDRESS` on the live deploy was still the
     `.env.example`/`render.yaml` placeholder value, never the actual Brevo-verified
     sender (`ticketbooking565@gmail.com`). Every manual `curl` test throughout this
     whole investigation had used the correct verified sender explicitly (hardcoded in
     the test command); every email the *app itself* sent had been using the wrong
     one. This is why "does Brevo's API work" kept checking out while "does the app's
     email work" kept failing — different sender, same everything else.
  9. Fix: `EMAIL_FROM_ADDRESS` changed from a `value:` placeholder to `sync: false` in
     `render.yaml` (so a fresh deploy can't silently inherit an invalid sender — it now
     forces a conscious choice, same reasoning as `BREVO_API_KEY`), set to
     `ticketbooking565@gmail.com` in the dashboard, redeployed, retested live — OTP
     email confirmed reaching a real inbox this time.
  **Fully closed**: retested both the direct API call and the actual frontend UI flow
  (register/verify-email pages) against a real inbox (`balajidrivebackup@gmail.com`)
  — both confirmed working. Real email delivery, end to end, through the deployed app,
  is done.
  **Lesson for anyone deploying this fresh**: Brevo (and most transactional-email
  providers) silently reject sends from an unverified sender *after* accepting the API
  call — `send_email()` returning `True` does not mean the email arrived, only that
  Brevo's API accepted the request structurally. The provider's own delivery/activity
  logs are the only authoritative source for what happened next; this app has no way
  to detect or surface that failure itself (would need Brevo's async delivery-status
  API or webhooks, out of scope here).

## Post-deployment addition: email OTP verification (not in the original brief)
A feature request that came after the app was fully built, tested, and deployed —
not part of the original assignment scope above, added on top of it.

**Design decisions confirmed with the user before building**: (1) an account is fully
blocked — no token issued, login refused — until the OTP is verified, not a soft
background flag; (2) applies to both self-registered roles, customer and organiser.
Admins are exempt: they're seeded directly by a trusted operator, never through
`/register`, so they never go through this flow at all — a freshly-seeded admin has
`email_verified=False` by default and that's fine, because the login check itself
skips the verification requirement entirely for `role == admin`.

**Data model**: three new columns on `User` — `email_verified` (bool, default False),
`otp_code` (6-digit string), `otp_expires_at` (datetime). `otp_code`/`otp_expires_at`
follow the same pattern as `SeatStatus.hold_key`/`hold_expires_at`: populated only
while a verification is actually pending, cleared on success. `OTP_TTL_SECONDS` config
(default 600s, same as the other TTLs) — code via `app/utils/otp.py`
(`secrets.randbelow`, not `random` — this guards real account access).

**Routes** (`app/routes/auth.py`):
- `POST /register` — now creates an unverified user and sends the OTP; returns
  `{"message": ..., "email": ...}`, **no token**. Registering again for an email that
  exists but isn't verified yet updates the name/password/role and sends a fresh code
  instead of hard-blocking with 409 (safe — the code still only reaches whoever
  controls the inbox); registering an already-verified email still 409s as before.
- `POST /verify-email` — `{email, otp}` → `404` unknown email, `400` wrong code, `410`
  expired code (mirrors the `410` used elsewhere for expired holds/offers), `200` +
  token on success. Idempotent: replaying against an already-verified account just
  issues a fresh token rather than erroring — same pattern as `checkout()`'s replay
  handling.
- `POST /resend-otp` — `{email}` → `404` unknown, `409` already verified, else a fresh
  code is generated and sent. No rate limiting — consistent with this project's other
  "not over-engineered for scale/abuse" scope decisions.
- `POST /login` — unchanged for admins; for customer/organiser, checks
  `user.check_password()` first (401 on failure) *then* `email_verified` (403
  `email_not_verified` if not) — deliberately in that order, so an unverified-account
  probe can't be distinguished from a wrong-password one without knowing the password.

**Frontend**: `register.html` no longer auto-logs in — redirects to the new
`verify-email.html?email=...` page (OTP input + a resend button). `login.html`
special-cases the `email_not_verified` error with a link straight to the verify page,
pre-filled. Both `register.html` and `login.html` share a `landingPageFor(role)`
helper in `api.js` for where to send a freshly-authenticated user.

**Testing**: existing local test suites all register a user and immediately use the
returned token — that pattern broke across all 7 files (register no longer returns
one). Fixed by adding a `register_and_verify()` helper to each (register via the real
endpoint, read the OTP straight from the DB — no real email in tests — then call
`/verify-email` for the token), not a bypass. **New dedicated suite, 34/34**: no-token
registration, blocked pre-verification login, verify validation (400/404/410),
idempotent replay, resend (fresh code supersedes the stale one), expiry, re-registration
of an unverified account (fresh code, updated details, doesn't 409) vs. an already-
verified one (still 409s), the admin exemption specifically (freshly-seeded admin has
`email_verified=False` and can still log in), and organiser gated the same as customer
(not customer-only). **Full regression on the other 7 suites: 250/250, no
regressions** — confirms the `register_and_verify()` migration didn't change behavior
elsewhere, just how tests authenticate.

**Deployment consequence worth flagging explicitly**: this project's "no migrations,
`db.create_all()` only" decision (see Architecture Decisions above) means the three new
`User` columns do **not** get added to the live Postgres table automatically —
`create_all()` only creates tables that don't exist yet, it doesn't alter existing
ones. Shipping this required a manual one-time `ALTER TABLE users ADD COLUMN ...`
against the live DB, done directly (same DB access used throughout the deployment
verification work), **plus backfilling `email_verified = TRUE` for every already-
existing user** — otherwise every account that could log in before this shipped
(including the operator's own admin and customer accounts) would have been locked out
by the new check the moment it deployed. This is the first schema change made against
the live database since the initial deploy; the next one will need the same manual
step, or it's worth reconsidering the no-migrations decision at that point.

## Reference Material Used (concepts only, not architecture)
- Medium: "Online Movie Ticket Booking Platform - System Design (e.g. BookMyShow)" by
  Prithwish Samanta — tentative/confirm booking, Redis TTL blocking, microservices HLD
- GeeksforGeeks: "Design BookMyShow - A System Design Interview Question" — FIFO ticket
  serving, `BlockUserSelectedSeats`/`BookUserSelectedSeat` API naming, seat lock timeout flow

Both are large-scale distributed designs; this project intentionally uses a subset of their
concepts (two-phase booking, TTL locking, FIFO fairness) without the distributed
infrastructure (Kafka, Elasticsearch, Redis, microservices, CDN, Hadoop/BI).
