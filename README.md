# SeatStalker

Monitor an airline reservation (Just Delta for now) for seat availability and get an email alert the moment your target seats open up.

For example, you and your travel partner book late and aren't sitting by each other.  The moment that sweet section of 2 seats opens up, SeatStalker will notify you and you can scoop them up.

When target seats become available, SeatStalker sends an HTML email with a color-coded seat map showing the target rows so you can confirm the positions at a glance. When nothing is available, it logs the check and skips the email — no inbox flooding during scheduled runs.

---

## Prerequisites

**1. Python 3.9+**

**2. delta-trip-pp-cli** (this is in the Printing Press CLI Library)

SeatStalker uses the [delta-trip Printing Press CLI](https://github.com/mvanhorn/printing-press) to fetch live seat map data from Delta. Install it with:

```
npx -y @mvanhorn/printing-press-library install delta-trip --cli-only
```

Verify: `delta-trip-pp-cli --version`

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
| `DELTA_TRIP_CLI` | No | Full path to the CLI binary if not on PATH | `C:\path\to\delta-trip-pp-cli.exe` |
| `GMAIL_SENDER` | Yes | Gmail address used to send alerts | `you@gmail.com` |
| `GMAIL_RECIPIENT` | No | Address to receive alerts (defaults to `GMAIL_SENDER`) | `you@gmail.com` |
| `GMAIL_APP_PASSWORD` | Yes | Gmail App Password (16 chars, spaces ok) | `xxxx xxxx xxxx xxxx` |
| `CONFIRMATION` | Yes | Delta confirmation number | `ABC123` |
| `FIRST_NAME` | Yes | Passenger first name | `Jane` |
| `LAST_NAME` | Yes | Passenger last name | `Smith` |
| `FLIGHT` | Yes | Flight number or leg index | `DL5597` or `2` |
| `TARGET_SEATS` | Yes | Seats to watch | `20A,20B` or `20-23` |

All inputs can also be passed as flags — run `python tools/check_seats.py --help` for details.

### Target seat formats

| Format | Example | What it matches |
|--------|---------|-----------------|
| Specific seats | `20A,20B,20H` | Exact seat numbers |
| Row range | `20-23` | All seats in rows 20–23 |
| Mixed | `20A,21-22` | Specific seats plus full rows |

### Flight input

`FLIGHT` accepts a full Delta flight number (`DL5597` or `5597`) or a 1-based leg index (`1`, `2`, `3`). For multi-segment trips, SeatStalker resolves the flight number to the correct leg automatically.

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

## How it works

SeatStalker follows the [WAT framework](CLAUDE.md) — Workflows, Agents, Tools:

- **Workflow** (`workflows/seat_stalker.md`) — the SOP defining inputs, outputs, and edge cases
- **Tool** (`tools/check_seats.py`) — deterministic Python that calls the CLI, compares seats, and sends email
- **Agent** — Claude, when used to orchestrate or modify the workflow

The seat map data comes entirely from `delta-trip-pp-cli` — no Delta credentials, no web scraping in Python. The CLI handles the browser session; SeatStalker just processes the JSON output.
