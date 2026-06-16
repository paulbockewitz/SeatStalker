import json
import os
import pathlib
import subprocess
import sys

from .base import AirlineAdapter

CLI = os.getenv("IBERIA_TRIP_CLI", "iberia-trips-pp-cli")


def _run_cli(args):
    result = subprocess.run([CLI] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"iberia CLI error (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout



def _normalize_flights(iberia_flights, passengers):
    """Map Iberia CLI flight dicts to the SeatStalker common schema."""
    pax = [
        {"name": f"{p.get('name', '')} {p.get('surname', '')}".strip(), "seat": "--",
         "_iberia_id": p.get("id", "")}
        for p in passengers
    ]
    normalized = []
    for f in iberia_flights:
        dep = f.get("departure", {})
        arr = f.get("arrival", {})
        normalized.append({
            "flightNumber": f.get("flightNumber", ""),
            "flightIndex":  f.get("index", ""),
            "aircraft":     f.get("aircraft", ""),
            "departure": {
                "airport":  dep.get("airport", ""),
                "city":     dep.get("city", ""),
                "time":     dep.get("time", ""),
                "date":     dep.get("date", ""),
                "dateTime": dep.get("dateTime", ""),
            },
            "arrival": {
                "airport":  arr.get("airport", ""),
                "city":     arr.get("city", ""),
                "time":     arr.get("time", ""),
                "date":     arr.get("date", ""),
                "dateTime": arr.get("dateTime", ""),
            },
            "passengers": pax,
        })
    return normalized


def _normalize_seatmap(raw):
    """
    Normalize Iberia's CISM seatmap JSON to SeatStalker schema.

    Three response formats are handled in priority order:
      Format C: raw["cabins"][].map[][] — v4 sea-cism (SPA navigation path, primary)
      Format A: raw["decks"][].seats — dict keyed by row (Amadeus Shopping Seatmap)
      Format B: raw["decks"][].seatRows[] — array form (Amadeus CISM)
    """
    data = raw.get("data", raw)
    available_count = 0
    cabins = []
    aircraft = ""
    if isinstance(data.get("aircraft"), dict):
        aircraft = data["aircraft"].get("model", "")

    # Format C: cabins[].map[][] with occupation "FREE"/"OCCUPIED"/"BLOCKED"
    current_seats = {}  # passenger_id -> seat_number, e.g. {"ADULT_01": "21C"}
    if data.get("cabins"):
        for cabin in data["cabins"]:
            cabin_name = (cabin.get("cabinClass", {}).get("type") or "Main Cabin").title()
            rows_dict = {}
            for seat_row in cabin.get("map", []):
                for seat in seat_row:
                    if not isinstance(seat, dict) or seat.get("type") != "SEAT":
                        continue
                    try:
                        row_num = int(seat.get("row", ""))
                    except (ValueError, TypeError):
                        continue
                    col = seat.get("column", "")
                    features = seat.get("features") or []
                    occupation = seat.get("occupation", "")
                    allowed = seat.get("passengersAllowed") or []
                    seat_num = "%s%s" % (seat["row"], col)
                    if occupation == "FREE":
                        status = "available"
                        available_count += 1
                    elif occupation == "BLOCKED" and len(allowed) == 1:
                        # Single passenger allowed on a BLOCKED seat = their current assignment
                        status = "your-seat"
                        current_seats[allowed[0]] = seat_num
                    else:
                        status = "occupied"
                    rows_dict.setdefault(row_num, []).append({
                        "number": seat_num,
                        "status": status,
                        "type": ("window" if "WINDOW" in features
                                 else "aisle" if "AISLE" in features
                                 else "middle"),
                        "exitRow": "EMERGENCY_EXIT" in features,
                    })
            if rows_dict:
                cabins.append({
                    "name": cabin_name,
                    "rows": [{"row": rn, "seats": rows_dict[rn]} for rn in sorted(rows_dict)],
                })

    if not cabins:
        # Format A & B: decks[] — legacy Amadeus seatmap fallback
        for deck in data.get("decks", []):
            cabin_name = deck.get("type", deck.get("deckInfo", {}).get("cabin", "Main Cabin"))
            rows_dict = {}

            # Format A: seats keyed by row number (dict)
            seats_map = deck.get("seats", {})
            if seats_map and isinstance(seats_map, dict):
                for row_num_str, row_data in seats_map.items():
                    if not isinstance(row_data, dict):
                        continue
                    try:
                        row_num = int(row_num_str)
                    except ValueError:
                        continue
                    seats = []
                    for _, seat_data in row_data.items():
                        if not isinstance(seat_data, dict):
                            continue
                        seat_num = seat_data.get("number", "")
                        available = bool(seat_data.get("available", False))
                        chars = seat_data.get("characteristicsCodes", [])
                        if available:
                            available_count += 1
                        seats.append({
                            "number": seat_num,
                            "status": "available" if available else "occupied",
                            "type": ("window" if "W" in chars else "aisle" if "A" in chars else "middle"),
                            "exitRow": "EM" in chars or "EX" in chars,
                        })
                    if seats:
                        rows_dict[row_num] = seats

            # Format B: seatRows[] array
            seat_rows = deck.get("seatRows", [])
            if not rows_dict and seat_rows:
                for row_obj in seat_rows:
                    row_num = row_obj.get("number", 0)
                    seats = []
                    for seat_data in row_obj.get("seats", []):
                        if not isinstance(seat_data, dict):
                            continue
                        seat_num = seat_data.get("number", "")
                        status_code = seat_data.get("availabilityStatus", "BLOCKED")
                        available = status_code == "AVAILABLE"
                        chars = seat_data.get("characteristicsCodes", [])
                        if available:
                            available_count += 1
                        seats.append({
                            "number": seat_num,
                            "status": "available" if available else "occupied",
                            "type": ("window" if "W" in chars else "aisle" if "A" in chars else "middle"),
                            "exitRow": "EM" in chars or "EX" in chars,
                        })
                    if seats:
                        rows_dict[row_num] = seats

            if rows_dict:
                cabins.append({
                    "name": cabin_name,
                    "rows": [{"row": rn, "seats": rows_dict[rn]} for rn in sorted(rows_dict)],
                })

    if not cabins:
        dump_path = pathlib.Path(".tmp") / "iberia_seatmap_raw.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        print(
            f"WARNING: Could not normalize Iberia seatmap response.\n"
            f"Raw response saved to {dump_path.resolve()}\n"
            f"Share this file to improve the Iberia adapter normalization.",
            file=sys.stderr,
        )
        cabins = [{"name": "Main Cabin", "rows": []}]

    return {"cabins": cabins, "availableSeats": available_count, "aircraft": aircraft,
            "currentSeats": current_seats}


