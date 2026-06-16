"""
SeatStalker: Check airline flight seat availability against target seats and send email alert.

Usage:
    python tools/check_seats.py --confirmation ABC123 --first-name John --last-name Smith \
        --flight DL5597 --target-seats "12A,14C"

    --flight accepts a flight number (DL5597 or 5597) or a leg index (1, 2, 3).
    --target-seats accepts specific seats (12A,14C) or a row range (12-15).

    Airline is auto-detected from the flight number prefix (DL=Delta, IB=Iberia).
    Override with --airline or the AIRLINE env var.
"""

import argparse
import importlib
import json
import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
GMAIL_RECIPIENT = os.getenv("GMAIL_RECIPIENT", GMAIL_SENDER)
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
LOG_FILE = Path(".tmp") / "seatstalker.log"

# Map IATA carrier prefix -> adapter module name in tools/adapters/
AIRLINE_MAP = {
    "DL": "delta",
    "IB": "iberia",
}


def load_adapter(airline_code):
    """Return an instantiated AirlineAdapter for the given two-letter code."""
    name = AIRLINE_MAP.get(airline_code.upper())
    if not name:
        supported = ", ".join(AIRLINE_MAP.keys())
        print(f"ERROR: Unknown airline code '{airline_code}'. Supported: {supported}", file=sys.stderr)
        sys.exit(10)
    # tools/ is on sys.path (added below main) so adapters is importable directly
    mod = importlib.import_module(f"adapters.{name}")
    cls_name = name.capitalize() + "Adapter"
    return getattr(mod, cls_name)()


def detect_airline(flight_str):
    """Detect the two-letter airline code from a flight string like 'DL5597' or 'IB1234'."""
    m = re.match(r"^([A-Z]{2})", flight_str.strip().upper())
    if m:
        return m.group(1)
    return None


def log(message):
    """Print to console and append to log file."""
    print(message)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def parse_target_seats(target_str):
    """
    Parse target seat input into a set of identifiers.
    Supports specific seats ("12A,14C") and row ranges ("12-15").
    Row ranges are stored as "ROW12", "ROW13", etc. for matching.
    """
    targets = set()
    for part in target_str.split(","):
        part = part.strip().upper()
        range_match = re.match(r"^(\d+)-(\d+)$", part)
        if range_match:
            start_row = int(range_match.group(1))
            end_row = int(range_match.group(2))
            for row in range(start_row, end_row + 1):
                targets.add(f"ROW{row}")
        else:
            targets.add(part)
    return targets


def seat_matches_targets(seat_number, targets):
    """Return True if a seat number matches any entry in targets (including row ranges)."""
    seat_number = seat_number.upper()
    if seat_number in targets:
        return True
    row_match = re.match(r"^(\d+)[A-Z]$", seat_number)
    if row_match:
        row_num = int(row_match.group(1))
        if f"ROW{row_num}" in targets:
            return True
    return False


def resolve_flight_index(flights, flight_input):
    """
    Resolve flight input to a 1-based leg index given the flights list.
    Accepts a flight number (DL5597 / 5597 / IB1234) or a leg index (1, 2, 3).
    Returns (index, flight_dict).
    """
    flight_str = str(flight_input).strip().upper()
    # Strip any two-letter carrier prefix for numeric matching
    numeric = re.sub(r"^[A-Z]{2}", "", flight_str)

    if re.match(r"^\d{1,2}$", numeric) and not re.match(r"^[A-Z]{2}\d{1,2}$", flight_str):
        # Pure index like "1" or "2"
        idx = int(flight_str)
        match = next((f for f in flights if f.get("flightIndex", "").startswith(str(idx))), None)
        return idx, match

    for flight in flights:
        fn = re.sub(r"^[A-Z]{2}", "", flight.get("flightNumber", "").upper())
        if fn == numeric:
            idx_str = flight.get("flightIndex", "1")  # "2 of 3"
            return int(idx_str.split()[0]), flight

    print(f"Flight '{flight_input}' not found. Available legs:", file=sys.stderr)
    for f in flights:
        print(f"  {f.get('flightNumber')} ({f.get('flightIndex')})", file=sys.stderr)
    sys.exit(3)


