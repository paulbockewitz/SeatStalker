"""
Generate a preview HTML of the hit email using your real reservation data.
Simulates two seats as available so you can see what the email looks like
before a real hit occurs.

Usage:
    python scripts/gen_preview.py

Reads CONFIRMATION, FIRST_NAME, LAST_NAME, FLIGHT, TARGET_SEATS from .env.
Simulates the first two seats in TARGET_SEATS as available.
Output: .tmp/email_preview.html
"""
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)

from dotenv import load_dotenv
load_dotenv()

from check_seats import (
    load_adapter,
    detect_airline,
    resolve_flight_index,
    parse_target_seats,
    seat_matches_targets,
    build_seat_map_html,
    build_html_body,
)

confirmation = os.getenv("CONFIRMATION")
first_name   = os.getenv("FIRST_NAME")
last_name    = os.getenv("LAST_NAME")
flight_input = os.getenv("FLIGHT")
target_str   = os.getenv("TARGET_SEATS")
airline_code = os.getenv("AIRLINE") or detect_airline(flight_input or "")

if not all([confirmation, first_name, last_name, flight_input, target_str]):
    print("ERROR: Set CONFIRMATION, FIRST_NAME, LAST_NAME, FLIGHT, and TARGET_SEATS in .env", file=sys.stderr)
    sys.exit(1)
if not airline_code:
    print(f"ERROR: Cannot detect airline from FLIGHT='{flight_input}'. Set AIRLINE in .env.", file=sys.stderr)
    sys.exit(1)

adapter = load_adapter(airline_code)
flights, _ = adapter.get_trip(confirmation, first_name, last_name)
flight_index, flight_info = resolve_flight_index(flights, flight_input)
seat_map = adapter.get_seat_map(confirmation, first_name, last_name, flight_index)
targets = parse_target_seats(target_str)

# Simulate the first two specific target seats as available
sim_seats = [t for t in sorted(targets) if not t.startswith("ROW")][:2]
if not sim_seats:
    all_seats = [
        s["number"]
        for cabin in seat_map.get("cabins", [])
        for row in cabin.get("rows", [])
        for s in row.get("seats", [])
    ]
    sim_seats = [s for s in all_seats if seat_matches_targets(s, targets)][:2]

for cabin in seat_map.get("cabins", []):
    for row in cabin.get("rows", []):
        for seat in row.get("seats", []):
            if seat["number"] in sim_seats:
                seat["status"] = "available"

flight_num = (flight_info or {}).get("flightNumber", flight_input)
dep = (flight_info or {}).get("departure", {})
arr = (flight_info or {}).get("arrival", {})
route = f"{dep.get('airport','')} -> {arr.get('airport','')}" if dep and arr else ""
aircraft = (flight_info or {}).get("aircraft", "")
passengers = (flight_info or {}).get("passengers", [])
seat_assignments = ", ".join(
    f"{p['name']} - {p['seat']}" for p in passengers
    if p.get("name") and p.get("seat") and p.get("seat") != "--"
) or "unknown"

header_fields = [
    ("Confirmation",  confirmation.upper()),
    ("Flight",        f"{flight_num}  {route}"),
    ("Aircraft",      aircraft),
    ("Current seats", seat_assignments),
]
text_body = (
    "\n".join([f"* {s} - (simulated)" for s in sim_seats])
    + "\n\nChecked at: "
    + datetime.now().strftime("%Y-%m-%d %I:%M %p")
)

html = build_html_body(text_body, build_seat_map_html(seat_map, targets), header_fields)

out = ROOT / ".tmp" / "email_preview.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"Preview written to {out.resolve()}")
print(f"Simulated available seats: {', '.join(sim_seats)}")
