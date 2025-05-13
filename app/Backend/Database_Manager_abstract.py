from __future__ import annotations

import mysql.connector
from mysql.connector.connection_cext import CMySQLConnection
from typing import Any, Dict, List, Tuple, Sequence, Optional
from datetime import date
from abc import ABC


class AbstractDatabaseService(ABC):
    """Common backend heler for all DB access layers."""

    # ────────────────────────── constructor ──────────────────────────── #

    def __init__(
        self,
        host: str = "localhost",
        user: str = "root",
        password: str = "",
        database: str = "flight_ticket_system",
        port: int = 3306,
        **kwargs,
    ) -> None:
        # store connection config – reused by automatic reconnects
        self._cfg: Dict[str, Any] = dict(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            **kwargs,
        )
        self._cnx: Optional[CMySQLConnection] = None  # opened lazily

    # ───────────────────── connection‑management API ──────────────────── #

    def _ensure_open(self) -> None:
        """Open the connection or revive it if the TCP socket died."""
        if self._cnx is None:
            self._cnx = mysql.connector.connect(**self._cfg)
        else:
            try:
                # Auto‑reconnect if ping fails (drops take‑over ~1 ms)
                self._cnx.ping(reconnect=True, attempts=2, delay=0)
            except mysql.connector.Error:
                # Last resort: hard reset
                try:
                    self._cnx.close()
                finally:
                    self._cnx = mysql.connector.connect(**self._cfg)

    def disconnect(self) -> None:
        """Gracefully close the physical socket (if any)."""
        if self._cnx and self._cnx.is_connected():
            self._cnx.close()
            self._cnx = None

    # ───────────────────────── low‑level helpers ──────────────────────── #

    def _cursor(self):
        """Return a **buffered** dict‑cursor so no unread‑result remains."""
        self._ensure_open()
        return self._cnx.cursor(dictionary=True, buffered=True)

    def _execute_query(
        self,
        query: str,
        params: Sequence | Dict | Tuple | None = None,
    ):
        """Run *query* with *params* and return the cursor.

        • For SELECT we *do not* commit (obviously).
        • For DML (INSERT/UPDATE/DELETE) we commit immediately.
        """
        cur = self._cursor()
        cur.execute(query, params or ())
        if not query.lstrip().upper().startswith("SELECT"):
            self._cnx.commit()
        return cur  # Caller decides whether/when to close

    # ─────────────────────── high‑level convenience ───────────────────── #

    def _fetchone(
        self,
        sql: str,
        params: Sequence | Dict | Tuple | None = None,
    ) -> Optional[Dict[str, Any]]:
        cur = self._execute_query(sql, params)
        row = cur.fetchone()
        cur.close()
        return row

    def _fetchall(
        self,
        sql: str,
        params: Sequence | Dict | Tuple | None = None,
    ) -> List[Dict[str, Any]]:
        cur = self._execute_query(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def execute_write(
        self,
        sql: str,
        params: Sequence | Dict | Tuple | None = None,
    ) -> None:
        """Convenience wrapper for INSERT/UPDATE/DELETE."""
        cur = self._execute_query(sql, params)
        cur.close()

    # ───────────────────────── business helpers ───────────────────────── #

    def search_upcoming_flights(
        self,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        on_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        sql = """
            SELECT *
            FROM   Flight
            WHERE  Status_ = 'Upcoming'
              {src}
              {dst}
              {dt}
            ORDER  BY Departure_Date, Departure_Time
        """
        src = "AND Departure_Airport = %s" if source else ""
        dst = "AND Arrival_Airport   = %s" if destination else ""
        dt = "AND Departure_Date    = %s" if on_date else ""

        params: Tuple = tuple(x for x in (source, destination, on_date) if x)
        return self._fetchall(sql.format(src=src, dst=dst, dt=dt), params)

    def _remaining_seats(self, airline: str, flight_id: str) -> int:
        sql = """
            SELECT A.Number_Seats - COUNT(T.Ticket_ID) AS remaining
            FROM   Flight    F
            JOIN   Airplane  A  ON A.Airline     = F.Airline
                               AND A.Airplane_ID = F.Airplane_ID
            LEFT   JOIN Ticket   T ON T.Airline   = F.Airline
                                   AND T.Flight_ID= F.Flight_ID
            WHERE  F.Airline   = %s
              AND  F.Flight_ID = %s
            GROUP  BY A.Number_Seats
        """
        row = self._fetchone(sql, (airline, flight_id))
        return 0 if row is None else int(row["remaining"])