class IberiaAdapter(AirlineAdapter):
    """Adapter for Iberia via iberia-trips-pp-cli."""

    def get_trip(self, confirmation, first_name, last_name):
        # Iberia needs locator + surname only (first name is not required).
        # Use a 2-hour cache TTL: trip data is stable and Akamai rate-limits
        # back-to-back sessions, so fetching less often is safer.
        args = ["trip", "get", "--locator", confirmation, "--surname", last_name,
                "--agent", "--max-age", "2h"]
        raw = _run_cli(args)
        try:
            trip = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"iberia: failed to parse trip JSON: {e}\nOutput: {raw[:200]}", file=sys.stderr)
            sys.exit(1)
        flights = _normalize_flights(trip.get("flights", []), trip.get("passengers", []))
        return flights, trip

    def get_seat_map(self, confirmation, first_name, last_name, flight_index):
        args = ["trip", "seatmap", "--locator", confirmation, "--surname", last_name,
                "--flight", str(flight_index), "--agent"]
        raw = _run_cli(args)
        try:
            return _normalize_seatmap(json.loads(raw))
        except json.JSONDecodeError as e:
            print(f"iberia: failed to parse seatmap JSON: {e}\nOutput: {raw[:200]}", file=sys.stderr)
            sys.exit(1)
