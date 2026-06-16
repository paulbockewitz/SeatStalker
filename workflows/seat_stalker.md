# SeatStalker Workflow

## Objective
Check an airline reservation to see if any targeted seats are currently available on a specific flight, then email the result when hits are found.

## Tool
`tools/check_seats.py`

Loads the airline adapter for the configured flight, fetches the seat map, compares available seats against the target list, and sends a Gmail alert when hits are found.

## Supported Airlines

| Airline | Code | Adapter | Data source |
|---------|------|---------|-------------|
| Delta Air Lines | `DL` | `tools/adapters/delta.py` | `delta-trip-pp-cli` |
| Iberia | `IB` | `tools/adapters/iberia.py` | `iberia-trips-pp-cli` + direct API |

Airline is auto-detected from the FLIGHT prefix (e.g. `DL5597` → Delta). Set `AIRLINE=XX` in `.env` to override.

## Inputs

| Input | Flag | `.env` key | Format | Example |
|-------|------|------------|--------|---------|
| Confirmation / locator | `--confirmation` | `CONFIRMATION` | 6-char code | `ABC123` |
| First name | `--first-name` | `FIRST_NAME` | string (*required for Delta; ignored by Iberia*) | `John` |
| Last name | `--last-name` | `LAST_NAME` | string | `Smith` |
| Airline | `--airline` | `AIRLINE` | 2-letter code | `DL` or `IB` |
| Flight number or leg index | `--flight` | `FLIGHT` | `DLxxxx`, `IBxxxx`, or `1`/`2`/`3` | `DL5597` or `2` |
| Target seats | `--target-seats` | `TARGET_SEATS` | comma list or row range | `12A,14C` or `12-15` |

All inputs can be stored in `.env` so the tool runs with no arguments:

```powershell
python tools\check_seats.py
```

Or override individual values at the command line:

```powershell
python tools\check_seats.py --confirmation ABC123 --first-name John --last-name Smith --flight DL5597 --target-seats "12A,14C"
```

### Target seat formats
- **Specific seats**: `12A,14C,15A` — exact seat numbers
- **Row range**: `12-15` — any seat in rows 12 through 15
- **Mixed**: `12A,14-15` — specific seats and row ranges can be combined

### Flight input
`--flight` accepts:
- A full Delta flight number: `DL5597` or just `5597`
- A 1-based leg index: `1` (first flight), `2` (second flight), etc.

For multi-segment trips, the tool resolves the flight number to the correct leg automatically.

## Email Output

**Seats found** (email sent):
- Subject: `SeatStalker: Target seat(s) available - ABC123`
- Body: HTML email with a color-coded seat map showing the target rows, plus a header table with confirmation, flight, aircraft, and current seat assignments. Plain-text fallback included.

**No seats found** (email skipped):
- No email sent; run is logged to `.tmp/seatstalker.log`

### Seat map color key
| Color | Meaning |
|-------|---------|
| Green | Available target seat |
| Blue | Your current seat |
| White | Available (non-target) |
| Dark gray | Occupied |
| Light gray | Blocked |

## Gmail Setup (App Password)

1. Go to your Google Account -> Security -> 2-Step Verification -> App Passwords
2. Create a new app password (name it "SeatStalker" or similar)
3. Copy the 16-character password into `.env`:

```
GMAIL_SENDER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

No OAuth, no browser consent, no `credentials.json` needed. SMTP with app password is all that's required.

## Scheduling (Windows Task Scheduler)

Since all inputs are in `.env`, the scheduled command is just `python tools\check_seats.py`.

1. Open Task Scheduler -> Create Basic Task
2. **Trigger**: Daily, then check "Repeat task every: 30 minutes" for a duration of "Indefinitely"
3. **Action**: Start a program
   - Program: `python`
   - Arguments: `tools\check_seats.py`
   - Start in: `C:\Users\paulb\Documents\Agentic Workflows\SeatStalker`
4. Under Properties -> Settings: check "Run task as soon as possible after a scheduled start is missed"

## Log File

Every run appends to `.tmp/seatstalker.log`:
- Confirmation, flight, aircraft, current seats, target list, open seat count, timestamp
- "No target seats available - email skipped." or "Email sent."
- `----` separator between runs

## Exit Codes (from CLI adapters)
| Code | Meaning |
|------|---------|
| `0` | Success |
| `3` | Confirmation or flight not found |
| `5` | API / scraping error |
| `7` | Rate limited — wait and retry |
| `10` | Config error (unknown airline code, missing CLI) |

## Notes
- The seat map check runs silently using headless Chrome — no visible window. Set `HEADED=true` in `.env` to fall back to a visible window if Delta's bot detection blocks headless mode.
- Delta trip metadata is cached for 4 hours in SQLite; add `--no-cache` to the CLI args in `adapters/delta.py` to bypass.
- `DELTA_TRIP_CLI` / `IBERIA_TRIP_CLI` in `.env` set the full path to the CLI binaries if they're not on your system PATH.
- Email is only sent when target seats are found — no email on a miss, no inbox flooding during scheduled runs.
- To add a new airline: create `tools/adapters/<code>.py` implementing `get_trip` and `get_seat_map`, then register the 2-letter code in `AIRLINE_MAP` in `check_seats.py`.
