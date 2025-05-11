from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Optional, Sequence, Any
from datetime import date, datetime, timedelta
from .Database_Manager_abstract import AbstractDatabaseService
import random

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
        allowed_airlines: Optional[Sequence[str]] = None,
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
                  AND T.Flight_ID = T.Flight_ID
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
            f"SELECT 1 FROM Flight WHERE Airline=%s AND Flight_ID=%s AND {self._upcoming_clause('Flight')}",
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
    
    def get_departure_airports(self) -> list[str]:
        """
        Return every airport code that appears as a departure airport
        on flights that haven't taken off yet (today or later).
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
        on flights that haven't taken off yet (today or later).
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
        """
        Get all upcoming flights that were booked by this agent.
        These are tickets where Booking_Agent_ID = agent_id and the flight is in the future.
        
        Parameters
        ----------
        agent_id : str
            The booking agent ID to filter tickets by.
            
        Returns
        -------
        List[Dict]
            List of flight dictionaries with Customer_Email added from the Ticket table.
        """
        sql = f"""
            SELECT F.*, T.Customer_Email
            FROM   Ticket T
            JOIN   Flight F ON T.Airline = F.Airline AND T.Flight_ID = F.Flight_ID
            WHERE  T.Booking_Agent_ID = %s
            AND  {self._upcoming_clause("F")}
            ORDER  BY F.Departure_Date, F.Departure_Time
        """
        return self._fetchall(sql, (agent_id,))


    def get_past_flights(
        self,
        agent_id: str,
        customer_email: Optional[str] = None,
        departure_airport: Optional[str] = None,
        arrival_airport: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> List[Dict]:
        """
        Past flights sold by this booking-agent, optionally filtered by
        customer, date range, and/or departure/arrival airport.
        """
        conditions = [
            "T.Booking_Agent_ID = %s",
            "F.Departure_Date < CURRENT_DATE"
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
            f"SELECT 1 FROM Flight WHERE Airline=%s AND Flight_ID=%s AND {self._upcoming_clause('Flight')}",
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
    
    def get_airports_with_cities(self) -> List[Dict[str, str]]:
        sql = """
            SELECT Name as code, City as city
            FROM Airport
            ORDER BY City, Name
        """
        return self._fetchall(sql)


    def permissions(self, username: str) -> List[str]:
        rows = self._fetchall(
            "SELECT Role as Permission FROM Airline_Staff WHERE Username = %s",
            (username,)
        )
        role = [r["Permission"] for r in rows][0]
        return role if role else "None"
    
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

    def generate_flight_id(self, airline: str) -> str:
        """
        Generate a unique flight ID for the given airline.
        Format: AA123 (2 airline code letters + 3 random digits)
        
        Returns a unique flight ID that doesn't already exist in the database.
        """
        # Get airline code (first 2 letters or whole name if shorter)
        airline_code = airline[:2].upper()
        
        # Keep generating IDs until we find an unused one
        while True:
            # Generate random 3-digit number
            number = random.randint(100, 999)
            flight_id = f"{airline_code}{number}"
            
            # Check if this flight ID already exists
            exists = self._fetchone(
                "SELECT 1 FROM Flight WHERE Airline = %s AND Flight_ID = %s",
                (airline, flight_id)
            )
            
            # If not found, return this unique ID
            if not exists:
                return flight_id
    
    def create_flight(self, **flight_attrs) -> str:
        """
        Insert a new row into Flight with auto-generated Flight_ID.
        
        Uses a direct SQL query with named parameters and validates required fields.
        
        Parameters
        ----------
        **flight_attrs : column=value pairs that describe the flight
        
        Returns
        -------
        str : The generated Flight_ID
        
        Raises
        ------
        ValueError if a required field is missing
        """
        # Required fields check
        required_fields = [
            "Airline", "Airplane_ID", "Departure_Airport", 
            "Departure_Date", "Departure_Time", "Arrival_Airport",
            "Arrival_Date", "Arrival_Time", "Status_", "Price"
        ]
        
        # Check for missing fields
        missing_fields = [field for field in required_fields if field not in flight_attrs]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
        
        # Generate Flight_ID (2 letters of airline + 3 random digits)
        airline = flight_attrs["Airline"]
        flight_id = self.generate_flight_id(airline=airline)
        # Create parameters dictionary with the generated flight_id
        params = {
            "flight_id": flight_id,
            "airline": flight_attrs["Airline"],
            "airplane_id": flight_attrs["Airplane_ID"],
            "departure_airport": flight_attrs["Departure_Airport"],
            "departure_date": flight_attrs["Departure_Date"],
            "departure_time": flight_attrs["Departure_Time"],
            "arrival_airport": flight_attrs["Arrival_Airport"],
            "arrival_date": flight_attrs["Arrival_Date"],
            "arrival_time": flight_attrs["Arrival_Time"],
            "status": flight_attrs["Status_"],
            "price": flight_attrs["Price"]
        }
        
        # Direct SQL query with named parameters
        sql = """
        INSERT INTO Flight (
            Flight_ID, Airline, Airplane_ID, Departure_Airport, 
            Departure_Date, Departure_Time, Arrival_Airport, 
            Arrival_Date, Arrival_Time, Status_, Price
        ) VALUES (
            %(flight_id)s, %(airline)s, %(airplane_id)s, %(departure_airport)s,
            %(departure_date)s, %(departure_time)s, %(arrival_airport)s,
            %(arrival_date)s, %(arrival_time)s, %(status)s, %(price)s
        )
        """
        # Execute the query with a tuple of values
        self._execute_query(sql, params)
        
        # Return the generated flight_id
        return flight_id

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
        One-row snapshot for the "summary cards" (total revenue / tickets).

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

    def add_booking_agent_to_airline(self, agent_id: str, airline: str) -> None:
        self._execute_query(
            """
            INSERT IGNORE INTO Work_For (Booking_Agent_ID, Airline)
            VALUES (%s, %s)
            """,
            (agent_id, airline)
        )

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
    
    def flights_of_customer(self, airline: str, customer_email: str) -> List[Dict]:
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
    
    def top_customers_by_flights(self, airline: str, limit: int = 5) -> List[Dict]:
        """Returns the top N customers by number of flights in the last year."""
        sql = """
            SELECT 
                C.Email AS Customer_Email,
                C.First_Name,
                C.Last_Name,
                COUNT(T.Ticket_ID) AS flights,
                SUM(F.Price) AS total_spent
            FROM Ticket T
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            JOIN Customer C ON C.Email = T.Customer_Email
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
            GROUP BY Customer_Email, C.First_Name, C.Last_Name
            ORDER BY flights DESC
            LIMIT %s
        """
        return self._fetchall(sql, (airline, limit))
    
    def top_customers_by_flights(self, airline: str, limit: int = 5) -> List[Dict]:
        """Returns the top N customers by number of flights in the last year."""
        sql = """
            SELECT 
                C.Email AS Customer_Email,
                C.First_Name,
                C.Last_Name,
                COUNT(T.Ticket_ID) AS flights,
                SUM(F.Price) AS total_spent
            FROM Ticket T
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            JOIN Customer C ON C.Email = T.Customer_Email
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
            GROUP BY Customer_Email, C.First_Name, C.Last_Name
            ORDER BY flights DESC
            LIMIT %s
        """
        return self._fetchall(sql, (airline, limit))

    def customer_destinations(self, airline: str) -> List[Dict]:
        """
        Returns data about the most popular destinations for customers.
        Used for visualization in the dashboard.
        """
        sql = """
            SELECT 
                F.Arrival_Airport AS destination,
                COUNT(DISTINCT T.Customer_Email) AS unique_customers,
                COUNT(*) AS total_flights
            FROM Ticket T
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
            GROUP BY destination
            ORDER BY unique_customers DESC, total_flights DESC
            LIMIT 10
        """
        return self._fetchall(sql, (airline,))

    def monthly_customer_activity(self, airline: str) -> List[Dict]:
        """
        Returns monthly data about customer ticket purchases for trend analysis.
        """
        sql = """
            SELECT 
                DATE_FORMAT(T.Purchase_Date, '%Y-%m') AS month,
                COUNT(DISTINCT T.Customer_Email) AS unique_customers,
                COUNT(*) AS tickets_sold,
                SUM(F.Price) AS revenue
            FROM Ticket T
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
            GROUP BY month
            ORDER BY month
        """
        return self._fetchall(sql, (airline,))

    def revenue_by_customer_category(self, airline: str) -> List[Dict]:
        """
        Categorizes customers by frequency and returns revenue data for each category.
        """
        sql = """
            WITH customer_categories AS (
                SELECT 
                    T.Customer_Email,
                    COUNT(*) AS flight_count,
                    CASE 
                        WHEN COUNT(*) >= 10 THEN 'Frequent'
                        WHEN COUNT(*) >= 5 THEN 'Regular'
                        ELSE 'Occasional'
                    END AS category
                FROM Ticket T
                WHERE T.Airline = %s
                AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
                GROUP BY T.Customer_Email
            )
            SELECT 
                cc.category,
                COUNT(DISTINCT cc.Customer_Email) AS customer_count,
                SUM(F.Price) AS total_revenue,
                AVG(F.Price) AS avg_revenue_per_ticket,
                SUM(F.Price)/COUNT(DISTINCT cc.Customer_Email) AS avg_revenue_per_customer
            FROM customer_categories cc
            JOIN Ticket T ON T.Customer_Email = cc.Customer_Email
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE T.Airline = %s
            AND T.Purchase_Date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
            GROUP BY cc.category
            ORDER BY total_revenue DESC
        """
        return self._fetchall(sql, (airline, airline))

    def get_customer_details(self, email: str) -> Optional[Dict]:
        """
        Retrieves detailed information about a specific customer.
        """
        sql = """
            SELECT 
                Email, First_Name, Last_Name, Phone_Number,
                State, City, Building_Name, Zip_Code,
                Passport_Number, Passport_Country, Passport_Expiration_Date,
                DATE_FORMAT(FROM_DAYS(DATEDIFF(CURRENT_DATE, DoB)), '%Y') + 0 AS age
            FROM Customer
            WHERE Email = %s
        """
        return self._fetchone(sql, (email,))

    def get_customer_flight_stats(self, airline: str, customer_email: str) -> Dict:
        """
        Returns statistics about a customer's flight history with this airline.
        """
        sql = """
            SELECT 
                COUNT(*) AS total_flights,
                SUM(F.Price) AS total_spent,
                AVG(F.Price) AS avg_ticket_price,
                MIN(T.Purchase_Date) AS first_purchase,
                MAX(T.Purchase_Date) AS last_purchase,
                COUNT(DISTINCT F.Arrival_Airport) AS unique_destinations,
                SUM(CASE WHEN T.Booking_Agent_ID IS NOT NULL THEN 1 ELSE 0 END) AS agent_bookings,
                SUM(CASE WHEN T.Booking_Agent_ID IS NULL THEN 1 ELSE 0 END) AS direct_bookings,
                (SELECT COUNT(*) 
                FROM Ticket T2 
                JOIN Flight F2 ON F2.Airline = T2.Airline AND F2.Flight_ID = T2.Flight_ID
                WHERE T2.Customer_Email = T.Customer_Email 
                AND F2.Status_ = 'Cancelled') AS cancelled_flights
            FROM Ticket T
            JOIN Flight F ON F.Airline = T.Airline AND F.Flight_ID = T.Flight_ID
            WHERE T.Airline = %s
            AND T.Customer_Email = %s
            GROUP BY T.Customer_Email
        """
        result = self._fetchone(sql, (airline, customer_email))
        return result if result else {
            'total_flights': 0,
            'total_spent': 0,
            'avg_ticket_price': 0,
            'first_purchase': None,
            'last_purchase': None,
            'unique_destinations': 0,
            'agent_bookings': 0,
            'direct_bookings': 0,
            'cancelled_flights': 0
        }