# SeatStalker

Monitor airline reservations for seat availability and get an email alert the moment your target seats open up.

For example, you and your travel partner book late and aren't sitting next to each other. The moment that sweet pair of seats opens up, SeatStalker will notify you and you can scoop them up.

When target seats become available, SeatStalker sends an HTML email with a color-coded seat map showing the target rows so you can confirm the positions at a glance. When nothing is available, it logs the check and skips the email — no inbox flooding during scheduled runs.

**Supported airlines:** Delta, Iberia _(more to come — each airline is a self-contained adapter)_

---

## Prerequisites

**1. Python 3.9+**

**2. Airline CLI(s)**

SeatStalker uses airline-specific CLIs (from the Printing Press CLI Library) to fetch live seat map data. Install the ones you need:

**Delta:**
```
npx -y @mvanhorn/printing-press-library install delta-trip --cli-only
```
Verify: `delta-trip-pp-cli --version`

**Iberia:**
```
npx -y @mvanhorn/printing-press-library install iberia-trips --cli-only
```
Verify: `iberia-trips-pp-cli --version`

> Runs silently using headless Chrome — no visible window during checks. If Delta's bot detection ever blocks headless mode, add `HEADED=true` to your `.env` to fall back to a visible window.

**3. Gmail App Password**

SeatStalker sends email via Gmail SMTP. You'll need an App Password:

1. Go to your Google Account → Security → 2-Step Verification → App Passwords
2. Create a new app password (name it "SeatStalker" or similar)
3. Copy the 16-character password — you'll add it to `.env` in Setup

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/yourusername/SeatStalker.git
cd SeatStalker

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env with your trip details, Gmail credentials, and target seats

# 4. Run
python tools/check_seats.py
```

---

## Configuration (`.env`)

| Key | Required | Description | Example |
|-----|----------|-------------|---------|
| `DELTA_TRIP_CLI` | No | Full path to Delta CLI binary if not on PATH | `C:\path\to\delta-trip-pp-cli.exe` |
| `IBERIA_TRIP_CLI` | No | Full path to Iberia CLI binary if not on PATH | `C:\path\to\iberia-trips-pp-cli.exe` |
| `AIRLINE` | No | Two-letter airline code (auto-detected from flight number) | `DL` or `IB` |
| `GMAIL_SENDER` | Yes | Gmail address used to send alerts | `you@gmail.com` |
| `GMAIL_RECIPIENT` | No | Address to receive alerts (defaults to `GMAIL_SENDER`) | `you@gmail.com` |
| `GMAIL_APP_PASSWORD` | Yes | Gmail App Password (16 chars, spaces ok) | `xxxx xxxx xxxx xxxx` |
| `CONFIRMATION` | Yes | Booking confirmation / locator | `ABC123` |
| `FIRST_NAME` | Yes* | Passenger first name (*required for Delta; ignored by Iberia) | `Jane` |
| `LAST_NAME` | Yes | Passenger last name / surname | `Smith` |
| `FLIGHT` | Yes | Flight number or leg index | `DL5597`, `IB1234`, or `2` |
| `TARGET_SEATS` | Yes | Seats to watch | `20A,20B` or `20-23` |

All inputs can also be passed as flags — run `python tools/check_seats.py --help` for details.

### Airline auto-detection

The airline is auto-detected from the flight number prefix: `DL` → Delta, `IB` → Iberia. Set `AIRLINE` explicitly if your flight number doesn't start with the carrier code.

### Target seat formats

| Format | Example | What it matches |
|--------|---------|-----------------|
| Specific seats | `20A,20B,20H` | Exact seat numbers |
| Row range | `20-23` | All seats in rows 20–23 |
| Mixed | `20A,21-22` | Specific seats plus full rows |

### Flight input

`FLIGHT` accepts a full flight number (`DL5597`, `IB1234`) or a 1-based leg index (`1`, `2`, `3`). For multi-segment trips, SeatStalker resolves the flight number to the correct leg automatically.

---

## Running

```bash
# Zero-argument run (reads everything from .env)
python tools/check_seats.py

# Override specific values
python tools/check_seats.py --confirmation ABC123 --target-seats "20A,20B"
```

---

## Scheduling (Windows Task Scheduler)

To check automatically every 30 minutes:

1. Open **Task Scheduler** → **Create Basic Task**
2. **Trigger**: Daily, then set "Repeat task every: 30 minutes" for "Indefinitely"
3. **Action**: Start a program
   - Program: `python`
   - Arguments: `tools\check_seats.py`
   - Start in: `C:\path\to\SeatStalker`
4. Under **Properties → Settings**: check "Run task as soon as possible after a scheduled start is missed"

---

## Email

**On a hit** — an HTML email is sent with:
- Header table: confirmation, flight, aircraft, current seat assignments
- Color-coded seat map for the target rows
- Plain-text fallback for email clients that don't render HTML

**On a miss** — no email. The check is logged to `.tmp/seatstalker.log`.

### Seat map colors

| Color | Meaning |
|-------|---------|
| 🟢 Green | Available target seat |
| 🔵 Blue | Your current seat |
| White | Available (non-target) |
| Gray | Occupied or blocked |

---

## Log file

Every run appends to `.tmp/seatstalker.log`:

```
SeatStalker checked your reservation - none of your target seats are currently available.

  Confirmation  : ABC123
  Flight        : DL5597  BOS -> AMS
  Aircraft      : Airbus A330-900neo
  Current seats : Jane Smith - 23J
  Target seats  : 20A,20B,20H,20J
  Open seats    : 9 available on this flight

Checked at: 2026-05-23 03:46 PM
No target seats available - email skipped.
------------------------------------------------------------
```

---

## Preview the email without a real hit

```bash
python scripts/gen_preview.py
```

Generates `.tmp/email_preview.html` using your `.env` config and simulates the first two target seats as available. Open the file in a browser to verify the layout before you schedule.

---

## Adding a new airline

Each airline is a self-contained adapter in `tools/adapters/`. To add support for a new airline:

1. Create `tools/adapters/<code>.py` extending `AirlineAdapter` (see `tools/adapters/base.py`)
2. Implement `get_trip()` and `get_seat_map()` — both must return normalized SeatStalker schema
3. Add the two-letter IATA code to `AIRLINE_MAP` in `tools/check_seats.py`

See `tools/adapters/delta.py` (CLI wrapper) and `tools/adapters/iberia.py` (CLI + direct API) for examples.

---

## How it works

SeatStalker follows the [WAT framework](CLAUDE.md) — Workflows, Agents, Tools:

- **Workflow** (`workflows/seat_stalker.md`) — the SOP defining inputs, outputs, and edge cases
- **Adapters** (`tools/adapters/`) — one per airline; each fetches and normalizes trip and seat map data
- **Tool** (`tools/check_seats.py`) — airline-agnostic: loads the right adapter, compares seats, sends email
- **Agent** — Claude, when used to orchestrate or modify the workflow

No airline credentials required — booking reference + passenger name only.
