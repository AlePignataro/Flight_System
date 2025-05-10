from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Optional, Sequence, Any
from datetime import date, datetime, timedelta
from .Database_Manager_abstract import AbstractDatabaseService
import random

class AbstractUserDB(AbstractDatabaseService, ABC):
    """
    Anything shared by *all* logged-in users goes here.
    If you add new user types later they will automatically inherit it.
    """
    _ALLOWED_FLIGHT_COLS = {
        "Airline",
        "Flight_ID",
        "Departure_Airport",
        "Departure_Date",
        "Departure_Time",
        "Arrival_Airport",
        "Arrival_Date",
        "Arrival_Time",
        "Status_",
        "Price",
    }

    def _upcoming_clause(self, alias: str | None = "F") -> str:
        """
        Return SQL that is TRUE only for flights strictly in the future.

        alias = None   -> un-prefixed columns  (Departure_Date …)
        alias = 'F'    -> F.Departure_Date …   etc.
        """
        p = f"{alias}." if alias else ""
        return (
            f"({p}Departure_Date >  CURDATE() "
            f"OR ({p}Departure_Date = CURDATE() AND {p}Departure_Time > CURTIME()))"
        )


    def search_upcoming_flights(
        self,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        on_date: Optional[date] = None,
        *,
        allowed_airlines: Optional[Sequence[str]] = None,   # <-- NEW
        customer_email: Optional[str] = None,
        booking_agent_id: Optional[str] = None,
        airline_staff_id: Optional[str] = None,
        role: Optional[str] = None,
    ) -> List[Dict]:
        """
        Generic search used by every role.
        Always restricted to future flights via _upcoming_clause().

        Parameters
        ----------
        …
        allowed_airlines : iterable[str] | None
            If given, restrict to F.Airline IN ( … ).
            Handy for booking-agents (only airlines they work for) or
            staff (their own airline).
        """
        filters = [self._upcoming_clause("F")]
        params: list[Any] = []

        # ------------------------------------------------ city / date filters
        if source:
            filters.append("F.Departure_Airport = %s")
            params.append(source)

        if destination:
            filters.append("F.Arrival_Airport = %s")
            params.append(destination)

        if on_date:
            filters.append("F.Departure_Date = %s")
            params.append(on_date)

        # ------------------------------------------------ airline whitelist
        if allowed_airlines:
            placeholders = ", ".join(["%s"] * len(allowed_airlines))
            filters.append(f"F.Airline IN ({placeholders})")
            params.extend(allowed_airlines)

        # ------------------------------------------------ role-specific joins
        if role == "customer" and customer_email:
            filters.append("T.Customer_Email = %s")
            params.append(customer_email)

        if role == "booking_agent" and booking_agent_id:
            filters.append("T.Booking_Agent_ID = %s")
            params.append(booking_agent_id)

        if role == "airline_staff" and airline_staff_id:
            filters.append("S.Username = %s")
            params.append(airline_staff_id)

        sql = f"""
            SELECT F.*
            FROM   Flight F
            LEFT  JOIN Ticket        T ON T.Airline = F.Airline   AND T.Flight_ID = F.Flight_ID
            LEFT  JOIN Airline_Staff S ON S.Airline = F.Airline
            WHERE  {' AND '.join(filters)}
            ORDER  BY F.Departure_Date, F.Departure_Time
        """
        return self._fetchall(sql, tuple(params))

    def _insert_ticket_row(
        self,
        *,
        airline: str,
        flight_id: int,
        customer_email: str,
        booking_agent_id: str | None,
    ) -> str:
        """Internal helper that actually INSERTs the row and returns Ticket_ID."""
        # generate unique Ticket_ID
        while True:
            ticket_id = f"TKT{random.randint(0, 9999):04d}"
            clash = self._fetchone(
                "SELECT 1 FROM Ticket WHERE Ticket_ID = %s", (ticket_id,)
            )
            if not clash:
                break

        self._execute_query(
            """
            INSERT INTO Ticket
                (Ticket_ID, Airline, Flight_ID,
                Customer_Email, Booking_Agent_ID, Purchase_Date)
            VALUES (%s,        %s,      %s,
                    %s,        %s,      CURDATE())
            """,
            (
                ticket_id,
                airline,
                flight_id,
                customer_email,
                booking_agent_id,
            ),
        )
        return ticket_id


    
    def check_existing_ticket(self, flight_id: int, customer_email: str) -> str:
        """
        Check if a customer already has a ticket for the selected flight.
        Returns the existing ticket_id if found, otherwise None.
        """
        result = self._fetchone(
            "SELECT Ticket_ID FROM Ticket WHERE Flight_ID = %s AND Customer_Email = %s",
            (flight_id, customer_email)
        )
        return result['Ticket_ID'] if result else None

    @abstractmethod
    def get_upcoming_flights(self, *owner_key) -> List[Dict]: ...
    @abstractmethod
    def get_past_flights(self, *owner_key,
                         start: Optional[date] = None,
                         end: Optional[date] = None) -> List[Dict]: ...

