from datetime import date
from typing import Optional, Sequence, List, Dict, Any, Tuple

from .Database_Manager_abstract import AbstractDatabaseService


class PublicDatabaseService(AbstractDatabaseService):
    # ──────────────────────────────────────────────────────────────
    # FLEXIBLE SEARCH – every filter is optional
    # ──────────────────────────────────────────────────────────────
    def view_flights(
        self,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        on_or_after: Optional[date] = None,
    ) -> List[Dict]:
        sql = """
            SELECT  F.*,
                    dep.City AS Departure_City,
                    arr.City AS Arrival_City
            FROM    Flight   F
            JOIN    Airport  dep ON dep.Name = F.Departure_Airport
            JOIN    Airport  arr ON arr.Name = F.Arrival_Airport
            WHERE   F.Status_ = 'Upcoming'
                  {src_filter} {dst_filter} {date_filter}
            ORDER BY F.Departure_Date, F.Departure_Time
        """

        src_filter  = "AND (F.Departure_Airport = %s OR dep.City = %s)" if source else ""
        dst_filter  = "AND (F.Arrival_Airport   = %s OR arr.City = %s)" if destination else ""
        date_filter = "AND F.Departure_Date >= %s"                      if on_or_after else ""

        params: Sequence[Any] = tuple(
            x
            for grp in (
                (source, source)           if source      else (),
                (destination, destination) if destination else (),
                (on_or_after,)             if on_or_after else (),
            )
            for x in grp
        )

        return self._fetchall(sql.format(
            src_filter=src_filter,
            dst_filter=dst_filter,
            date_filter=date_filter,
        ), params)
    
    def list_airport_labels(self) -> List[str]:
        """
        Returns labels like “New York-JFK”, “Los Angeles-LAX”, …,
        one per active airport, sorted A-Z (case-insensitive).
        """
        rows = self._fetchall(
            """
            SELECT DISTINCT A.City, A.Name AS code
            FROM   Airport A
            WHERE  A.Name IN (
                     SELECT Departure_Airport FROM Flight
                     UNION
                     SELECT Arrival_Airport   FROM Flight
                   )
            """
        )
        # e.g. "New York-JFK"
        return sorted({f"{r['City']}-{r['code']}" for r in rows},
                      key=lambda s: s.lower())


    # ------------------------------------------------------------------
    # Handy default: *all* upcoming flights
    # ------------------------------------------------------------------
    def view_upcoming_flights(self) -> List[Dict]:
        return self._fetchall(
            """
            SELECT  F.*,
                    dep.City AS Departure_City,
                    arr.City AS Arrival_City
            FROM    Flight   F
            JOIN    Airport  dep ON dep.Name = F.Departure_Airport
            JOIN    Airport  arr ON arr.Name = F.Arrival_Airport
            WHERE   F.Status_ = 'Upcoming'
            ORDER BY F.Departure_Date, F.Departure_Time
            """,
            ()
        )

    # ───── existence helpers ───────────────────────────────────────
    def customer_exists(self, email: str) -> bool:
        return self._fetchone("SELECT 1 FROM Customer WHERE Email = %s", (email,)) is not None

    def booking_agent_email_exists(self, email: str) -> bool:
        return self._fetchone("SELECT 1 FROM Booking_Agent WHERE Email = %s", (email,)) is not None

    def booking_agent_id_exists(self, agent_id: str) -> bool:
        return self._fetchone("SELECT 1 FROM Booking_Agent WHERE Booking_Agent_ID = %s", (agent_id,)) is not None

    def staff_exists(self, username: str) -> bool:
        return self._fetchone("SELECT 1 FROM Airline_Staff WHERE Username = %s", (username,)) is not None

    # ------------------------------------------------------------------
    # Flight-status lookup
    # ------------------------------------------------------------------
    def flight_status(
        self,
        flight_id: str,
        airline: str,
        on_date: date
    ) -> Optional[Dict]:
        return self._fetchone(
            """
            SELECT Status_
            FROM   Flight
            WHERE  Flight_ID      = %s
              AND  Airline        = %s
              AND  Departure_Date = %s
            """,
            (flight_id, airline, on_date)
        )

    # ------------------------------------------------------------------
    # Login helpers
    # ------------------------------------------------------------------
    def authenticate_customer(self, email: str):
        cur = self._execute_query("SELECT * FROM Customer WHERE Email = %s", (email,))
        row = cur.fetchone()
        cur.close()
        return row

    def authenticate_booking_agent(self, email: str, booking_agent_id: str):
        cur = self._execute_query(
            "SELECT * FROM Booking_Agent WHERE Email = %s AND Booking_Agent_ID = %s",
            (email, booking_agent_id)
        )
        row = cur.fetchone()
        cur.close()
        return row

    def authenticate_airline_staff(self, username: str):
        return self._fetchone(
            """
            SELECT Username  AS username,
                   Airline    AS airline,
                   First_Name AS first_name,
                   Last_Name  AS last_name,
                   Password,
                   Role       AS permission
            FROM   Airline_Staff
            WHERE  Username = %s
            """,
            (username,)
        )

    # ------------------------------------------------------------------
    # INSERT helpers  (all use _execute_query → commits automatically)
    # ------------------------------------------------------------------
    def _exec(self, sql: str, params: Dict[str, Any]):
        """Internal convenience wrapper that hides the cursor object."""
        cur = self._execute_query(sql, params)
        cur.close()

    def create_customer(self, **k):
        sql = """
            INSERT INTO Customer
                (Email, Password,
                    First_Name, Middle_Name, Last_Name,
                    State, City, Building_Name, Zip_Code,
                    Phone_Number,
                    Passport_Number, Passport_Country, Passport_Expiration_Date,
                    DoB)
            VALUES (%(email)s,
                    MD5(%(password)s),
                    %(first_name)s, %(middle_name)s, %(last_name)s,
                    %(state)s, %(city)s, %(building_name)s, %(zip_code)s,
                    %(phone)s,
                    %(passport_no)s, %(passport_country)s, %(passport_exp)s,
                    %(dob)s)
        """
        self._exec(sql, k)

    def create_booking_agent(self, **k):
        print(k)
        sql = """
            INSERT INTO Booking_Agent
                   (Email, Password, Booking_Agent_ID)
            VALUES (%(email)s,
                    MD5(%(password)s),
                    %(booking_agent_id)s)
        """
        self._exec(sql, k)

    def create_staff(self, **k):
        sql = """
            INSERT INTO Airline_Staff
                   (Username, Password,
                    First_Name, Middle_Name, Last_Name,
                    DoB, Airline, Role)
            VALUES (%(username)s,
                    MD5(%(password)s),
                    %(first_name)s, %(middle_name)s, %(last_name)s,
                    %(dob)s, %(airline_name)s,
                    NULL)
        """
        self._exec(sql, k)

    # ------------------------------------------------------------------
    # Misc.
    # ------------------------------------------------------------------
    def list_airports(self) -> List[str]:
        rows = self._fetchall(
            "SELECT DISTINCT Departure_Airport AS ap FROM Flight "
            "UNION SELECT DISTINCT Arrival_Airport FROM Flight"
        )
        return sorted(r["ap"] for r in rows)
