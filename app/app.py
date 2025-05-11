from flask import (
    Flask, 
    flash,
    render_template, 
    request, 
    redirect,
    url_for, 
    jsonify, 
    session,
    get_flashed_messages
)
from decimal import Decimal
import mysql.connector
import hashlib
from werkzeug.routing import BuildError
import secrets
from functools import wraps
from datetime import date, timedelta, datetime
from werkzeug.exceptions import BadRequest

# back-end Objects
from Backend.Public_db import PublicDatabaseService
from Backend.User_db import (
    CustomerDB,
    BookingAgentDB,
    AirlineStaffDB
)


def _dec2float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, list):
        return [_dec2float(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dec2float(v) for k, v in obj.items()}
    return obj

def md5(s: str) -> str:             # single place = harder to mistype
    return hashlib.md5(s.encode()).hexdigest()

# ──────────────────────────── factory ───────────────────────────
def main() -> None:
    ONE_YEAR = timedelta(days=365)
    app = Flask(__name__, static_url_path="/static")
    app.secret_key = secrets.token_hex(16)

    # --- one instance each ---
    public_db     = PublicDatabaseService()
    customer_db   = CustomerDB()
    agent_db      = BookingAgentDB()
    staff_db      = AirlineStaffDB()

    def _parse_iso(val: str | None) -> date:
        """Convert YYYY-MM-DD → date or raise 400."""
        try:
            return date.fromisoformat(val)
        except (TypeError, ValueError):
            raise BadRequest("Invalid date format")

    @app.context_processor
    def inject_current_year():
        """Add current_year to all template contexts."""
        from datetime import datetime
        return {'current_year': datetime.now().year}

    # ------------------------- template safety ------------------
    @app.context_processor
    def _safe_url():
        def safe_url_for(endpoint, **values):
            try:
                return url_for(endpoint, **values)
            except BuildError:
                return "#"
        return dict(safe_url_for=safe_url_for)
    
    @app.route("/features")
    def features():
        return render_template("features.html")

    # --------------------------- public -------------------------
    @app.route("/", methods=["GET", "POST"])
    def base():
        flights: list[dict] = []
        src = dest = date_str = ""
        limit = int(request.args.get("limit", 15))  # Default to 15 flights, get from query param
        airport_labels = public_db.list_airport_labels()

        if request.method == "POST":
            src = request.form.get("source_city", "").strip()
            dest = request.form.get("destination_city", "").strip()
            date_str = request.form.get("date", "").strip()
            limit = int(request.form.get("limit", 15))  # Get from form if provided

            # if the user picked a label like "Boston-BOS", keep only the code
            if "-" in src:
                src = src.rsplit("-", 1)[1]   # → "BOS"
            if "-" in dest:
                dest = dest.rsplit("-", 1)[1]

            flights = public_db.view_flights(
                source=src or None,
                destination=dest or None,
                on_or_after=(date.fromisoformat(date_str) if date_str else None),
                limit=limit
            )
        else:
            flights = public_db.view_upcoming_flights(limit=limit)

        return render_template(
            "home.html",
            flights=flights,
            airport_labels=airport_labels,
            form_values={"src": src, "dest": dest, "date": date_str, "limit": limit},
        )

    @app.route("/flight_status")
    def flight_status():
        """
        AJAX/JSON endpoint:
            /flight_status?flight_id=...&airline=...&date=YYYY-MM-DD
        """
        fid   = request.args.get("flight_id")
        al    = request.args.get("airline")
        dstr  = request.args.get("date")
        if not (fid and al and dstr):
            return jsonify(error="flight_id, airline and date are required"), 400

        try:
            fdate = date.fromisoformat(dstr)
        except ValueError:
            return jsonify(error="date must be ISO-format YYYY-MM-DD"), 400

        status_row = public_db.flight_status(fid, al, fdate)
        return jsonify(status=status_row)   

    # --------------------------- auth ---------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            role = request.form.get("role")                # customer | agent | staff
            raw_pw = request.form.get("password", "")
            psw = md5(raw_pw)

            # pick the right identifier field based on role
            if role == "staff":
                username = request.form.get("username", "").strip()
            else:                        # customer or agent → email posted
                username = request.form.get("email", "").strip()

            if not (username and raw_pw and role):
                return render_template("login.html", error="All fields are required.")
            user_info = None
            if role == "customer":
                user_info = public_db.authenticate_customer(username)
                uid_key   = "Email"

            elif role == "agent":
                agent_id  = request.form.get("booking_agent_id", "").strip()
                if not agent_id:
                    return render_template("login.html", error="Agent-ID required.")
                user_info = public_db.authenticate_booking_agent(username, agent_id)
                uid_key   = "Booking_Agent_ID"

            elif role == "staff":
                user_info = public_db.authenticate_airline_staff(username)
                uid_key   = "username"

            else:
                return render_template("login.html", error="Unknown role.")
            
            if not user_info:
                return render_template("login.html", error="You are a user, please sign-in")
            
            if user_info.get("Password") == psw:
                session.clear()
                session["role"] = role
                session["user_id"] = user_info[uid_key]
                return redirect(url_for("home"))

            if role == "customer":
                return render_template("login.html", role = role, error="Invalid email / password.")
            if role == "agent":
                return render_template("login.html", role = role, error="Invalid email / booking agent ID / password.")
            if role == "staff":
                return render_template("login.html", role = role, error="Invalid username / password.")

        return render_template("login.html")

    def _clean(value: str | None) -> str | None:
        """Return stripped value or None if blank/None."""
        if value is None:
            return None
        value = value.strip()
        return value or None        
    
    # 1. Backend fix in app.py - Update the signup route with proper validation

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            # Debug the request data
            print("Request form data:", request.form)
            
            role = request.form["role"]
            raw_user = request.form["username"].strip()
            username = raw_user.lower() if role != "staff" else raw_user  # e-mails case-insensitive
            password = request.form["password"]

            # ── 1. pre-flight checks (prevent obvious dupes) ─────────────────
            if role == "customer" and public_db.customer_exists(username):
                flash("This email is already registered.", "danger")
                return redirect(url_for("signup"))           # flashes persist

            if role == "agent":
                if public_db.booking_agent_email_exists(username):
                    flash("Booking-agent email already in use.", "danger")
                    return redirect(url_for("signup"))
                if public_db.booking_agent_id_exists(request.form["booking_agent_id"]):
                    flash("Booking-agent ID already in use.", "danger")
                    return redirect(url_for("signup"))

            if role == "staff" and public_db.staff_exists(username):
                flash("That username is already taken.", "danger")
                return redirect(url_for("signup"))

            # ── 2. attempt insert – catch *any* duplicates that slipped past ──
            try:
                if role == "customer":
                    public_db.create_customer(
                        email=username,
                        password=password,
                        first_name=request.form["first_name"],
                        middle_name=request.form.get("middle_name"),
                        last_name=request.form["last_name"],
                        state=request.form["state"],
                        city=request.form["city"],
                        building_name=request.form["building_name"],
                        zip_code=request.form["zip_code"],
                        phone=request.form["phone"],
                        passport_no=request.form["passport_no"],
                        passport_country=request.form["passport_country"],
                        passport_exp=_clean(request.form.get("passport_exp")),  
                        dob=_clean(request.form.get("dob")),                    
                    )

                elif role == "agent":
                    public_db.create_booking_agent(
                        email=username,
                        password=password,
                        booking_agent_id=request.form["booking_agent_id"].strip(),
                    )

                elif role == "staff":
                    # Handle the duplicate keys issue by getting all values for each key
                    # and choosing the non-empty ones
                    
                    # Get all values for each field
                    first_name_values = request.form.getlist("first_name")
                    last_name_values = request.form.getlist("last_name")
                    middle_name_values = request.form.getlist("middle_name")
                    dob_values = request.form.getlist("dob")
                    airline_name = request.form.get("airline_name", "").strip()
                    
                    # Choose the non-empty values (the last non-empty value)
                    first_name = next((val for val in reversed(first_name_values) if val.strip()), "")
                    last_name = next((val for val in reversed(last_name_values) if val.strip()), "")
                    middle_name = next((val for val in reversed(middle_name_values) if val.strip()), None)
                    dob = next((val for val in reversed(dob_values) if val.strip()), None)
                    
                    # Print debugging info
                    print("Staff signup processed values:")
                    print(f"Username: {username}")
                    print(f"First name: {first_name}")
                    print(f"Last name: {last_name}")
                    print(f"Middle name: {middle_name}")
                    print(f"DoB: {dob}")
                    print(f"Airline: {airline_name}")
                    
                    # Create the staff with the correct values
                    public_db.create_staff(
                        username=username,
                        password=password,
                        first_name=first_name,
                        middle_name=middle_name,
                        last_name=last_name,
                        airline_name=airline_name,
                        dob=dob
                    )

                flash("Account created! You can now log in.", "success")
                return redirect(url_for("login"))
                
            except Exception as e:
                flash(f"Error creating account: {str(e)}", "danger")
                print(f"Error during signup: {str(e)}")
                return redirect(url_for("signup"))

        # GET  → show blank form (flashes, if any, are rendered by template)
        return render_template("signup.html")

    def _iso2date(s: str | None):
            """Return date from YYYY-MM-DD or None (invalid → None)."""
            if not s:
                return None
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except ValueError:
                return None
            
    # -------------------------- homepages -----------------------
    @app.route("/homepage")
    def home():
        role = session.get("role")
        user_id = session.get("user_id")
        if not role or not user_id:
            return redirect(url_for("login"))

        # ------------------------------------------------------------------ #
        # ---------------------------- CUSTOMER ---------------------------- #
        # ------------------------------------------------------------------ #
        if role == "customer":
            profile = customer_db.profile(user_id) or {}
            first_name = profile.get("First_Name", "")
            last_name = profile.get("Last_Name", "")
            flights = customer_db.get_upcoming_flights(user_id)  # ← only tickets
            dep_airports = customer_db.get_departure_airports()
            arr_airports = customer_db.get_arrival_airports()

            return render_template(
                "homepage.html",
                user_type="Customer",
                email=user_id,
                first_name=first_name,
                last_name=last_name,
                upcoming_flights=flights,
                departure_airports=dep_airports,
                arrival_airports=arr_airports,
            )

        # ------------------------------------------------------------------ #
        # ------------------------- BOOKING AGENT -------------------------- #
        # ------------------------------------------------------------------ #
        if role == "agent":
            airlines = agent_db.agent_airlines(user_id)
            
            # Get flights booked by this agent using the fixed method
            flights = agent_db.get_upcoming_flights(user_id)
                        
            # Get available departure and arrival airports for this agent's authorized airlines
            dep_rows = agent_db.list_agent_departure_airports(airlines)
            arr_rows = agent_db.list_agent_arrival_airports(airlines)

            return render_template(
                "homepage.html",
                user_type="Booking Agent",
                email=user_id,
                airline_names=", ".join(airlines) if airlines else "",
                upcoming_flights=flights,
                departure_airports=dep_rows,
                arrival_airports=arr_rows,
            )

        # ------------------------------------------------------------------ #
        # -------------------------- AIRLINE STAFF ------------------------- #
        # ------------------------------------------------------------------ #
        if role == "staff":
            profile = staff_db.profile(user_id)
            if not profile:
                return redirect(url_for("logout"))
            permissions = staff_db.permissions(user_id)
            airline_name = profile["Airline"]

            flights = staff_db.search_upcoming_flights(
                airline_staff_id=user_id,
                role="airline_staff"
            )

            departure_airports = staff_db.get_departure_airports(airline_name)
            arrival_airports = staff_db.get_arrival_airports(airline_name)
            is_operator = "Operator" in permissions

            return render_template(
                "homepage.html",
                user_type="Airline Staff",
                email=user_id,
                first_name=profile["First_Name"],
                last_name=profile["Last_Name"],
                airline_name=airline_name,
                permissions=permissions,
                is_operator=is_operator,
                upcoming_flights=flights,
                departure_airports=departure_airports,
                arrival_airports=arrival_airports,
            )

        # unknown role
        return redirect(url_for("logout"))
    
    def _require_customer():
        """
        This function checks if the user is logged in as a customer.
        If not, it redirects to the login page.
        """
        if 'user_id' not in session or session.get('role') != 'customer':
            return redirect(url_for('login'))  # Redirect to login page
        return None  
    
    def require_customer(f):
        """
        Decorator to ensure the user is logged in as a customer.
        If not, redirect them to the login page.
        """
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:  # Check if user_id exists in the session
                return redirect(url_for("login"))  # Redirect to the login page if not logged in
            return f(*args, **kwargs)  # Proceed with the route if logged in as a customer

        return decorated_function
   
    # ---- 1. Search flights & purchase -----------------------------------
    @app.route("/customer/search", methods=["GET", "POST"])
    @require_customer
    def customer_flight_search():
        """Show *available* upcoming flights that match the filters."""
        if session.get("role") != "customer":
            return redirect(url_for("home"))

        # ── read query parameters ─────────────────────────────────────────
        on_date = request.args.get("start_date") or None  # we only use one date
        source  = request.args.get("source") or None
        dest    = request.args.get("destination") or None

        # convert to date obj if present
        if on_date:
            try:
                from datetime import datetime
                on_date = datetime.strptime(on_date, "%Y-%m-%d").date()
            except ValueError:
                on_date = None

        # ── run the search WITHOUT customer_email filter! ────────────────
        flights = customer_db.search_upcoming_flights(
            source      = source,
            destination = dest,
            on_date     = on_date,
            role        = "customer",      # optional in your SQL, still fine
            # ⇐ no customer_email here
        )

        dep_airports = customer_db.get_departure_airports()
        arr_airports = customer_db.get_arrival_airports()

        return render_template(
            "customer_search.html",
            flights = flights,
            departure_airports = dep_airports,
            arrival_airports  = arr_airports,
        )




    @app.route("/customer/purchase/<airline>/<flight_id>", methods=["POST"])
    def customer_purchase(airline: str, flight_id: int):
        """
        Buy a ticket for the logged-in customer, then go back to /homepage.
        """
        guard = _require_customer()           # your current session check
        if guard:
            return guard                      # not logged-in -> redirect to login

        email = session["user_id"]

        try:
            ticket_id = customer_db.purchase_ticket(
                flight_id=flight_id,
                airline=airline,
                customer_email=email,
            )
            flash(f"Ticket purchased successfully! Your ticket ID is {ticket_id}",
                "success")

        except RuntimeError as err:
            flash(str(err), "danger")         # seats sold out, duplicate, etc.

        # Always let /homepage rebuild the dashboard with fresh data.
        return redirect(url_for("home"))



    # ---- 2. View past flights -------------------------------------------
    @app.route("/customer/past_flights", methods=["GET", "POST"])
    @require_customer
    def customer_past_flights():
        email = session["user_id"]
        dep_used, arr_used = customer_db.airports_used(email)   # Fetch used airports

        # defaults = last 6 months
        end   = date.today()
        start = end - timedelta(days=180)
        city  = ""

        if request.method == "POST":
            start = date.fromisoformat(request.form["start"])
            end   = date.fromisoformat(request.form["end"])
            city  = request.form.get("city", "").strip()

        # Get the past tickets for this customer
        rows = customer_db.past_tickets(email, start, end)

        if city:
            c = city.lower()
            rows = [r for r in rows if c in (
                r["Departure_Airport"].lower(), r["Arrival_Airport"].lower(),
                r.get("Departure_City", "").lower(), r.get("Arrival_City", "").lower())]

        # 1. Pie chart data (spend by airline)
        spend_air = {}
        for r in rows:
            spend_air[r["Airline"]] = spend_air.get(r["Airline"], 0) + float(r["Price"])
        
        pie_labels = list(spend_air.keys())
        pie_values = list(spend_air.values())

        # 2. Bar chart data (spend per month)
        m_rows = customer_db.spend_per_month(email, start, end)
        bar_labels = [r["yr_mon"] for r in m_rows]
        bar_values = [float(r["spent"]) for r in m_rows]

        return render_template(
            "customer_past.html",
            start=start, end=end, city=city,
            dep_airports=dep_used, arr_airports=arr_used,
            rows=rows,
            pie_labels=pie_labels, pie_values=pie_values,
            bar_labels=bar_labels, bar_values=bar_values
        )


    # ---- 3. Spending dashboard -----------------------------------------
    @app.route("/customer/spending", methods=["GET", "POST"])
    @require_customer
    def customer_spending():
        email  = session["user_id"]
        today  = date.today()
        start, end = today - ONE_YEAR, today     # default 12-month window

        if request.method == "POST":
            start = _parse_iso(request.form.get("start"))
            end   = _parse_iso(request.form.get("end"))
            if start > end:
                raise BadRequest("Start date must not be after end date")

        # ── database queries (all param-bound) ───────────────────────────
        tickets = customer_db.past_tickets(email, start, end)
        commission_total = sum(float(r["Commission"]) for r in tickets)
        summary   = customer_db.spend_breakdown(email, start, end)
        monthly   = customer_db.spend_per_month(email, start, end)

        # pie data: spend by airline
        spend_air = {}
        for row in tickets:
            spend_air[row["Airline"]] = spend_air.get(row["Airline"], 0) + float(row["Paid"])


        pie_labels, pie_values = list(spend_air), list(spend_air.values())

        # bar data: spend per month
        bar_labels = [r["yr_mon"]           for r in monthly]
        bar_values = [float(r["spent"])     for r in monthly]

        return render_template(
            "customer_spending.html",
            start=start, end=end,
            total_spend      = float(summary["total_spend"]  or 0),
            commission_total = commission_total,            # NEW
            direct_spend     = float(summary["direct_spend"] or 0),
            agent_spend      = float(summary["agent_spend"]  or 0),
            total_tix        = int(summary["total_tix"]   or 0),
            direct_tix       = int(summary["direct_tix"]  or 0),
            agent_tix        = int(summary["agent_tix"]   or 0),
            rows=tickets,
            pie_labels=pie_labels, pie_values=pie_values,
            bar_labels=bar_labels, bar_values=bar_values
        )

    
    def _require_agent():
        if session.get("role") != "agent":
            return redirect(url_for("login"))
    
    def require_agent(view):
        """Route-decorator: allow only logged-in booking agents."""
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") != "agent":
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    @app.route("/agent/search", methods=["GET", "POST"])
    @require_agent
    def agent_flight_search() -> str:
        """Booking-agent: search upcoming flights for their authorised airlines only."""
        agent_id: str = session["user_id"]

        # 1. which airlines can this agent sell for?
        airlines: list[str] = agent_db.agent_airlines(agent_id)        # [] if none

        # 2. dropdown lists – use new helpers that look at Flight, not Ticket
        departure_airports: list[str] = agent_db.list_agent_departure_airports(airlines)
        arrival_airports:   list[str] = agent_db.list_agent_arrival_airports(airlines)

        # 3. autocomplete for customer emails
        past_customers: list[str] = agent_db.list_agent_customers(agent_id)

        # 4. run search if POST
        results: list[dict] = []
        cust_email: str = ""
        error: str | None = None

        if request.method == "POST":
            try:
                cust_email = request.form["customer_email"].strip()

                dep_sel  = request.form.get("departure_airport", "all")
                arr_sel  = request.form.get("arrival_airport",   "all")
                date_raw = request.form.get("date") or None

                src_city  = None if dep_sel == "all" else dep_sel
                dest_city = None if arr_sel == "all" else arr_sel
                on_date   = date.fromisoformat(date_raw) if date_raw else None

                raw = agent_db.search_upcoming_flights(
                    source           = src_city,
                    destination      = dest_city,
                    on_date          = on_date,
                    allowed_airlines = airlines           # restrict by Work_For
                )

                for row in raw:
                    row["Seats_Left"] = agent_db._remaining_seats(
                        row["Airline"], row["Flight_ID"]
                    )
                    row["Dep_City"] = agent_db.airport_city(row["Departure_Airport"])
                    row["Arr_City"] = agent_db.airport_city(row["Arrival_Airport"])

                results = raw

            except Exception as exc:
                error = str(exc)

        # 5. render page
        return render_template(
            "agent_search.html",
            user_type="Booking Agent",
            email=agent_id,
            departure_airports=departure_airports,
            arrival_airports=arrival_airports,
            past_customers=past_customers,
            table_content=results,
            customer_email=cust_email,
            error=error,
        )

    @app.route("/agent/purchase/<airline>/<flight_id>", methods=["POST"])
    @require_agent
    def agent_purchase(airline: str, flight_id: str):
        guard = _require_agent()  # redirect() or None
        if guard:
            return guard  # ⇢ /login

        agent_id = session["user_id"]  # Booking_Agent_ID in the session
        customer = request.form["customer_email"].strip()

        if not customer:
            flash("Customer e-mail is required.", "danger")
            return redirect(url_for("agent_flight_search"))

        try:
            # Check if the customer already has a ticket for the flight
            existing_ticket = agent_db.check_existing_ticket(flight_id, customer)
            if existing_ticket:
                flash(f"Customer already has a ticket for this flight. Ticket ID: {existing_ticket}", "danger")
                return redirect(url_for("agent_flight_search"))

            # Proceed with the purchase
            agent_db.purchase_for_customer(
                flight_id=flight_id,  # cast to int
                airline=airline,
                customer_email=customer,
                agent_id=agent_id,
            )
            flash("Ticket purchased successfully!", "success")
            return redirect(url_for("home"))

        except PermissionError as err:
            # agent can’t sell for this airline
            flash(str(err), "danger")
            return redirect(url_for("agent_flight_search"))

        except RuntimeError as err:
            # plane is full
            flash(str(err), "danger")
            return redirect(request.referrer or url_for("agent_flight_search"))


    # ---- 2.  Commission dashboard ----------------------------
    @app.route("/agent/commission", methods=["GET", "POST"])
    @require_agent
    def agent_commission():
        agent_id = session["user_id"]
        today  = date.today()
        start  = today - timedelta(days=30)
        end    = today
        if request.method == "POST":
            s = request.form.get("start") or start.isoformat()
            e = request.form.get("end")   or end.isoformat()
            start = date.fromisoformat(s)
            end   = date.fromisoformat(e)
        rows = agent_db.get_commission_tickets(agent_id, start, end)

        cust_totals = {}
        for r in rows:
            cust_totals[r["Customer_Email"]] = cust_totals.get(r["Customer_Email"], 0) + float(r["Price"]) * 0.10
        pie_labels  = list(cust_totals.keys())
        pie_values  = list(cust_totals.values())
        
        day_rows    = agent_db.commission_per_day(agent_id, start, end)
        bar_labels  = [r["day"].strftime("%Y-%m-%d") for r in day_rows]
        bar_values  = [float(r["commission"])         for r in day_rows]

        # summary
        total_comm  = sum(pie_values)
        tickets     = len(rows)
        avg_comm    = total_comm / tickets if tickets else 0

        return render_template(
            "agent_commission.html",
            user_type="Booking Agent",
            email=agent_id,
            start=start, end=end,
            total_comm=total_comm, avg_comm=avg_comm, tickets=tickets,
            rows=rows,
            pie_labels=pie_labels, pie_values=pie_values,
            bar_labels=bar_labels, bar_values=bar_values
        )



    # ---- 3.  Past flights sold --------------------------------
    @app.route("/agent/past_flights", methods=["GET", "POST"])
    @require_agent
    def agent_past_flights():
        agent_id = session["user_id"]

        # helper lists ----------------------------------------------------
        airlines = agent_db.agent_airlines(agent_id)
        departure_airports = agent_db.list_agent_departure_airports(airlines)
        arrival_airports   = agent_db.list_agent_arrival_airports(airlines)
        past_customers     = agent_db.list_agent_customers(agent_id)

        # defaults
        flights, start, end = [], None, None
        cust_email = dep_sel = arr_sel = None
        error = None

        if request.method == "POST":
            try:
                cust_email = request.form.get("customer_email", "").strip() or None

                dep_sel = request.form.get("departure_airport", "all")
                dep_sel = None if dep_sel == "all" else dep_sel

                arr_sel = request.form.get("arrival_airport", "all")
                arr_sel = None if arr_sel == "all" else arr_sel

                s = request.form.get("start")
                e = request.form.get("end")
                start = date.fromisoformat(s) if s else None
                end   = date.fromisoformat(e) if e else None
            except Exception as exc:
                error = str(exc)

        flights = agent_db.get_past_flights(
            agent_id,
            customer_email=cust_email,
            departure_airport=dep_sel,
            arrival_airport=arr_sel,
            start=start,
            end=end
        )

        return render_template(
            "agent_past.html",
            user_type          = "Booking Agent",
            email              = agent_id,
            flights            = flights,
            departure_airports = departure_airports,
            arrival_airports   = arrival_airports,
            past_customers     = past_customers,
            customer_email     = cust_email or "",
            start              = start,
            end                = end,
            error              = error,
        )

    # ---- 4.  Top customers widgets ---------------------------
    @app.route("/agent/top_customers")
    @require_agent
    def agent_top_customers():
        agent_id = session["user_id"]

        # 1 .  raw DB data
        by_tickets    = agent_db.top_customers_by_tickets(agent_id)      # last 6 mo
        by_commission = agent_db.top_customers_by_commission(agent_id)   # last 12 mo
        month_rows    = agent_db.monthly_commission_totals(agent_id)     # helper we added

        # 2 .  pie data (handle “no rows” safely)
        if by_commission:
            pie_labels = [r["customer"] for r in by_commission]
            pie_values = [float(r["commission"]) for r in by_commission]
        else:
            pie_labels, pie_values = [], []

        # 3 .  bar data (also safe when empty)
        months       = [r["month"]       for r in month_rows]
        month_totals = [float(r["commission"]) for r in month_rows]

        # 4 .  render
        return render_template(
            "agent_top.html",
            user_type="Booking Agent",
            email=agent_id,
            by_tickets=by_tickets,
            by_commission=by_commission,
            pie_labels=pie_labels,
            pie_values=pie_values,
            months=months,
            month_totals=month_totals
        )


    def _require_airline_staff():
        """Ensure the user is logged in as airline staff."""
        if 'user_id' not in session or session.get('role') != 'staff':
            return redirect(url_for('login'))  # redirect to login page if not logged in or wrong role
        return None
    
    
    def require_staff(view):
        """Route decorator - only airline-staff users may enter."""
        @wraps(view)
        def wrapper(*a, **kw):
            if session.get("role") != "staff":
                return redirect(url_for("login"))
            return view(*a, **kw)
        return wrapper


    def require_perm(perm):
        """
        Route decorator - staff must hold a specific permission
        (“Admin”, “Operator”, …).  Implies require_staff.
        """
        def decorator(view):
            @wraps(view)
            def wrapper(*a, **kw):
                if session.get("role") != "staff":
                    return redirect(url_for("login"))
                if perm not in staff_db.permissions(session["user_id"]):
                    return "Forbidden", 403
                return view(*a, **kw)
            return wrapper
        return decorator


    def _airline() -> str:
        """Convenience: airline of the logged-in staff (never None)."""
        return staff_db.profile(session["user_id"])["Airline"]

    # ────────────────────────── 1. My flights ─────────────────────────
    @app.get("/staff/flights")
    @require_staff
    def staff_flights() -> str:
        airline = _airline()                         # helper: current staff airline

        # ---------- read query-string filters --------------------
        start = request.args.get("start") or None
        end   = request.args.get("end")   or None
        src   = request.args.get("departure_airport", "All")
        dest  = request.args.get("arrival_airport",   "All")

        # ---------- default window when no dates chosen ----------
        if start is None and end is None:
            start_default = date.today()
            end_default   = start_default + timedelta(days=30)
            start, end = start_default, end_default

        # ---------- pull flights (list, never generator) ---------
        flights = staff_db.get_flights(airline, start, end)       # helper you added

        if src  and src  != "All":
            flights = [f for f in flights
                    if src == f["Departure_Airport"]]
        if dest and dest != "All":
            flights = [f for f in flights
                    if dest == f["Arrival_Airport"]]

        # ---------- chart data -----------------------------------
        raw_status = staff_db.get_flight_status_distribution(airline, start, end)
        pie_labels = [r["Status_"]       for r in raw_status]
        pie_values = [int(r["count"])    for r in raw_status]

        raw_days   = staff_db.get_daily_flights_count(airline, start, end)
        bar_labels = [r["Departure_Date"].isoformat() for r in raw_days]
        bar_values = [int(r["flight_count"])          for r in raw_days]

        # ---------- dropdown options -----------------------------
        departure_airports = staff_db.get_departure_airports(airline)
        arrival_airports   = staff_db.get_arrival_airports(airline)

        # ---------- permission gate ------------------------------
        perms       = staff_db.permissions(session["user_id"])
        is_operator = "Operator" in perms

        return render_template(
            "staff_flights.html",
            airline_name      = airline,
            start=start, end=end,
            departure_airport = src,
            arrival_airport   = dest,
            flights           = flights,

            pie_labels  = pie_labels,
            pie_values  = pie_values,
            bar_labels  = bar_labels,
            bar_values  = bar_values,

            departure_airports = departure_airports,
            arrival_airports   = arrival_airports,

            is_operator = is_operator,
            permissions = perms,
        )
    
    @app.route("/airline_staff/change_status/<airline>/<flight_id>", methods=["POST"])
    def airline_staff_change_status(airline: str, flight_id: str):
        guard = _require_airline_staff()
        if guard:
            return guard

        new_status = request.form["status"]  # You can add the new status here
        try:
            staff_db.update_flight_status(flight_id, airline, new_status)  # Call to the function to update the status in the DB
            flash("Flight status updated successfully.", "success")
        except Exception as e:
            flash(f"Error updating flight status: {str(e)}", "danger")

        return redirect(url_for("staff_flights"))   

    @app.route("/staff/flights/<flight_id>/passengers")
    @require_staff
    def staff_passengers(flight_id):
        pax = staff_db.passengers_of_flight(_airline(), flight_id)
        return render_template("staff_passengers.html",
                            flight_id=flight_id, passengers=pax)

    # ────────────────────── 2. Create flight (Admin) ───────────────────
    @app.route("/staff/flight/new", methods=["GET", "POST"])
    @require_perm("Admin")
    def staff_new_flight():
        airline = _airline()
        
        # Get all available airports with city information
        airports = staff_db.get_airports_with_cities()
        
        if request.method == "POST":
            # Create a dictionary from the form data
            attrs = {
                # Map form field names to database column names
                "Airline": airline,  # Enforce current airline
                "Airplane_ID": request.form["Airplane_ID"],
                "Departure_Airport": request.form["Departure_Airport"],
                "Departure_Date": request.form["Departure_Date"],
                "Departure_Time": request.form["Departure_Time"],
                "Arrival_Airport": request.form["Arrival_Airport"],
                "Arrival_Date": request.form["Arrival_Date"], 
                "Arrival_Time": request.form["Arrival_Time"],
                "Price": request.form["Price"],
                "Status_": "Upcoming"  # Default status for new flights
            }
            
            try:
                # Use the enhanced create_flight method that generates Flight_ID
                flight_id = staff_db.create_flight(**attrs)
                flash(f"Flight {flight_id} created successfully ✅", "success")
                return redirect(url_for("staff_flights"))
            except ValueError as err:
                flash(str(err), "danger")
            except Exception as err:
                flash(f"Error creating flight: {str(err)}", "danger")
        
        return render_template(
            "staff_new_flight.html",
            airports=airports
        )
    # ──────────────── 4. Add airplane (+ list) (Admin) ───────────────
    @app.route("/staff/airplane/new", methods=["GET", "POST"])
    @require_perm("Admin")
    def staff_add_airplane():
        airline = _airline()
        if request.method == "POST":
            try:
                staff_db.add_airplane(airline,
                                request.form["plane_id"],
                                request.form["seats"])
                flash("Airplane added ✅", "success")
            except mysql.connector.Error as err:
                # Check for duplicate entry error (MySQL error code 1062)
                if err.errno == 1062:
                    flash(f"Error: Airplane ID {request.form['plane_id']} already exists for this airline", "danger")
                else:
                    flash(f"Database error: {err}", "danger")
            except Exception as e:
                flash(f"An error occurred: {str(e)}", "danger")
            
            return redirect(url_for("staff_add_airplane"))

        planes = staff_db._fetchall("SELECT * FROM Airplane WHERE Airline=%s",
                                    (airline,))
        return render_template("staff_add_airplane.html", airplanes=planes)

    # ─────────────── 5. Add airport (Admin) ───────────────────────────
    @app.route("/staff/airport/new", methods=["GET", "POST"])
    @require_perm("Admin")
    def staff_add_airport():
        if request.method == "POST":
            try:
                staff_db.add_airport(request.form["name"], request.form["city"])
                flash("Airport added ✅", "success")
            except mysql.connector.Error as err:
                # Check for duplicate entry error
                if err.errno == 1062:
                    flash(f"Error: Airport code '{request.form['name']}' already exists in the database", "danger")
                else:
                    flash(f"Database error: {err}", "danger")
            except Exception as e:
                flash(f"An error occurred: {str(e)}", "danger")
            
            return redirect(url_for("staff_add_airport"))
            
        return render_template("staff_add_airport.html")

    @app.route("/staff/booking_agents", methods=["GET", "POST"])
    @require_staff  # Changed from @require_perm("Admin") to allow all staff to view
    def staff_view_booking_agents():
        """
        Comprehensive view and management of booking agents for the airline.
        Shows top and bottom performing agents, and allows admins to add new agents.
        """
        airline = _airline()  # Get the current staff member's airline
        
        # Get user permissions to check if they're an admin
        user_id = session["user_id"]
        permissions = staff_db.permissions(user_id)
        is_admin = "Admin" in permissions
        
        # Handle POST request to add a new booking agent (admin only)
        if request.method == "POST":
            # Verify the user is an admin before allowing them to add agents
            if not is_admin:
                flash("Permission denied: Only admins can add booking agents", "danger")
                return redirect(url_for("staff_view_booking_agents"))
                
            agent_id = request.form.get("agent_id")
            
            if not agent_id:
                flash("Agent ID is required", "danger")
            else:
                try:
                    staff_db.add_booking_agent_to_airline(agent_id, airline)  # Note: Fixed parameter order
                    flash(f"Booking agent {agent_id} added to {airline} successfully!", "success")
                except Exception as e:
                    flash(f"Failed to add booking agent: {str(e)}", "danger")
            
            return redirect(url_for("staff_view_booking_agents"))
        
        # Handle GET request to display the page
        period = request.args.get("period", "month")  # Default to monthly view
        
        # Get comprehensive booking agent data
        agent_data = staff_db.top_booking_agents_comprehensive(airline, period)
        
        # Get bottom performing agents
        bottom_agents = staff_db.bottom_booking_agents(airline, period)
        
        # Get list of booking agents not currently working for this airline
        # Only fetch available agents if the user is an admin
        available_agents = []
        if is_admin:
            available_agents = staff_db.list_booking_agents_not_working_for_airline(airline)
        
        return render_template(
            "staff_booking_agents.html",
            top_tickets=agent_data['by_tickets'],
            top_commission=agent_data['by_commission'],
            bottom_agents=bottom_agents,
            sales_distribution=agent_data['agent_sales_distribution'],
            monthly_sales=agent_data['monthly_sales'],
            available_agents=available_agents,
            period=period,
            is_admin=is_admin  # Pass admin status to the template
        )


    @app.route("/staff/booking_agents/add", methods=["POST"])
    @require_perm("Admin")
    def staff_add_booking_agent():
        """Add a booking agent to work for the staff's airline."""
        airline = _airline()
        agent_id = request.form.get("agent_id")
        
        if not agent_id:
            flash("Agent ID is required", "danger")
            return redirect(url_for("staff_view_booking_agents"))
        
        try:
            staff_db.add_booking_agent_to_airline(airline, agent_id)
            flash(f"Booking agent {agent_id} added to {airline} successfully!", "success")
        except Exception as e:
            flash(f"Failed to add booking agent: {str(e)}", "danger")
        
        return redirect(url_for("staff_view_booking_agents"))

    # ────────────────── Manage Staff Permissions ────────────────────────
    @app.route("/staff/permissions", methods=["GET", "POST"])
    @require_perm("Admin")
    def staff_manage_permissions():
        """View and update permissions for all staff members of the same airline."""
        airline = _airline()
        current_username = session.get("user_id")  # Get the current user's username
        
        # Handle POST request to update a staff member's permission
        if request.method == "POST":
            username = request.form.get("username")
            new_role = request.form.get("new_role")
            
            if not username:
                flash("Username is required", "danger")
            elif username == current_username:
                flash("You cannot change your own permissions", "danger")
            else:
                try:
                    staff_db.update_staff_permission(username, new_role)
                    flash(f"Permission for {username} updated to {new_role or 'None'} successfully!", "success")
                except Exception as e:
                    flash(f"Failed to update permission: {str(e)}", "danger")
            
            return redirect(url_for("staff_manage_permissions"))
        
        # Handle GET request to display the page
        # Get list of all staff members for this airline with their current roles
        staff_members = staff_db.list_all_airline_staff(airline)
        
        # Get possible permission roles
        permission_roles = ["Admin", "Operator", "Admin & Operator", None]
        
        return render_template(
            "staff_permissions.html",
            staff_members=staff_members,
            permission_roles=permission_roles,
            current_username=current_username  # Pass the current username to the template
        )
    @app.route("/staff/permissions/update", methods=["POST"])
    @require_perm("Admin")
    def staff_update_permission():
        """Update permission for a staff member."""
        username = request.form.get("username")
        new_role = request.form.get("new_role")
        
        if not username:
            flash("Username is required", "danger")
            return redirect(url_for("staff_manage_permissions"))
        
        try:
            staff_db.update_staff_permission(username, new_role)
            flash(f"Permission for {username} updated to {new_role or 'None'} successfully!", "success")
        except Exception as e:
            flash(f"Failed to update permission: {str(e)}", "danger")
        
        return redirect(url_for("staff_manage_permissions"))

    # ─────────────── 7. Frequent customer + flight list ───────────────
    @app.route("/staff/customers", methods=["GET", "POST"])
    @require_staff
    def staff_customers():
        airline = _airline()
        
        # Get top frequent customers (expanded from just one)
        top_customers = staff_db.top_customers_by_flights(airline, limit=5)
        
        # Get customer destinations data for visualization
        destinations_data = staff_db.customer_destinations(airline)
        
        # Get monthly customer activity for trend analysis
        monthly_activity = staff_db.monthly_customer_activity(airline)
        
        # Get ticket revenue by customer category
        revenue_by_category = staff_db.revenue_by_customer_category(airline)
        
        # For individual customer lookup
        flights = []
        email = ""
        customer_info = None
        flight_stats = None
        
        if request.method == "POST":
            email = request.form["customer_email"].strip()
            
            # Get detailed flight data for this customer
            flights = staff_db.flights_of_customer(airline, email)
            
            # Get additional customer information if they exist
            if flights:
                # Get customer profile information
                customer_info = staff_db.get_customer_details(email)
                
                # Get statistics about the customer's flights
                flight_stats = staff_db.get_customer_flight_stats(airline, email)

        return render_template("staff_customers.html",
                            airline=airline,
                            top_customers=top_customers,
                            destinations_data=destinations_data,
                            monthly_activity=monthly_activity,
                            revenue_by_category=revenue_by_category,
                            customer_info=customer_info,
                            flight_stats=flight_stats,
                            email=email,
                            flights=flights)


    # ────────────── 8-10. Analytics & charts dashboard ────────────────
    @app.route("/staff/analytics", methods=["GET", "POST"])
    @require_staff
    def staff_analytics() -> str:
        """
        Analytics dashboard for airline-staff users.

        Optional query parameters
        -------------------------
            ?start=YYYY-MM-DD&end=YYYY-MM-DD

        If a parameter is missing or malformed:
            • start defaults to (today – 365 days)
            • end   defaults to today
        """
        # airline of the logged-in staff (helper you defined above)
        airline: str = _airline()
        dest_limit = int(request.args.get("dest_limit", 5))
        cust_limit = int(request.args.get("cust_limit", 3))

        # ── date-range parsing ────────────────────────────────────────────
        today = date.today()

        def _parse(dstr: str | None, default: date) -> date:
            try:
                return date.fromisoformat(dstr) if dstr else default
            except ValueError:
                return default

        start = _parse(request.args.get("start"), today - timedelta(days=365))
        end   = _parse(request.args.get("end"),   today)

        # ── collect datasets from the DB layer (sql-injection safe) ───────
        summary_cards = _dec2float(staff_db.sales_summary(airline, start, end))
        monthly_tix   = _dec2float(staff_db.tickets_per_month(airline, start, end))
        monthly_rev   = _dec2float(staff_db.revenue_per_month(airline, start, end))
        dest_revenue  = _dec2float(staff_db.revenue_by_destination_split(airline, start, end, limit=10))
        top_3m        = _dec2float(staff_db.top_destinations_split(airline, "3m"))
        top_1y        = _dec2float(staff_db.top_destinations_split(airline, "1y"))
        top_cust_rows = _dec2float(staff_db.top_customers_monthly(airline, start, end, limit=cust_limit))
        sched_rows    = _dec2float(staff_db.flights_next_two_months_by_destination(airline))

        # ── render the dashboard template ─────────────────────────────────
        return render_template(
            "staff_analytics.html",
            start=start, end=end,
            dest_limit=dest_limit, cust_limit=cust_limit,
            summary=summary_cards,
            monthly_tix=monthly_tix,
            monthly_rev=monthly_rev,
            dest_revenue=dest_revenue,
            top_3m=top_3m, top_1y=top_1y,
            top_cust_rows=top_cust_rows,
            sched_rows=sched_rows,
        )


    @app.route("/logout")
    def logout():
        session.clear()                       
        return render_template("logout.html")
    

    # --------------------------- run ----------------------------
    app.run(debug=True)


if __name__ == "__main__":
    main()