class CustomerDB(AbstractUserDB):
    """Queries that only a *customer* can run."""

    # ––– profile –––
    def profile(self, email: str) -> Optional[Dict]:
        return self._fetchone(
            """
            SELECT *
            FROM Customer 
            WHERE Email = %s
            """,
            (email,)
        )


    # ––– flights –––
    def get_upcoming_flights(self, email: str) -> List[Dict]:
        sql = f"""
            SELECT F.*
            FROM   Ticket  T
            JOIN   Flight  F ON T.Airline = F.Airline AND T.Flight_ID = F.Flight_ID
            WHERE  T.Customer_Email = %s
            AND  {self._upcoming_clause()}
            ORDER  BY F.Departure_Date, F.Departure_Time
        """
        return self._fetchall(sql, (email,))


    def get_past_flights(
        self,
        email: str,
        start: Optional[date] = None,
        end:   Optional[date] = None,
    ) -> List[Dict]:
        sql = """
            SELECT F.*
            FROM   Ticket T
            JOIN   Flight F
                   ON T.Airline   = F.Airline
                  AND T.Flight_ID = F.Flight_ID
            WHERE  T.Customer_Email = %s
              AND  F.Departure_Date < CURRENT_DATE
              {start_filter}
              {end_filter}
        """
        sf = "AND F.Departure_Date >= %s" if start else ""
        ef = "AND F.Departure_Date <= %s" if end   else ""
        return self._fetchall(
            sql.format(start_filter=sf, end_filter=ef),
            tuple(x for x in (email, start, end) if x)
        )

    # ––– purchase –––
    def purchase_ticket(
        self, *,
        flight_id: int,
        airline: str,
        customer_email: str
    ) -> str:
        """
        Direct purchase by the customer themself (no booking-agent commission).
        Raises RuntimeError if:
        • customer already holds a ticket
        • flight has departed / is departing now
        • no seats remain
        Returns the new Ticket_ID.
        """
        # duplicate check
        if self.check_existing_ticket(flight_id, customer_email):
            raise RuntimeError("You already have a ticket for this flight.")

        # future-flight guard
        future_ok = self._fetchone(
            f"SELECT 1 FROM Flight WHERE Airline=%s AND Flight_ID=%s AND {self._upcoming_clause("Flight")}",
            (airline, flight_id)
        )
        if not future_ok:
            raise RuntimeError("Flight already departed – cannot purchase.")

        # seat availability
        if self._remaining_seats(airline, flight_id) <= 0:
            raise RuntimeError("No seats available on this flight.")

        # write row (no booking agent → NULL)
        return self._insert_ticket_row(
            airline=airline,
            flight_id=flight_id,
            customer_email=customer_email,
            booking_agent_id=None,
        )

    
    def airports_used(self, email: str) -> Tuple[List[str], List[str]]:
        """Return two lists: departure airports and arrival airports the customer has flown through."""
        sql_dep = "SELECT DISTINCT Departure_Airport AS ap FROM Flight F JOIN Ticket T ON F.Airline=T.Airline AND F.Flight_ID=T.Flight_ID WHERE T.Customer_Email=%s"
        sql_arr = "SELECT DISTINCT Arrival_Airport   AS ap FROM Flight F JOIN Ticket T ON F.Airline=T.Airline AND F.Flight_ID=T.Flight_ID WHERE T.Customer_Email=%s"
        dep = [r["ap"] for r in self._fetchall(sql_dep, (email,))]
        arr = [r["ap"] for r in self._fetchall(sql_arr, (email,))]
        return sorted(dep), sorted(arr)


    # ––– spending analytics –––
    def yearly_spending(self, email: str) -> Dict:
        """
        Total spent in last 12 months + month-wise breakdown for last 6 months.
        """
        sql_tot = """
            SELECT SUM(F.Price) AS total
            FROM   Ticket T
            JOIN   Flight F
                   ON F.Airline   = T.Airline
                  AND F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
              AND  F.Departure_Date > DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
        """
        total = self._fetchone(sql_tot, (email,))["total"] or 0

        sql_bar = """
            SELECT DATE_FORMAT(F.Departure_Date, '%%Y-%%m') AS yr_mon,
                   SUM(F.Price)                             AS spent
            FROM   Ticket T
            JOIN   Flight F
                   ON F.Airline   = T.Airline
                  AND F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
              AND  F.Departure_Date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP  BY yr_mon
            ORDER  BY yr_mon
        """
        bars = self._fetchall(sql_bar, (email,))
        return {"total": total, "bars": bars}

    def spending_between(self, email: str, start: date, end: date) -> Dict:
        sql = """
            SELECT SUM(F.Price) AS total
            FROM   Ticket T
            JOIN   Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
              AND  F.Departure_Date BETWEEN %s AND %s
        """
        return self._fetchone(sql, (email, start, end))
    
    def past_tickets(self, email: str, start: date, end: date):
        """Tickets purchased between start & end inclusive."""
        sql = """
            SELECT F.*, T.Purchase_Date
            FROM   Ticket T
            JOIN   Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
            AND  T.Purchase_Date  BETWEEN %s AND %s
            ORDER  BY T.Purchase_Date
        """
        return self._fetchall(sql, (email, start, end))


    def tickets_per_month(self, email: str, start: date, end: date):
        sql = """
            SELECT DATE_FORMAT(T.Purchase_Date,'%Y-%m') AS yr_mon,
                COUNT(*)                           AS tickets
            FROM   Ticket T
            WHERE  T.Customer_Email = %s
            AND  T.Purchase_Date BETWEEN %s AND %s
            GROUP  BY yr_mon
            ORDER  BY yr_mon
        """
        return self._fetchall(sql, (email, start, end))


    def spend_per_month(self, email: str, start: date, end: date):
        sql = """
            SELECT DATE_FORMAT(T.Purchase_Date,'%Y-%m') AS yr_mon,
                SUM(F.Price)                         AS spent
            FROM   Ticket T
            JOIN   Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
            AND  T.Purchase_Date BETWEEN %s AND %s
            GROUP  BY yr_mon
            ORDER  BY yr_mon
        """
        return self._fetchall(sql, (email, start, end))
    
    def get_departure_airports(self) -> list[str]:
        """
        Return every airport code that appears as a departure airport
        on flights that haven’t taken off yet (today or later).
        """
        sql = """
            SELECT DISTINCT Departure_Airport AS ap
            FROM   Flight
            WHERE  Departure_Date >= CURDATE()      
            ORDER  BY ap
        """
        return [row["ap"] for row in self._fetchall(sql)]

    def get_arrival_airports(self) -> list[str]:
        """
        Return every airport code that appears as an arrival airport
        on flights that haven’t taken off yet (today or later).
        """
        sql = """
            SELECT DISTINCT Arrival_Airport AS ap
            FROM   Flight
            WHERE  Departure_Date >= CURDATE()      
            ORDER  BY ap
        """
        return [row["ap"] for row in self._fetchall(sql)]
    
    def past_tickets(self, email: str, start: date, end: date) -> list[dict]:
        sql = """
            SELECT F.*,
                T.Purchase_Date,
                T.Booking_Agent_ID                    AS Agent_ID,

                F.Price                               AS Price,      -- base
                CASE WHEN T.Booking_Agent_ID IS NULL
                        THEN 0
                        ELSE ROUND(F.Price * 0.10, 2)
                END                                  AS Commission,

                CASE WHEN T.Booking_Agent_ID IS NULL
                        THEN F.Price
                        ELSE ROUND(F.Price * 1.10, 2)
                END                                  AS Paid
            FROM   Ticket T
            JOIN   Flight F
                ON F.Airline   = T.Airline
                AND F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
            AND  F.Departure_Date BETWEEN %s AND %s
            ORDER  BY F.Departure_Date, F.Departure_Time
        """
        return self._fetchall(sql, (email, start, end))


    def spend_breakdown(self, email: str, start: date, end: date) -> dict:
        sql = """
            SELECT
              /* total paid (base or base+10 %) */
              SUM(CASE WHEN T.Booking_Agent_ID IS NULL
                       THEN  F.Price
                       ELSE  F.Price * 1.10 END)               AS total_spend,

              SUM(CASE WHEN T.Booking_Agent_ID IS NULL
                       THEN  F.Price END)                      AS direct_spend,

              SUM(CASE WHEN T.Booking_Agent_ID IS NOT NULL
                       THEN  F.Price * 1.10 END)               AS agent_spend,

              COUNT(*)                                         AS total_tix,
              SUM(CASE WHEN T.Booking_Agent_ID IS NULL  THEN 1 ELSE 0 END) AS direct_tix,
              SUM(CASE WHEN T.Booking_Agent_ID IS NOT NULL THEN 1 ELSE 0 END) AS agent_tix
            FROM   Ticket T
            JOIN   Flight F
              ON   F.Airline   = T.Airline
             AND   F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
              AND  F.Departure_Date BETWEEN %s AND %s
        """
        return self._fetchone(sql, (email, start, end))

    def spend_per_month(self, email: str, start: date, end: date) -> list[dict]:
        sql = """
            SELECT DATE_FORMAT(F.Departure_Date,'%Y-%m') AS yr_mon,
                   SUM(
                     CASE WHEN T.Booking_Agent_ID IS NULL
                          THEN  F.Price
                          ELSE  F.Price * 1.10 END
                   ) AS spent
            FROM   Ticket T
            JOIN   Flight F
              ON   F.Airline   = T.Airline
             AND   F.Flight_ID = T.Flight_ID
            WHERE  T.Customer_Email = %s
              AND  F.Departure_Date BETWEEN %s AND %s
            GROUP  BY yr_mon
            ORDER  BY yr_mon
        """
        return self._fetchall(sql, (email, start, end))


    

