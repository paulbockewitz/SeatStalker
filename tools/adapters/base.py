from abc import ABC, abstractmethod


class AirlineAdapter(ABC):
    """
    Contract every airline adapter must implement.

    get_trip and get_seat_map both normalize their output to the SeatStalker
    schema so check_seats.py never needs to know which airline it's talking to.
    """

    @abstractmethod
    def get_trip(self, confirmation, first_name, last_name):
        """
        Fetch trip data and return (flights_list, raw_trip_dict).

        flights_list items must have:
          flightNumber  str          e.g. "DL0256"
          flightIndex   str          e.g. "1 of 2"
          aircraft      str          e.g. "Boeing 737-800"  (may be "")
          departure     dict         {airport, city, time, date}
          arrival       dict         {airport, city, time, date}
          passengers    list[dict]   [{name, seat}]  seat may be "--"

        raw_trip_dict is the full response for logging/debugging.
        """

    @abstractmethod
    def get_seat_map(self, confirmation, first_name, last_name, flight_index):
        """
        Fetch the seat map for the given 1-based leg index and return a dict:

          cabins          list  [{name, rows: [{row: int, seats: [{number, status, type, exitRow}]}]}]
          availableSeats  int
          aircraft        str   (may be "")

        seat status values: "available", "occupied", "blocked", "your-seat"
        """
