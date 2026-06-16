import json
import os
import subprocess
import sys

from .base import AirlineAdapter

CLI = os.getenv("DELTA_TRIP_CLI", "delta-trip-pp-cli")
HEADED = os.getenv("HEADED", "").lower() in ("1", "true", "yes")


def _run_cli(args):
    result = subprocess.run([CLI] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"delta CLI error (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout


class DeltaAdapter(AirlineAdapter):
    """Adapter for Delta Air Lines via delta-trip-pp-cli."""

    def get_trip(self, confirmation, first_name, last_name):
        args = ["trips", confirmation, first_name, last_name, "--json"]
        if HEADED:
            args.append("--headed")
        raw = _run_cli(args)
        data = json.loads(raw)
        trip = data.get("results", data)
        return trip.get("flights", []), trip

    def get_seat_map(self, confirmation, first_name, last_name, flight_index):
        args = ["seatmap", confirmation, first_name, last_name,
                "--flight", str(flight_index), "--agent"]
        if HEADED:
            args.append("--headed")
        raw = _run_cli(args)
        return json.loads(raw)
        # Delta JSON already matches the SeatStalker schema — no normalization needed.