def find_available_targets(seat_map, targets):
    """Return list of dicts for target seats that have status 'available'."""
    hits = []
    for cabin in seat_map.get("cabins", []):
        for row in cabin.get("rows", []):
            for seat in row.get("seats", []):
                if seat.get("status") == "available" and seat_matches_targets(seat["number"], targets):
                    hits.append({
                        "seat": seat["number"],
                        "cabin": cabin["name"],
                        "type": seat.get("type", ""),
                        "exitRow": seat.get("exitRow", False),
                    })
    return hits


def build_seat_map_html(seat_map, targets):
    """
    Build an HTML table of the seat map, showing only rows that contain target seats.
    Color coding:
      green  = available target seat
      blue   = your current seat
      white  = available (non-target)
      dark gray = occupied
      light gray = blocked
    """
    target_rows = set()
    for t in targets:
        if t.startswith("ROW"):
            target_rows.add(int(t[3:]))
        else:
            m = re.match(r"^(\d+)[A-Z]$", t)
            if m:
                target_rows.add(int(m.group(1)))

    COLORS = {
        "available-target": ("#22c55e", "white"),
        "your-seat":        ("#3b82f6", "white"),
        "available":        ("#f9fafb", "#374151"),
        "occupied":         ("#6b7280", "white"),
        "blocked":          ("#e5e7eb", "#9ca3af"),
    }

    sections = []
    for cabin in seat_map.get("cabins", []):
        relevant_rows = [
            row for row in cabin.get("rows", [])
            if any(seat_matches_targets(s["number"], targets) for s in row.get("seats", []))
            or row.get("row", 0) in target_rows
        ]
        if not relevant_rows:
            continue

        all_letters = sorted({s["number"][-1] for row in relevant_rows for s in row.get("seats", [])})

        header_cells = ['<td style="padding:4px 6px;font-weight:bold;color:#6b7280;"></td>']
        for letter in all_letters:
            header_cells.append(
                f'<td style="width:38px;text-align:center;font-weight:bold;'
                f'color:#6b7280;font-size:12px;padding:2px 4px;">{letter}</td>'
            )

        seat_rows = [f'<tr>{"".join(header_cells)}</tr>']

        for row in relevant_rows:
            seats_by_letter = {s["number"][-1]: s for s in row.get("seats", [])}
            row_num = row.get("row", "")
            is_exit = row.get("exitRow", False)
            exit_border = "border-left:3px solid #f59e0b;" if is_exit else ""

            cells = [
                f'<td style="padding:4px 6px;font-weight:bold;color:#6b7280;'
                f'font-size:12px;text-align:right;">{row_num}</td>'
            ]
            for letter in all_letters:
                seat = seats_by_letter.get(letter)
                if not seat:
                    cells.append('<td style="width:38px;"></td>')
                    continue
                status = seat.get("status", "occupied")
                seat_num = seat["number"]
                is_target = seat_matches_targets(seat_num, targets)
                color_key = (
                    "available-target" if status == "available" and is_target
                    else status if status in COLORS
                    else "occupied"
                )
                bg, fg = COLORS[color_key]
                label = seat_num if status in ("available", "your-seat") else ("X" if status == "occupied" else "-")
                cells.append(
                    f'<td style="padding:3px;">'
                    f'<div style="width:38px;height:36px;line-height:36px;text-align:center;'
                    f'background:{bg};color:{fg};border-radius:5px;'
                    f'border:1px solid #d1d5db;{exit_border}'
                    f'font-size:11px;font-weight:bold;">{label}</div></td>'
                )
            seat_rows.append(f'<tr>{"".join(cells)}</tr>')

        exit_note = ' <span style="color:#f59e0b;font-size:11px;">(gold border = exit row)</span>' if any(
            r.get("exitRow") for r in relevant_rows) else ""
        sections.append(
            f'<p style="margin:16px 0 6px;font-weight:bold;color:#111;">{cabin["name"]}</p>'
            f'<table style="border-collapse:collapse;font-family:Arial,sans-serif;">{"".join(seat_rows)}</table>'
            f'{exit_note}'
        )

    legend = """
    <p style="margin-top:14px;font-size:11px;color:#6b7280;">
      <span style="background:#22c55e;color:white;padding:2px 8px;border-radius:3px;">Available target</span>&nbsp;
      <span style="background:#3b82f6;color:white;padding:2px 8px;border-radius:3px;">Your seat</span>&nbsp;
      <span style="background:#f9fafb;color:#374151;padding:2px 8px;border-radius:3px;border:1px solid #d1d5db;">Available</span>&nbsp;
      <span style="background:#6b7280;color:white;padding:2px 8px;border-radius:3px;">Occupied</span>
    </p>"""

    return "\n".join(sections) + legend