# ───────────────────────── booking_agents.py ─────────────────────────
class BookingAgentDB(AbstractUserDB):
    """Queries available *only* to booking-agents."""

    # ––– meta –––
    def agent_airlines(self, agent_id: str) -> List[str]:
        rows = self._fetchall(
            "SELECT Airline FROM Work_For WHERE Booking_Agent_ID = %s",
            (agent_id,)
        )
        return [r["Airline"] for r in rows]

    # ––– flights –––
    def get_upcoming_flights(self, agent_id: str) -> List[Dict]:
        sql = f"""
            SELECT F.*, T.Customer_Email
            FROM   Ticket T
            JOIN   Flight F ON T.Airline = F.Airline AND T.Flight_ID = F.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
            AND  {self._upcoming_clause()}
            ORDER  BY F.Departure_Date, F.Departure_Time
        """
        return self._fetchall(sql, (agent_id,))


    def get_past_flights(
        self,
        agent_id: str,
        customer_email: Optional[str] = None,
        departure_airport: Optional[str] = None,
        arrival_airport:   Optional[str] = None,
        start: Optional[date] = None,
        end:   Optional[date] = None,
    ) -> List[Dict]:
        """
        Past flights sold by this booking-agent, optionally filtered by
        customer, date range, and/or departure/arrival airport.
        """
        conditions = [
            "T.Booking_Agent_ID = %s",
            "F.Departure_Date   < CURRENT_DATE"
        ]
        params: List = [agent_id]

        if customer_email:
            conditions.append("T.Customer_Email = %s")
            params.append(customer_email)

        if departure_airport:
            conditions.append("F.Departure_Airport = %s")
            params.append(departure_airport)

        if arrival_airport:
            conditions.append("F.Arrival_Airport = %s")
            params.append(arrival_airport)

        if start:
            conditions.append("F.Departure_Date >= %s")
            params.append(start)

        if end:
            conditions.append("F.Departure_Date <= %s")
            params.append(end)

        sql = f"""
            SELECT F.*, T.Customer_Email
            FROM   Ticket T
            JOIN   Flight F
                   ON T.Airline   = F.Airline
                  AND T.Flight_ID = F.Flight_ID
            WHERE  {' AND '.join(conditions)}
            ORDER  BY F.Departure_Date DESC, F.Departure_Time DESC
        """
        return self._fetchall(sql, tuple(params))

    def purchase_for_customer(
        self, *,
        flight_id: int,
        airline: str,
        customer_email: str,
        agent_id: str,
    ) -> str:
        """
        Agent-mediated purchase (10 % commission credited later).
        Same guards as direct purchase plus duplicate check across *customer*.
        Returns Ticket_ID.
        """
        # duplicate for that customer?
        if self.check_existing_ticket(flight_id, customer_email):
            raise RuntimeError(
                f"{customer_email} already holds a ticket for this flight."
            )

        # still in the future?
        future_ok = self._fetchone(
            f"SELECT 1 FROM Flight WHERE Airline=%s AND Flight_ID=%s AND {self._upcoming_clause("Flight")}",
            (airline, flight_id)
        )
        if not future_ok:
            raise RuntimeError("Cannot sell tickets for flights in the past.")

        # seats left?
        if self._remaining_seats(airline, flight_id) <= 0:
            raise RuntimeError("Flight is sold out.")

        # insert row with agent ID
        return self._insert_ticket_row(
            airline=airline,
            flight_id=flight_id,
            customer_email=customer_email,
            booking_agent_id=agent_id,
        )


    # ––– commission analytics –––
    def commission_last_30_days(self, agent_id: str) -> Dict:
        sql = """
            SELECT
                SUM(F.Price) * 0.10 AS total_comm,
                AVG(F.Price) * 0.10 AS avg_comm,
                COUNT(*) AS tickets
            FROM   Ticket T
            JOIN   Flight F
                   ON F.Airline   = T.Airline
                  AND F.Flight_ID = T.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
              AND  T.Purchase_Date   >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """
        return self._fetchone(sql, (agent_id,))

    def get_commission_tickets(
        self, agent_id: str, start: date, end: date
    ) -> List[Dict]:
        """
        Tickets this agent sold *purchased* between start and end (inclusive).
        Includes Flight price so we can compute commission.
        """
        sql = """
            SELECT F.*, T.Customer_Email, T.Purchase_Date, F.Price
            FROM   Ticket T
            JOIN   Flight F
                ON F.Airline   = T.Airline
                AND F.Flight_ID = T.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
            AND  T.Purchase_Date    BETWEEN %s AND %s
            ORDER  BY T.Purchase_Date
        """
        return self._fetchall(sql, (agent_id, start, end))
    
    def commission_per_day(
        self, agent_id: str, start: date, end: date
    ) -> List[Dict]:
        sql = """
            SELECT DATE(T.Purchase_Date) AS day,
                SUM(F.Price)*0.10     AS commission
            FROM   Ticket T
            JOIN   Flight F
            ON  F.Airline   = T.Airline
            AND F.Flight_ID  = T.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
            AND  T.Purchase_Date BETWEEN %s AND %s
            GROUP  BY day
            ORDER  BY day
        """
        return self._fetchall(sql, (agent_id, start, end))


    # ––– top customers (two different metrics) –––
    def top_customers_by_tickets(self, agent_id: str) -> List[Dict]:
        sql = """
            SELECT T.Customer_Email        AS customer,
                   COUNT(*)                AS tickets
            FROM   Ticket T
            WHERE  T.Booking_Agent_ID = %s
              AND  T.Purchase_Date   >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP  BY customer
            ORDER  BY tickets DESC
            LIMIT  5
        """
        return self._fetchall(sql, (agent_id,))

    def top_customers_by_commission(self, agent_id: str) -> List[Dict]:
        sql = """
            SELECT T.Customer_Email         AS customer,
                   SUM(F.Price)*0.10        AS commission
            FROM   Ticket T
            JOIN   Flight F
                   ON F.Airline   = T.Airline
                  AND F.Flight_ID = T.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
              AND  T.Purchase_Date   >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
            GROUP  BY customer
            ORDER  BY commission DESC
            LIMIT  5
        """
        return self._fetchall(sql, (agent_id,))
    
    def list_agent_departure_airports(self, airlines: list[str]) -> list[str]:
        """
        All DISTINCT departure airports that appear on *upcoming* flights
        operated by ANY airline in <airlines>.
        """
        if not airlines:
            return []                              # agent linked to no airline
        ph = ", ".join(["%s"] * len(airlines))
        sql = f"""
            SELECT DISTINCT Departure_Airport AS ap
            FROM   Flight
            WHERE  Airline IN ({ph})
              AND  Departure_Date >= CURDATE()
            ORDER  BY ap
        """
        return [r["ap"] for r in self._fetchall(sql, tuple(airlines))]

    def list_agent_arrival_airports(self, airlines: list[str]) -> list[str]:
        if not airlines:
            return []
        ph = ", ".join(["%s"] * len(airlines))
        sql = f"""
            SELECT DISTINCT Arrival_Airport AS ap
            FROM   Flight
            WHERE  Airline IN ({ph})
              AND  Departure_Date >= CURDATE()
            ORDER  BY ap
        """
        return [r["ap"] for r in self._fetchall(sql, tuple(airlines))]
    
    def list_agent_flights(self, agent_id: str) -> List[Dict]:
        """
        All distinct Flight_ID values the booking agent has tickets for.
        Used to populate the “Flight #” dropdown.
        """
        sql = """
            SELECT DISTINCT F.Flight_ID
            FROM   Ticket T
            JOIN   Flight F
                   ON F.Airline   = T.Airline
                  AND F.Flight_ID = T.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
            ORDER  BY F.Flight_ID
        """
        return self._fetchall(sql, (agent_id,))
    
    def monthly_commission_totals(self, agent_id: str):
        sql = """
            SELECT DATE_FORMAT(T.Purchase_Date,'%Y-%m') AS month,
                SUM(F.Price)*0.10                    AS commission
            FROM   Ticket T
            JOIN   Flight F
            ON  F.Airline   = T.Airline
            AND  F.Flight_ID = T.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
            AND  T.Purchase_Date   >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            GROUP  BY month
            ORDER  BY month
        """
        return self._fetchall(sql, (agent_id,))

    def list_agent_customers(self, agent_id: str) -> list[str]:
        """Distinct customer e-mails this agent has ever served."""
        rows = self._fetchall(
            "SELECT DISTINCT Customer_Email FROM Ticket WHERE Booking_Agent_ID=%s",
            (agent_id,)
        )
        return [r["Customer_Email"] for r in rows]

    def airport_city(self, code: str) -> str:
        """
        Translate an IATA airport code (stored in Flight.Departure_Airport /
        Arrival_Airport) into its city. Falls back to the code itself if the
        airport is missing from the table.
        """
        row = self._fetchone(
            "SELECT City FROM Airport WHERE Name = %s",
            (code,)
        )
        return row["City"] if row else code




