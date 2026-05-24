# SeatStalker Workflow

## Objective
Check a Delta Air Lines reservation to see if any targeted seats are currently available on a specific flight, then email the result to paul.bockewitz@gmail.com.

## Tool
`tools/check_seats.py`

Uses `delta-trip-pp-cli seatmap` to fetch the full seat map, compares available seats against the target list, and sends a Gmail alert when hits are found.

## Inputs

| Input | Flag | `.env` key | Format | Example |
|-------|------|------------|--------|---------|
| Confirmation number | `--confirmation` | `CONFIRMATION` | 6-char code | `ABC123` |
| First name | `--first-name` | `FIRST_NAME` | string | `John` |
| Last name | `--last-name` | `LAST_NAME` | string | `Smith` |
| Flight number or leg index | `--flight` | `FLIGHT` | `DLxxxx`, `xxxx`, or `1`/`2`/`3` | `DL5597` or `2` |
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

## Exit Codes (from delta-trip CLI)
| Code | Meaning |
|------|---------|
| `0` | Success |
| `3` | Confirmation or flight not found |
| `5` | API / scraping error |
| `7` | Rate limited — wait and retry |
| `10` | Config error |

## Notes
- The seat map check opens a visible Chrome window briefly (required — delta.com blocks headless browsers)
- Trip metadata is cached for 4 hours in SQLite; add `--no-cache` to the CLI args in `check_seats.py` to bypass
- `DELTA_TRIP_CLI` in `.env` sets the full path to the binary if it's not on your system PATH
- Email is only sent when target seats are found — no email on a miss, no inbox flooding during scheduled runs