def build_html_body(text_body, seat_map_html, header_fields):
    """Wrap the plain-text summary and seat map HTML into a full HTML email."""
    header_rows = "".join(
        f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280;white-space:nowrap;">{k}</td>'
        f'<td style="padding:2px 0;color:#111;">{v}</td></tr>'
        for k, v in header_fields
    )
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#111;max-width:640px;margin:0 auto;padding:16px;">
  <h2 style="color:#22c55e;margin-bottom:4px;">SeatStalker: Target Seat(s) Available</h2>
  <table style="margin-bottom:16px;">{header_rows}</table>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:12px 0;">
  <p style="font-weight:bold;margin-bottom:8px;">Seat Map (target rows)</p>
  {seat_map_html}
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;">
  <pre style="font-size:12px;color:#6b7280;white-space:pre-wrap;">{text_body}</pre>
</body></html>"""


def send_email(subject, text_body, html_body=None):
    if not GMAIL_APP_PASSWORD:
        print("ERROR: GMAIL_APP_PASSWORD not set in .env - skipping email", file=sys.stderr)
        return
    if html_body:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(text_body, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        message = MIMEText(text_body, "plain", "utf-8")
    message["to"] = GMAIL_RECIPIENT
    message["from"] = GMAIL_SENDER
    message["subject"] = subject
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.send_message(message)
    print(f"Email sent to {GMAIL_RECIPIENT}: {subject}")


def build_email(seat_map, hits, flight_info, targets, args, checked_at):
    confirmation = args.confirmation.upper()
    flight_num = flight_info.get("flightNumber", "") if flight_info else ""
    dep = (flight_info or {}).get("departure", {})
    arr = (flight_info or {}).get("arrival", {})
    route = f"{dep.get('airport','')} -> {arr.get('airport','')}" if dep and arr else ""
    aircraft = (flight_info or {}).get("aircraft", "")

    passengers = (flight_info or {}).get("passengers", [])
    seat_assignments = ", ".join(
        f"{p['name']} - {p['seat']}" for p in passengers if p.get("name") and p.get("seat") and p.get("seat") != "--"
    ) or "unknown"

    header_fields = [
        ("Confirmation",  confirmation),
        ("Flight",        f"{flight_num}  {route}"),
        ("Aircraft",      aircraft),
        ("Current seats", seat_assignments),
    ]
    header = [f"  {k:14}: {v}" for k, v in header_fields]

    if hits:
        subject = f"SeatStalker: Target seat(s) available - {confirmation}"
        lines = ["Good news! The following target seats are currently available:", ""] + header + ["", "Available target seats:"]
        for h in hits:
            extras = []
            if h["exitRow"]:
                extras.append("exit row")
            if h["type"]:
                extras.append(h["type"])
            tag = f" ({', '.join(extras)})" if extras else ""
            lines.append(f"  * {h['seat']} - {h['cabin']}{tag}")
        lines += ["", f"Checked at: {checked_at}"]
        text_body = "\n".join(lines)
        html_body = build_html_body(text_body, build_seat_map_html(seat_map, targets), header_fields)
    else:
        subject = f"SeatStalker: No target seats available - {confirmation}"
        lines = (
            ["SeatStalker checked your reservation - none of your target seats are currently available.", ""]
            + header
            + [
                f"  {'Target seats':14}: {args.target_seats}",
                f"  {'Open seats':14}: {seat_map.get('availableSeats', '?')} available on this flight",
                "",
                f"Checked at: {checked_at}",
            ]
        )
        text_body = "\n".join(lines)
        html_body = None

    return subject, text_body, html_body


def main():
    parser = argparse.ArgumentParser(
        description="SeatStalker: check airline seat availability and email results. "
                    "All flags fall back to env vars in .env when not provided."
    )
    parser.add_argument("--confirmation", default=os.getenv("CONFIRMATION"),
                        help="Booking confirmation / locator (or set CONFIRMATION in .env)")
    parser.add_argument("--first-name",   default=os.getenv("FIRST_NAME"),
                        help="Passenger first name (or set FIRST_NAME in .env)")
    parser.add_argument("--last-name",    default=os.getenv("LAST_NAME"),
                        help="Passenger last name (or set LAST_NAME in .env)")
    parser.add_argument("--flight",       default=os.getenv("FLIGHT"),
                        help="Flight number or leg index (or set FLIGHT in .env)")
    parser.add_argument("--target-seats", default=os.getenv("TARGET_SEATS"),
                        help="Seats to watch, e.g. 20A,20B or 20-23 (or set TARGET_SEATS in .env)")
    parser.add_argument("--airline",      default=os.getenv("AIRLINE"),
                        help="Two-letter airline code (auto-detected from flight number if omitted)")
    args = parser.parse_args()

    missing = [f for f, v in [("--confirmation", args.confirmation), ("--first-name", args.first_name),
               ("--last-name", args.last_name), ("--flight", args.flight),
               ("--target-seats", args.target_seats)] if not v]
    if missing:
        parser.error(f"Missing required inputs (pass as flags or set in .env): {', '.join(missing)}")

    # Resolve airline — explicit flag/env wins; otherwise auto-detect from flight prefix
    airline_code = args.airline
    if not airline_code:
        airline_code = detect_airline(args.flight)
    if not airline_code:
        parser.error(
            f"Cannot determine airline from flight '{args.flight}'. "
            "Pass --airline DL (or set AIRLINE in .env)."
        )

    # Ensure tools/ is on the path so adapters/ is importable
    sys.path.insert(0, str(Path(__file__).parent))

    adapter = load_adapter(airline_code)
    flights, _ = adapter.get_trip(args.confirmation, args.first_name, args.last_name)
    flight_index, flight_info = resolve_flight_index(flights, args.flight)
    seat_map = adapter.get_seat_map(args.confirmation, args.first_name, args.last_name, flight_index)

    # Some adapters (e.g. Iberia) embed current seat assignments in the seatmap itself.
    # Backfill the flight info's passenger list so the email shows current seats correctly.
    current_seats = seat_map.get("currentSeats", {})
    if current_seats and flight_info:
        for p in flight_info.get("passengers", []):
            pax_id = p.get("_iberia_id", "")
            if pax_id in current_seats:
                p["seat"] = current_seats[pax_id]

    targets = parse_target_seats(args.target_seats)
    hits = find_available_targets(seat_map, targets)
    checked_at = datetime.now().strftime("%Y-%m-%d %I:%M %p")

    subject, body, html_body = build_email(seat_map, hits, flight_info, targets, args, checked_at)
    log(body)
    if hits:
        send_email(subject, body, html_body)
        log("Email sent.")
    else:
        log("No target seats available - email skipped.")
    log("-" * 60)


if __name__ == "__main__":
    main()