# ─────────────────────────── airline_staff.py ─────────────────────────
class AirlineStaffDB(AbstractUserDB):
    """Everything an airline-staff account can do (Admin / Operator gates enforced in code)."""

    # ––– user + permission info –––
    def profile(self, username: str) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM Airline_Staff WHERE Username = %s",
            (username,)
        )

    def permissions(self, username: str) -> List[str]:
        rows = self._fetchall(
            "SELECT Role as Permission FROM Airline_Staff WHERE Username = %s",
            (username,)
        )
        return [r["Permission"] for r in rows]
    
    def get_departure_airports(self, airline_name):
        # SQL query to get unique departure airports for the airline
        query = """
        SELECT DISTINCT Departure_Airport
        FROM Flight
        WHERE Airline = %s
        """
        result = self._execute_query(query, (airline_name,))
        return [row['Departure_Airport'] for row in result]
    
    def get_arrival_airports(self, airline_name):
    # SQL query to get unique arrival airports for the airline
        query = """
        SELECT DISTINCT Arrival_Airport
        FROM Flight
        WHERE Airline = %s
        """
        result = self._execute_query(query, (airline_name,))
        return [row['Arrival_Airport'] for row in result]

    # ––– flights –––
    def get_upcoming_flights(
            self, 
            airline: str,
            next_days: int = 30
    ) -> List[Dict]:
        sql = f"""
            SELECT *
            FROM   Flight
            WHERE  Airline = %s
            AND  {self._upcoming_clause()}
            AND  Departure_Date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
            ORDER  BY Departure_Date, Departure_Time
        """
        return self._fetchall(sql, (airline, next_days))


    def get_past_flights(self, airline: str,
                         start: Optional[date] = None,
                         end:   Optional[date] = None) -> List[Dict]:
        sql = """
            SELECT *
            FROM   Flight
            WHERE  Airline = %s
              AND  Departure_Date < CURDATE()
              {sf} {ef}
        """
        sf = "AND Departure_Date >= %s" if start else ""
        ef = "AND Departure_Date <= %s" if end   else ""
        return self._fetchall(
            sql.format(sf=sf, ef=ef),
            tuple(x for x in (airline, start, end) if x)
        )

    def passengers_of_flight(self, airline: str, flight_id: int) -> List[str]:
        sql = """
            SELECT Customer_Email
            FROM   Ticket
            WHERE  Airline   = %s
              AND  Flight_ID = %s
        """
        rows = self._fetchall(sql, (airline, flight_id))
        return [r["Customer_Email"] for r in rows]

    # ––– create / update entities (Admin / Operator gated) –––
    def create_flight(self, **flight_attrs) -> None:
        """
        Insert a new row into Flight.

        Parameters
        ----------
        **flight_attrs : column=value pairs that describe the flight.
                         Only columns listed in _ALLOWED_FLIGHT_COLS
                         are accepted.
        Raises
        ------
        ValueError if an unknown column is supplied or if the
        call contains no attributes.
        """
        if not flight_attrs:
            raise ValueError("create_flight() called with no attributes.")

        # — 1.  whitelist check —
        illegal_cols = set(flight_attrs) - self._ALLOWED_FLIGHT_COLS
        if illegal_cols:
            raise ValueError(f"Unknown column(s): {', '.join(illegal_cols)}")

        # — 2.  build statement —
        # Keep deterministic order to avoid test flakiness.
        ordered_items = [(k, flight_attrs[k])
                         for k in sorted(flight_attrs.keys())]

        cols = ", ".join(k for k, _ in ordered_items)
        ph   = ", ".join(["%s"] * len(ordered_items))
        sql  = f"INSERT INTO Flight ({cols}) VALUES ({ph})"

        # — 3.  execute with bound parameters —
        self._execute_query(sql, tuple(v for _, v in ordered_items))


    def update_flight_status(self, airline: str,
                             flight_id: int, new_status: str) -> None:
        self._execute_query(
            """
            UPDATE Flight
            SET    Status_ = %s
            WHERE  Airline   = %s
              AND  Flight_ID = %s
            """,
            (new_status, airline, flight_id)
        )

    def add_airplane(self, airline: str,
                     plane_id: int, seats: int) -> None:
        self._execute_query(
            """
            INSERT INTO Airplane (Airline, Airplane_ID, Number_Seats)
            VALUES (%s, %s, %s)
            """,
            (airline, plane_id, seats)
        )

    def add_airport(self, name: str, city: str) -> None:
        self._execute_query(
            "INSERT INTO Airport (Name, City) VALUES (%s, %s)",
            (name, city)
        )

    # ––– analytics –––
    def tickets_sold_report(self, airline: str,
                            start: date, end: date) -> List[Dict]:
        sql = """
            SELECT DATE_FORMAT(Purchase_Date,'%%Y-%%m') AS yr_mon,
                   COUNT(*)                             AS tickets
            FROM   Ticket
            WHERE  Airline = %s
              AND  Purchase_Date BETWEEN %s AND %s
            GROUP  BY yr_mon
            ORDER  BY yr_mon
        """
        return self._fetchall(sql, (airline, start, end))

    def revenue_split(self, airline: str,
                      period: str = 'month') -> Dict:
        assert period in ('month', 'year')
        window = "1 MONTH" if period == 'month' else "1 YEAR"
        sql = f"""
            SELECT
              SUM(CASE WHEN Booking_Agent_ID IS NULL THEN F.Price ELSE 0 END) AS direct,
              SUM(CASE WHEN Booking_Agent_ID IS NOT NULL THEN F.Price ELSE 0 END) AS indirect
            FROM   Ticket T
            JOIN   Flight F
                   ON F.Airline   = T.Airline
                  AND F.Flight_ID = T.Flight_ID
            WHERE  T.Airline       = %s
              AND  T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL {window})
        """
        return self._fetchone(sql, (airline,))

    def top_destinations(self, airline: str,
                         period: str = '3m') -> List[Dict]:
        win = {"3m": "3 MONTH", "1y": "1 YEAR"}[period]
        sql = f"""
            SELECT Arrival_Airport        AS airport,
                   COUNT(*)               AS flights
            FROM   Flight
            WHERE  Airline      = %s
              AND  Departure_Date >= DATE_SUB(CURDATE(), INTERVAL {win})
            GROUP  BY airport
            ORDER  BY flights DESC
            LIMIT  3
        """
        return self._fetchall(sql, (airline,))

    def top_booking_agents(self, airline: str,
                           metric: str = 'tickets',
                           period: str = 'month') -> List[Dict]:
        """
        metric = 'tickets' | 'commission'
        period = 'month' | 'year'
        """
        window = "1 MONTH" if period == 'month' else "1 YEAR"
        select = "COUNT(*)" if metric == 'tickets' else "SUM(F.Price)*0.10"
        col    = "tickets"  if metric == 'tickets' else "commission"
        sql = f"""
            SELECT Booking_Agent_ID AS agent,
                   {select}         AS {col}
            FROM   Ticket T
            JOIN   Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE  T.Airline = %s
              AND  T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL {window})
              AND  Booking_Agent_ID IS NOT NULL
            GROUP  BY agent
            ORDER  BY {col} DESC
            LIMIT  5
        """
        return self._fetchall(sql, (airline,))

    def frequent_customer_last_year(self, airline: str) -> Optional[Dict]:
        sql = """
            SELECT Customer_Email, COUNT(*) AS flights
            FROM   Ticket
            WHERE  Airline = %s
              AND  Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
            GROUP  BY Customer_Email
            ORDER  BY flights DESC
            LIMIT 1
        """
        return self._fetchone(sql, (airline,))

    def flights_of_customer(self, airline: str,
                            customer_email: str) -> List[Dict]:
        sql = """
            SELECT F.*
            FROM   Ticket T
            JOIN   Flight F
                   ON F.Airline   = T.Airline
                  AND F.Flight_ID = T.Flight_ID
            WHERE  T.Airline        = %s
              AND  T.Customer_Email = %s
        """
        return self._fetchall(sql, (airline, customer_email))

    # ––– permission + agent admin –––
    def grant_permission(self, username: str, perm: str) -> None:
        self._execute_query(
            """
            INSERT IGNORE INTO Staff_Permissions (Username, Permission)
            VALUES (%s, %s)
            """,
            (username, perm)
        )

    def add_booking_agent_to_airline(self, agent_email: str,
                                     airline: str) -> None:
        self._execute_query(
            """
            INSERT IGNORE INTO Work_For (Booking_Agent_ID, Airline)
            VALUES (%s, %s)
            """,
            (agent_email, airline)
        )

    def flight_status_counts(
        self,
        airline: str,
        *,
        start: date | None = None,
        end:   date | None = None,
    ) -> Dict[str, int]:
        """
        Return {'on_time_cnt': N, 'delayed_cnt': M}.
        If no dates are supplied we look at the last 30 days.
        """
        if start is None and end is None:
            start = date.today() - timedelta(days=30)

        sql = """
            SELECT
              SUM(CASE WHEN Status_ = 'On-time' THEN 1 ELSE 0 END) AS on_time_cnt,
              SUM(CASE WHEN Status_ = 'Delayed' THEN 1 ELSE 0 END) AS delayed_cnt
            FROM Flight
            WHERE Airline = %s
              AND Departure_Date >= %s
              {end_clause}
        """
        end_clause = "AND Departure_Date <= %s" if end else ""
        full_sql   = sql.format(end_clause=end_clause)
        params     = (airline, start) + ((end,) if end else ())

        return self._fetchone(full_sql, params)
    
    def update_flight_status(self, airline: str, flight_id: str, new_status: str):
        sql = """
            UPDATE Flight 
            SET Status_ = %s 
            WHERE Airline = %s AND Flight_ID = %s
        """
        self._execute_query(sql, (new_status, airline, flight_id))

    def get_flight_status_distribution(self,
                                    airline: str,
                                    start: date | None,
                                    end:   date | None) -> list[dict]:
        """
        Returns list like [{'Status_':'Upcoming','count':12}, …]

        • If *start* or *end* is None, the bound is left open.
        • Uses >= start  AND  <= end  (inclusive).
        """
        sql  = """
            SELECT  Status_,
                    COUNT(*) AS count
            FROM    Flight
            WHERE   Airline = %s
        """
        params: list[Any] = [airline]

        if start:
            sql += " AND Departure_Date >= %s"
            params.append(start)
        if end:
            sql += " AND Departure_Date <= %s"
            params.append(end)

        sql += " GROUP BY Status_ ORDER BY Status_"
        return [dict(r) for r in self._fetchall(sql, params)]          # list of dict-rows

    
    def get_daily_flights_count(self,
                            airline: str,
                            start: date | None,
                            end:   date | None) -> list[dict]:
        """
        Returns list like [{'Departure_Date':date(2025,5,3),'flight_count':2}, …]
        If *start* / *end* is None the bound is ignored.
        """
        sql  = """
            SELECT  Departure_Date,
                    COUNT(*) AS flight_count
            FROM    Flight
            WHERE   Airline = %s
        """
        params: list[Any] = [airline]

        if start:
            sql += " AND Departure_Date >= %s"
            params.append(start)
        if end:
            sql += " AND Departure_Date <= %s"
            params.append(end)

        sql += " GROUP BY Departure_Date ORDER BY Departure_Date"
        return [dict(r) for r in self._fetchall(sql, params)]

    def flight_status_monthly(
        self, airline: str, start: date, end: date
    ) -> list[dict]:
        """
        Row → {'yr_mon':'2025-05',
            'upcoming_cnt':3, 'arrived_cnt':12,
            'delayed_cnt':1,  'cancelled_cnt':0}
        """
        sql = """
            SELECT  DATE_FORMAT(Departure_Date,'%Y-%m')                  AS yr_mon,
                    SUM(Status_='Upcoming')                             AS upcoming_cnt,
                    SUM(Status_='Arrived')                              AS arrived_cnt,
                    SUM(Status_='Delayed')                              AS delayed_cnt,
                    SUM(Status_='Cancelled')                            AS cancelled_cnt
            FROM    Flight
            WHERE   Airline = %s
            AND   Departure_Date BETWEEN %s AND %s
            GROUP   BY yr_mon
            ORDER   BY yr_mon
        """
        #  MariaDB: SUM(bool) returns BIGINT, MySQL: BIGINT/DECIMAL → cast later
        rows = self._fetchall(sql, (airline, start, end))
        return [dict(r) for r in rows]



    # ---------- revenue by destination (pie / bar) -----------------
    def revenue_by_destination(self, airline: str,
                               start: date, end: date,
                               limit: int = 10) -> list[dict]:
        sql = """
            SELECT  F.Arrival_Airport AS airport,
                    SUM(F.Price)      AS revenue
            FROM    Ticket T
            JOIN    Flight F ON F.Airline=T.Airline
                            AND F.Flight_ID=T.Flight_ID
            WHERE   T.Airline=%s
              AND   T.Purchase_Date BETWEEN %s AND %s
            GROUP   BY airport
            ORDER   BY revenue DESC
            LIMIT   %s;
        """
        return [dict(r) for r in self._fetchall(sql, (airline, start, end, limit))]


    # ────────────────────────────────────────────────────────────────
    #  revenue split by destination (pie / bar)
    # ────────────────────────────────────────────────────────────────
    def revenue_by_destination(
        self, airline: str, start: date, end: date, limit: int = 10
    ) -> list[dict]:
        """
        Returns the *top-N* destinations with their gross revenue (direct + indirect).
        → [{'airport':'JFK','revenue':12800.0}, …]
        """
        sql = """
            SELECT  F.Arrival_Airport AS airport,
                    SUM(F.Price)      AS revenue
            FROM    Ticket  T
            JOIN    Flight   F ON F.Airline   = T.Airline
                               AND F.Flight_ID = T.Flight_ID
            WHERE   T.Airline       = %s
              AND   T.Purchase_Date BETWEEN %s AND %s
            GROUP   BY airport
            ORDER   BY revenue DESC
            LIMIT  %s
        """
        rows = self._fetchall(sql, (airline, start, end, limit))
        return [dict(r) for r in rows]

    def get_flights(
        self,
        airline: str,
        start: date | None,
        end:   date | None
    ) -> list[dict]:
        """
        Return **all** flights for this airline between start and end (inclusive).
        If start or end is None the bound is left open.
        Always returns a Python list of dicts – never a generator.
        """
        sql = """
            SELECT  Flight_ID, Airline,
                    Departure_Airport, Departure_Date, Departure_Time,
                    Arrival_Airport,   Arrival_Date,   Arrival_Time,
                    Status_, Price
            FROM    Flight
            WHERE   Airline = %s
            AND   (%s IS NULL OR Departure_Date >= %s)
            AND   (%s IS NULL OR Departure_Date <= %s)
            ORDER BY Departure_Date, Departure_Time
        """
        # pass start/end twice because of the IS NULL checks
        rows = self._fetchall(sql, (airline, start, start, end, end))  # use your own DB wrapper
        return [dict(row) for row in rows]          
    

    def sales_summary(
        self, airline: str, start: date, end: date
    ) -> Dict[str, Any]:
        """
        One-row snapshot for the “summary cards” (total revenue / tickets).

        Returns
        -------
        {
          'direct_rev'  : 12800.00,
          'agent_rev'   :  6200.00,
          'direct_tix'  :   180,
          'agent_tix'   :    55,
          'total_rev'   : 19000.00,
          'total_tix'   :   235
        }
        """
        sql = """
            SELECT
                SUM( CASE WHEN T.Booking_Agent_ID IS NULL
                          THEN F.Price ELSE 0 END)                 AS direct_rev,
                SUM( CASE WHEN T.Booking_Agent_ID IS NOT NULL
                          THEN F.Price ELSE 0 END)                 AS agent_rev,
                SUM( CASE WHEN T.Booking_Agent_ID IS NULL
                          THEN 1 ELSE 0 END)                       AS direct_tix,
                SUM( CASE WHEN T.Booking_Agent_ID IS NOT NULL
                          THEN 1 ELSE 0 END)                       AS agent_tix
            FROM   Ticket  T
            JOIN   Flight  F ON F.Airline = T.Airline
                           AND F.Flight_ID = T.Flight_ID
            WHERE  T.Airline       = %s
              AND  T.Purchase_Date BETWEEN %s AND %s
        """
        row = self._fetchone(sql, (airline, start, end))
        row["total_rev"] = (row["direct_rev"] or 0) + (row["agent_rev"] or 0)
        row["total_tix"] = (row["direct_tix"] or 0) + (row["agent_tix"] or 0)
        return row

    def tickets_per_month(
        self, airline: str, start: date, end: date
    ) -> List[Dict[str, Any]]:
        """
        Bar-chart data: **counts** of tickets per month split direct/agent.

        [{ 'yr_mon':'2025-04', 'direct':30, 'agent':7 }, …]
        """
        sql = """
            SELECT DATE_FORMAT(T.Purchase_Date,'%Y-%m')                         AS yr_mon,
                   SUM(CASE WHEN T.Booking_Agent_ID IS NULL THEN 1 ELSE 0 END) AS direct,
                   SUM(CASE WHEN T.Booking_Agent_ID IS NOT NULL THEN 1 ELSE 0 END) AS agent
            FROM   Ticket  T
            WHERE  T.Airline       = %s
              AND  T.Purchase_Date BETWEEN %s AND %s
            GROUP  BY yr_mon
            ORDER  BY yr_mon
        """
        return self._fetchall(sql, (airline, start, end))

    def revenue_per_month(
        self, airline: str, start: date, end: date
    ) -> List[Dict[str, Any]]:
        """
        Bar-chart data: **revenue** per month split direct/agent.

        [{ 'yr_mon':'2025-04', 'direct_rev':8200.0, 'agent_rev':1900.0 }, …]
        """
        sql = """
            SELECT DATE_FORMAT(T.Purchase_Date,'%Y-%m')                            AS yr_mon,
                   SUM(CASE WHEN T.Booking_Agent_ID IS NULL
                            THEN F.Price ELSE 0 END)                              AS direct_rev,
                   SUM(CASE WHEN T.Booking_Agent_ID IS NOT NULL
                            THEN F.Price ELSE 0 END)                              AS agent_rev
            FROM   Ticket  T
            JOIN   Flight  F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE  T.Airline       = %s
              AND  T.Purchase_Date BETWEEN %s AND %s
            GROUP  BY yr_mon
            ORDER  BY yr_mon
        """
        return self._fetchall(sql, (airline, start, end))

    # ──────────────────────── 9 · REVENUE COMPARISON ────────────────────
    #   • revenue per destination (direct / agent split)
    # --------------------------------------------------------------------
    def revenue_by_destination_split(
        self, airline: str, start: date, end: date, limit: int = 10
    ) -> list[dict]:
        """
        Top-N destinations with direct / agent revenue split.
        [{airport, direct_rev, agent_rev}, …]
        """
        sql = """
            SELECT  F.Arrival_Airport AS airport,
                    SUM(CASE WHEN T.Booking_Agent_ID IS NULL
                            THEN F.Price ELSE 0 END) AS direct_rev,
                    SUM(CASE WHEN T.Booking_Agent_ID IS NOT NULL
                            THEN F.Price ELSE 0 END) AS agent_rev
            FROM    Ticket T
            JOIN    Flight F ON F.Airline   = T.Airline
                            AND F.Flight_ID = T.Flight_ID
            WHERE   T.Airline       = %s
            AND   T.Purchase_Date BETWEEN %s AND %s
            GROUP   BY airport
            /* total revenue = SUM(F.Price) so we sort by that */
            ORDER   BY SUM(F.Price) DESC
            LIMIT   %s
        """
        return self._fetchall(sql, (airline, start, end, limit))
    
    
    def top_customers_monthly(
        self, airline: str, start: date, end: date, limit: int = 3
    ) -> list[dict]:
        """
        Returns rows like
            {'yr_mon':'2025-04','customer':'alice@example.com','flights':5}
        for the *top-N* customers with most flights in [start, end].
        """
        sql = f"""
            WITH top_cust AS (
                SELECT Customer_Email
                FROM   Ticket
                WHERE  Airline = %s
                  AND  Purchase_Date BETWEEN %s AND %s
                GROUP  BY Customer_Email
                ORDER  BY COUNT(*) DESC
                LIMIT  {limit}
            )
            SELECT DATE_FORMAT(Purchase_Date,'%Y-%m') AS yr_mon,
                   Customer_Email                     AS customer,
                   COUNT(*)                          AS flights
            FROM   Ticket
            JOIN   top_cust USING (Customer_Email)
            WHERE  Airline = %s
              AND  Purchase_Date BETWEEN %s AND %s
            GROUP  BY yr_mon, customer
            ORDER  BY yr_mon, customer
        """
        return [dict(r) for r in self._fetchall(sql,
                 (airline, start, end, airline, start, end))]

    # -----------------------------------------------------------------
    #  scheduled flights (next 2 months) grouped by destination
    # -----------------------------------------------------------------
    def flights_next_two_months_by_destination(
        self, airline: str
    ) -> list[dict]:
        """
        [{'airport':'JFK','cnt':12}, …]   for flights departing in the
        next 2 months (inclusive of today).
        """
        sql = """
            SELECT Arrival_Airport AS airport,
                   COUNT(*)        AS cnt
            FROM   Flight
            WHERE  Airline = %s
              AND  Departure_Date BETWEEN CURDATE()
                                       AND DATE_ADD(CURDATE(), INTERVAL 2 MONTH)
            GROUP  BY airport
            ORDER  BY cnt DESC
        """
        return [dict(r) for r in self._fetchall(sql, (airline,))]


    # ─────────────────────── 10 · TOP DESTINATIONS ──────────────────────
    #   • re-use revenue_by_destination_split(limit=3) for 3 month / 12 month
    # --------------------------------------------------------------------
    def top_destinations_split(
        self, airline: str, period: str = "3m"
    ) -> List[Dict[str, Any]]:
        """
        Convenience wrapper – *period* = "3m" | "1y"
        """
        delta = {"3m": 90, "1y": 365}[period]
        end   = date.today()
        start = end - timedelta(days=delta)
        return self.revenue_by_destination_split(airline, start, end, limit=3)
    
    def list_booking_agents_not_working_for_airline(self, airline: str) -> list[dict]:
        """
        Returns all booking agents not currently working for this airline.
        Used by admins to add new booking agents to their airline.
        """
        sql = """
            SELECT BA.Booking_Agent_ID, BA.Email,
                (SELECT GROUP_CONCAT(Airline SEPARATOR ', ')
                    FROM Work_For
                    WHERE Booking_Agent_ID = BA.Booking_Agent_ID) AS Current_Airlines
            FROM Booking_Agent BA
            WHERE BA.Booking_Agent_ID NOT IN (
                SELECT Booking_Agent_ID
                FROM Work_For
                WHERE Airline = %s
            )
            ORDER BY BA.Booking_Agent_ID
        """
        return self._fetchall(sql, (airline,))

    # Note: There's already an add_booking_agent_to_airline method in your codebase,
    # so we won't redefine it here.

    def list_all_airline_staff(self, airline: str) -> list[dict]:
        """
        Returns all staff members for the given airline with their current roles.
        Used for permission management by admins.
        """
        sql = """
            SELECT Username, First_Name, Last_Name, Role AS Permission
            FROM Airline_Staff
            WHERE Airline = %s
            ORDER BY Username
        """
        return self._fetchall(sql, (airline,))

    def update_staff_permission(self, username: str, role: str) -> None:
        """
        Updates the permission role for a staff member.
        Only allowed for staff with Admin permission.
        """
        sql = """
            UPDATE Airline_Staff
            SET Role = %s
            WHERE Username = %s
        """
        self._execute_query(sql, (role, username))

    def top_booking_agents_comprehensive(self, airline: str, period: str = 'month') -> dict:
        """
        Returns comprehensive data about top booking agents for the airline.
        
        Parameters:
        period - 'month' or 'year'
        
        Returns a dictionary with:
        - 'by_tickets': top agents by tickets sold
        - 'by_commission': top agents by commission
        - 'agent_sales_distribution': distribution of sales across all agents
        - 'monthly_sales': monthly sales data for each agent
        """
        # Define the time window based on period
        window = "1 MONTH" if period == 'month' else "1 YEAR"
        
        # Top agents by tickets
        tickets_sql = f"""
            SELECT 
                BA.Booking_Agent_ID AS agent_id,
                BA.Email AS agent_email,
                COUNT(*) AS tickets_sold
            FROM Ticket T
            JOIN Booking_Agent BA ON T.Booking_Agent_ID = BA.Booking_Agent_ID
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL {window})
            AND T.Booking_Agent_ID IS NOT NULL
            GROUP BY agent_id, agent_email
            ORDER BY tickets_sold DESC
            LIMIT 5
        """
        top_by_tickets = self._fetchall(tickets_sql, (airline,))
        
        # Top agents by commission
        commission_sql = f"""
            SELECT 
                BA.Booking_Agent_ID AS agent_id,
                BA.Email AS agent_email,
                SUM(F.Price) * 0.10 AS commission
            FROM Ticket T
            JOIN Booking_Agent BA ON T.Booking_Agent_ID = BA.Booking_Agent_ID
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL {window})
            AND T.Booking_Agent_ID IS NOT NULL
            GROUP BY agent_id, agent_email
            ORDER BY commission DESC
            LIMIT 5
        """
        top_by_commission = self._fetchall(commission_sql, (airline,))
        
        # Distribution of sales across all agents (for pie chart)
        distribution_sql = f"""
            SELECT 
                BA.Booking_Agent_ID AS agent_id,
                BA.Email AS agent_email,
                COUNT(*) AS tickets_sold
            FROM Ticket T
            JOIN Booking_Agent BA ON T.Booking_Agent_ID = BA.Booking_Agent_ID
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL {window})
            GROUP BY agent_id, agent_email
            ORDER BY tickets_sold DESC
        """
        sales_distribution = self._fetchall(distribution_sql, (airline,))
        
        # Monthly sales for each agent (for line chart)
        monthly_sql = f"""
            SELECT 
                BA.Booking_Agent_ID AS agent_id,
                DATE_FORMAT(T.Purchase_Date, '%Y-%m') AS month,
                COUNT(*) AS tickets_sold
            FROM Ticket T
            JOIN Booking_Agent BA ON T.Booking_Agent_ID = BA.Booking_Agent_ID
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL {window})
            GROUP BY agent_id, month
            ORDER BY agent_id, month
        """
        monthly_sales = self._fetchall(monthly_sql, (airline,))
        
        return {
            'by_tickets': top_by_tickets,
            'by_commission': top_by_commission,
            'agent_sales_distribution': sales_distribution,
            'monthly_sales': monthly_sales
        }

    def bottom_booking_agents(self, airline: str, period: str = 'month') -> list[dict]:
        """
        Returns the bottom 5 booking agents based on tickets sold.
        Only considers agents that work for this airline.
        """
        window = "1 MONTH" if period == 'month' else "1 YEAR"
        
        sql = f"""
            SELECT 
                BA.Booking_Agent_ID AS agent_id,
                BA.Email AS agent_email,
                COUNT(*) AS tickets_sold
            FROM Booking_Agent BA
            JOIN Work_For WF ON WF.Booking_Agent_ID = BA.Booking_Agent_ID
            LEFT JOIN Ticket T ON T.Booking_Agent_ID = BA.Booking_Agent_ID 
                            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL {window})
            WHERE WF.Airline = %s
            GROUP BY agent_id, agent_email
            ORDER BY tickets_sold ASC
            LIMIT 5
        """
        return self._fetchall(sql, (airline,))