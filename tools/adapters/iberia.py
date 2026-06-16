import json
import os
import pathlib
import re
import subprocess
import sys

from .base import AirlineAdapter

CLI = os.getenv("IBERIA_TRIP_CLI", "iberia-trips-pp-cli")
BASE_URL = "https://ibisservices.iberia.com"


def _run_cli(args):
    result = subprocess.run([CLI] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"iberia CLI error (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout


def _build_flight_id(flight_number, departure_datetime):
    """
    Construct the Iberia seatmap flight_id: carrier + 4-digit number + YYYYMMDD.
    e.g. "IB0333" + "20260815" -> "IB033320260815"
    """
    carrier = flight_number[:2].upper()
    num = re.sub(r"^[A-Z]{2}", "", flight_number.upper()).zfill(4)
    try:
        date_str = departure_datetime.split()[0].replace("-", "")  # "2026-08-15" -> "20260815"
    except Exception:
        date_str = ""
    return f"{carrier}{num}{date_str}"


def _normalize_flights(iberia_flights, passengers):
    """Map Iberia CLI flight dicts to the SeatStalker common schema."""
    pax = [
        {"name": f"{p.get('name', '')} {p.get('surname', '')}".strip(), "seat": "--"}
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
    Normalize Iberia's raw CISM seatmap JSON to SeatStalker schema.

    Iberia uses an Amadeus CISM seatmap. The response structure varies across
    API versions. Two known formats are attempted:
      Format A: data.decks[].seats (dict keyed by row number, then seat letter)
      Format B: data.decks[].seatRows[].seats[] (array form)

    If neither matches, the raw JSON is saved to .tmp/iberia_seatmap_raw.json.
    Share that file to improve this normalization.
    """
    data = raw.get("data", raw)
    decks = data.get("decks", [])
    cabins = []
    available_count = 0

    for deck in decks:
        cabin_name = deck.get("type", deck.get("deckInfo", {}).get("cabin", "Main Cabin"))
        rows_dict = {}

        # --- Format A: seats keyed by row number (Amadeus Shopping Seatmap) ---
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

        # --- Format B: seatRows[] array (Amadeus CISM) ---
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

    return {"cabins": cabins, "availableSeats": available_count, "aircraft": ""}


class IberiaAdapter(AirlineAdapter):
    """
    Adapter for Iberia via iberia-trips-pp-cli.

    get_trip  — calls the CLI (which uses the Python sidecar for Akamai bypass).
    get_seat_map — makes a direct Chrome-impersonated HTTP/3 request via curl_cffi,
                   using the orderToken returned by get_trip.
    """

    def __init__(self):
        self._raw_flights = []
        self._order_token = ""

    def get_trip(self, confirmation, first_name, last_name):
        # Iberia needs locator + surname only (first name is not required)
        args = ["trip", "get", "--locator", confirmation, "--surname", last_name, "--agent"]
        raw = _run_cli(args)
        trip = json.loads(raw)
        self._raw_flights = trip.get("flights", [])
        self._order_token = trip.get("orderToken", "")
        flights = _normalize_flights(self._raw_flights, trip.get("passengers", []))
        return flights, trip

    def get_seat_map(self, confirmation, first_name, last_name, flight_index):
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:
            print(
                "ERROR: curl_cffi is required for Iberia seatmap requests.\n"
                "Install it with: pip install curl_cffi",
                file=sys.stderr,
            )
            sys.exit(1)

        if not self._order_token:
            # Re-fetch if this adapter instance hasn't seen get_trip yet
            self.get_trip(confirmation, first_name, last_name)

        # Find the raw Iberia flight for this leg index
        raw_flight = next(
            (f for f in self._raw_flights
             if str(f.get("index", "")).startswith(str(flight_index))),
            (self._raw_flights[flight_index - 1] if len(self._raw_flights) >= flight_index else None),
        )
        if not raw_flight:
            print(f"ERROR: Flight leg {flight_index} not found in Iberia trip data.", file=sys.stderr)
            sys.exit(3)

        flight_number = raw_flight.get("flightNumber", "")
        dep_datetime = raw_flight.get("departure", {}).get("dateTime", "")
        flight_id = _build_flight_id(flight_number, dep_datetime)

        url = f"{BASE_URL}/api/sea-cism/rs/cism/v4/{self._order_token}/flight/{flight_id}/seatmapLayout"
        try:
            resp = cffi_requests.get(url, impersonate="chrome", timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"ERROR: Iberia seatmap request failed: {e}", file=sys.stderr)
            sys.exit(5)

        return _normalize_seatmap(resp.json())
