'''
app.py — Solfer Flask application

Routes
------
  GET  /                          Home page (editor)
  GET  /auth                      Login / signup page

  POST /auth/signup               Register with email + password
  POST /auth/login                Login with email + password
  POST /auth/logout               Log out current session
  GET  /auth/google               Initiate Google OAuth flow
  GET  /auth/google/callback      Google OAuth callback

  GET  /auth/forgot-password      Render forgot-password form
  POST /auth/forgot-password      Send reset email
  GET  /auth/reset-password       Render reset form (token in query-string)
  POST /auth/reset-password       Apply new password

  GET  /api/me                    Return current user profile (JSON)

  POST /api/measures              Save / upsert a measure
  PUT  /api/measures/<id>         Update an existing measure
  DELETE /api/measures/<id>       Delete a measure

  POST /payment/initiate          Create a payment session and return the URL to redirect to a payment processor page (e.g. Stripe Checkout)
  POST /payment/webhook           Payment processor webhook — confirm payment & upgrade user

'''

import os
# import json
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

# import stripe                         # pip install stripe
from flask import (
    Flask, render_template, redirect, url_for,
    request, session, jsonify, abort, flash,
)
from flask_login import (             # pip install flask-login
    LoginManager, login_user, logout_user,
    login_required, current_user,
)

from flask_wtf import CSRFProtect

from flask_limiter import Limiter

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from werkzeug.exceptions import BadRequest

from core.mailer import send_reset_email, send_receipt_email

from core.models import db, User, Measure, Transaction

from core.helpers import is_valid_flutterwave_webhook
from core.flutterwave_services import FlutterwaveService

# Firstly, I do not want the server starting without a secret key

if not os.environ.get("SECRET_KEY"): 
    raise Exception("Secret key not set")

csrf_protect = CSRFProtect()  # For protecting non-JSON routes from CSRF
limiter = Limiter(key_func=lambda: current_user.id if current_user.is_authenticated else request.remote_addr)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

# A little helper function to  always return timezone-aware UTC datetimes, even if the database returns naive values.
def as_utc(dt):
    """Return dt as an aware UTC datetime (naive values are assumed to be UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")
    csrf_protect.init_app(app)
    limiter.init_app(app)

    uri = os.environ["DATABASE_URL"]
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,   # drop dead connections instead of erroring
        "pool_recycle": 1800,    # recycle before the server/proxy closes idle ones
    }
    # ── Core config ─────────────────────────────────────────────────────────
    app.config.update(
        SECRET_KEY                = os.environ.get("SECRET_KEY", ""),
        # SQLALCHEMY_DATABASE_URI   = "sqlite:///"+str(Path(__file__).parent / "sqlite.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS = False,

        # Session cookie
        SESSION_COOKIE_HTTPONLY   = True,
        SESSION_COOKIE_SAMESITE   = "Lax",
        SESSION_COOKIE_SECURE     = os.environ.get("FLASK_ENV") == "production",
        PERMANENT_SESSION_LIFETIME = timedelta(days=30),

        ACCESS_DURATION_DAYS      = int(os.environ.get("ACCESS_DURATION_DAYS", 14)),

        FLUTTERWAVE_CLIENT_ID     = os.environ.get("FLUTTERWAVE_CLIENT_ID", ""),
        FLUTTERWAVE_CLIENT_SECRET = os.environ.get("V4_FLUTTERWAVE_CLIENT_SECRET", ""),

        # Google OAuth (using Authlib — pip install authlib requests)
        GOOGLE_CLIENT_ID          = os.environ.get("GOOGLE_CLIENT_ID", ""),
        GOOGLE_CLIENT_SECRET      = os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        GOOGLE_OAUTH_ENABLED      = bool(os.environ.get("GOOGLE_OAUTH_ENABLED", False)),
    )


    if config:
        app.config.update(config)

    # ── Extensions ──────────────────────────────────────────────────────────
    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view    = "auth.login_page"
    login_manager.login_message = "Please log in to continue."

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    # Flask-Login requires these on the User model; add them as mixins or
    # implement them inline here for simplicity.
    _patch_user_for_flask_login()

    # ── Blueprints ───────────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(payment_bp)

    # ── Database ─────────────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()

    return app


def _patch_user_for_flask_login():
    """
    Add Flask-Login interface to User without importing UserMixin
    (keeps models.py free of Flask-Login dependency).
    """
    User.is_authenticated = property(lambda self: True)
    User.is_active         = property(lambda self: True)
    User.is_anonymous      = property(lambda self: False)
    User.get_id            = lambda self: str(self.id)


# ---------------------------------------------------------------------------
# Helpers / decorators
# ---------------------------------------------------------------------------

def json_required(f):
    """Abort with 400 if the request body is not valid JSON."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not request.is_json:
            abort(400, "JSON body required")
        return f(*args, **kwargs)
    return wrapper


def api_login_required(f):
    """Return JSON 401 instead of a redirect for API routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(error="Authentication required"), 401
        return f(*args, **kwargs)
    return wrapper


def paid_required(f):
    """Return JSON 403 if the user does not have active paid access."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.has_active_access:
            return jsonify(error="Paid access required"), 403
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Blueprint: pages  (GET / and GET /auth)
# ---------------------------------------------------------------------------

from flask import Blueprint

auth_bp    = Blueprint("auth",    __name__, url_prefix="/auth")
api_bp     = Blueprint("api",     __name__, url_prefix="/api")
payment_bp = Blueprint("payment", __name__, url_prefix="/payment")


# ── Home ─────────────────────────────────────────────────────────────────────

@auth_bp.app_errorhandler(404)
def not_found(_):
    return jsonify(error="Not found"), 404


# Register the home route on the app directly (not a blueprint) so it sits at /
# We do this by attaching after the factory runs — see bottom of file.

def register_root_routes(app: Flask):
    @app.get("/")
    def home():
        """
        Serve the main editor page.
        Pass the current user and their measures to the template so the
        frontend can restore the session without an extra API call.
        """
        measures = []
        if current_user.is_authenticated:
            measures = [m.to_dict() for m in current_user.measures]

        is_paid_user = False
        if current_user.is_authenticated:
            is_paid_user = current_user.has_active_access or current_user.email in os.environ.get("ADMIN_EMAILS", "").split(",")
            
        print("PAID?: ", is_paid_user)
        return render_template(
            "index.html",
            user=current_user if current_user.is_authenticated else None,
            measures=measures,
            last_m_id=max((m["m_id"] for m in measures), default=0),
            is_paid_user=is_paid_user,
            days_remaining=(as_utc(current_user.access_until) - datetime.now(timezone.utc)).days if current_user.is_authenticated and current_user.access_until else 0,
            # stripe_key=app.config["STRIPE_PUBLISHABLE_KEY"],
        )


# ---------------------------------------------------------------------------
# Blueprint: auth
# ---------------------------------------------------------------------------

# ── Render auth page ─────────────────────────────────────────────────────────

@auth_bp.get("/")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return render_template("auth.html", google_oauth_enabled=app.config["GOOGLE_OAUTH_ENABLED"])


# ── Email / password signup ───────────────────────────────────────────────────

@auth_bp.post("/signup")
@json_required
def signup():
    data     = request.get_json()
    name     = (data.get("name") or "").strip()
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    # Basic validation
    if not name or not email or len(password) < 8:
        return jsonify(error="name, email, and a password of ≥8 chars are required"), 422

    if User.query.filter_by(email=email).first():
        return jsonify(error="An account with that email already exists"), 409

    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user, remember=True)
    session.permanent = True
    return jsonify(user=user.to_dict()), 201


# ── Email / password login ───────────────────────────────────────────────────

@auth_bp.post("/login")
@json_required
def login():
    data     = request.get_json()
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify(error="Invalid email or password"), 401

    login_user(user, remember=True)
    session.permanent = True
    return jsonify(user=user.to_dict()), 200


# ── Logout ───────────────────────────────────────────────────────────────────

@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")
    # return jsonify(message="Logged out"), 200


# ── Forgot password ───────────────────────────────────────────────────────────

@auth_bp.get("/forgot-password")
def forgot_password_page():
    return render_template("forgot_password.html")


@auth_bp.post("/forgot-password")
@json_required
@limiter.limit("3/hr")
def forgot_password():
    """
    Generate a signed reset token and e-mail it to the user.
    """
    email = (request.get_json().get("email") or "").strip().lower()
    user  = User.query.filter_by(email=email).first()

    # Always return 200 to avoid leaking whether the address is registered.
    if user:
        print("got here")
        token = _generate_reset_token(user)
        reset_url = "{}/auth/reset-password/{}".format(request.host_url.rstrip("/"), token)
        print(reset_url)
        send_reset_email(user.email, reset_url)

    return jsonify(message="If that email is registered you will receive a reset link."), 200


@auth_bp.get("/reset-password/<string:token>")
def reset_password_page(token):
    if not _verify_reset_token(token):
        return "Invalid or expired reset link <a href="/">Go back home</a>", 400
    return render_template("reset_password.html", token=token)


@auth_bp.post("/reset-password")
@json_required
def reset_password():
    data     = request.get_json()
    token    = data.get("token") or ""
    password = data.get("password") or ""

    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters"), 422

    user = _verify_reset_token(token)
    if not user:
        return jsonify(error="Invalid or expired reset link"), 400

    user.set_password(password)
    db.session.commit()
    return jsonify(message="Password updated — please log in."), 200


# ── Reset-token helpers (HMAC-based, stateless) ───────────────────────────────

_RESET_TOKEN_MAX_AGE_SECONDS = 3600  # 1 hour

def _generate_reset_token(user: User) -> str:
    import time, base64
    secret  = os.environ.get("SECRET_KEY")
    payload = f"{user.id}:{user.email}:{int(time.time())}"
    sig     = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw     = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _verify_reset_token(token: str):
    import time, base64
    try:
        raw     = base64.urlsafe_b64decode(token.encode()).decode()
        parts   = raw.rsplit(":", 1)
        payload, sig = parts[0], parts[1]
        secret  = os.environ.get("SECRET_KEY")
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        uid, email, ts = payload.split(":", 2)
        if time.time() - int(ts) > _RESET_TOKEN_MAX_AGE_SECONDS:
            return None
        return db.session.get(User, int(uid))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Blueprint: api  (/api/*)
# ---------------------------------------------------------------------------

@api_bp.get("/me")
@api_login_required
def me():
    return jsonify(user=current_user.to_dict()), 200


# ── Measures ─────────────────────────────────────────────────────────────────

@api_bp.post("/measures")
@api_login_required
@json_required
def save_measure():
    """
    Create or upsert a measure.

    Body (JSON):
        measure_string  str   required — the raw solfa string
        label           str   optional
        position        int   optional — ordering index
        key             str   optional — e.g. "C"
        time_sig        str   optional — e.g. "4/4"
        part            str   optional — "S"|"A"|"T"|"B"
        measure_id      str   required
    """
    data = request.get_json()
    measure_string = (data.get("measure_string") or "").strip()
    if not measure_string:
        return jsonify(error="measure_string is required"), 422

    measure = Measure(
        user_id        = current_user.id,
        measure_string = measure_string,
        label          = data.get("label"),
        position       = data.get("position", 0),
        key            = data.get("key"),
        time_sig       = data.get("time_sig"),
        part           = data.get("part"),
        m_id           = data.get("measure_id")
    )
    print(data.get("measure_id"))
    db.session.add(measure)
    db.session.commit()
    return jsonify(measure=measure.to_dict()), 201


# @api_bp.put("/measures/<int:measure_id>")
# @api_login_required
# @json_required
# def update_measure(measure_id: int):
#     """
#     Update an existing measure.  Only the owner may update.
#     Accepts the same optional fields as save_measure.
#     """
#     measure = db.session.get(Measure, measure_id)
#     if not measure or measure.user_id != current_user.id:
#         return jsonify(error="Measure not found"), 404

#     data = request.get_json()
#     if "measure_string" in data:
#         measure.measure_string = (data["measure_string"] or "").strip() or measure.measure_string
#     if "label"    in data: measure.label    = data["label"]
#     if "position" in data: measure.position = int(data["position"])
#     if "key"      in data: measure.key      = data["key"]
#     if "time_sig" in data: measure.time_sig = data["time_sig"]
#     if "part"     in data: measure.part     = data["part"]

#     db.session.commit()
#     return jsonify(measure=measure.to_dict()), 200


@api_bp.delete("/measures/<string:measure_id>")
@api_login_required
def delete_measure(measure_id: int):
    """Delete a measure.  Only the owner may delete."""
    measure = db.session.execute(db.select(Measure).filter_by(m_id=measure_id, user_id=current_user.id)).scalar_one_or_none()
    print(measure)
    if not measure or measure.user_id != current_user.id:
        return jsonify(error="Measure not found"), 404

    db.session.delete(measure)
    db.session.commit()
    return jsonify(message="Measure deleted"), 200


@api_bp.get("/measures")
@api_login_required
def list_measures():
    """Return all measures for the current user, ordered by position."""
    measures = (
        db.session.query(Measure)
        .filter_by(user_id=current_user.id)
        .order_by(Measure.position)
        .all()
    )
    return jsonify(measures=[m.to_dict() for m in measures]), 200


@api_bp.put("/measures/reorder")
@api_login_required
@json_required
def reorder_measures():
    """
    Bulk-update positions.

    Body:
        { "order": [<measure_id>, <measure_id>, ...] }

    Positions are assigned as 0, 1, 2, … in the given order.
    """
    order = request.get_json().get("order") or []
    for pos, measure_id in enumerate(order):
        measure = db.session.execute(db.select(Measure).filter_by(m_id=measure_id)).scalar_one_or_none()
        if measure and measure.user_id == current_user.id:
            measure.position = pos
    db.session.commit()
    return jsonify(message="Order updated"), 200


# ---------------------------------------------------------------------------
# Blueprint: payment  (/payment/*)
# Uses Flutterwave Checkout (one-time payment).
# ---------------------------------------------------------------------------

@payment_bp.get("/checkout")
@api_login_required
def load_payment_page():
    # Acknowledge all other events
    return render_template("payment.html", access_days=app.config["ACCESS_DURATION_DAYS"])
    # return redirect("https://flutterwave.com/pay/solfer-payment", code=302)
    # return jsonify(received=True), 200

@payment_bp.get("/initiate-payment")
@api_login_required
def generate_payment_deets():
    data = {
        "email": current_user.email,
        "amount": int(os.environ.get("PAYMENT_AMOUNT_NGN", 200)),
        "currency": "NGN",
        "name": current_user.name,
        "access_days": app.config["ACCESS_DURATION_DAYS"],
        "public_key": os.environ.get("FLUTTERWAVE_PUBLIC_KEY", ""),
    }
    
    return jsonify(data), 200

@payment_bp.post("/transfer/generate")
@api_login_required
def generate_transfer_deets():
    flw_service = FlutterwaveService(
        client_id=os.environ.get("FLUTTERWAVE_CLIENT_ID", ""),
        client_secret=os.environ.get("V4_FLUTTERWAVE_CLIENT_SECRET", "")
    )
    # access_token = flw_service._get_access_token()
    # if not access_token:
    #     return jsonify(error="Failed to generate details due to an internal error. It's our fault."), 500
    
    # FlutterwaveService.debug = True
    payment_details = flw_service.generate_transfer_details(
            current_user.email,
            os.environ.get("PAYMENT_AMOUNT_NGN", 200),
            current_user.name,
            os.environ.get("NARRATION")
        )
    print(payment_details)
    if not payment_details:
        return jsonify(error="Failed to generate details due to an internal error. It's our fault."), 500

    return jsonify(
        payment_details
    ), 200


@payment_bp.get("/statuxs/<string:tx_ref>")
def check_payment_status(tx_ref: str):
    print("Checking payment status for tx_ref:", tx_ref)
    flw_service = FlutterwaveService(
        client_id=os.environ.get("FLUTTERWAVE_CLIENT_ID", ""),
        client_secret=os.environ.get("V4_FLUTTERWAVE_CLIENT_SECRET", "")
    )
    status = flw_service._check_transfer_status_once(tx_ref)
    print(status)
    if status:
        return jsonify(status=status), 200
    return jsonify(error="could not fetch details"), 200

@payment_bp.get("/success")
def success():
    return render_template("thank_you.html")

'''
 {
 'webhook_id': 'wbk_9TjTzxQib0S11jRY1w0T', 
 'timestamp': 1784272795173, 
 'type': 'charge.completed', 
 'data': {
    'id': 'chg_6Po8kuWOPJ', 
    'amount': 100.0, 
    'currency': 'NGN', 
    'customer': {
        'id': 'cus_CRLTewfdja', 
        'address': None, 
        'email': 'beansonius@email.com', 
        'name': {
            'first': 'Sicnarf', 'middle': None, 'last': 'Biro'}, 
        'phone': None, 
        'meta': {}, 
        'created_datetime': '2026-07-15T12:49:07.347Z'
  }, 
'description': 'Transfer from CHISOM FRANCIS ALI', 
'meta': {}, 
'payment_method': {
    'type': 'bank_transfer', 
    'bank_transfer': {
        'account_expires_in': 1800, 
        'account_display_name': None, 
        'account_type': 'dynamic', 
        'originator_bank_name': 'OPAY', 
        'originator_account_number': '701*******28', 'originator_name': 'CHISOM FRANCIS ALI'
    }, 
    'id': 'pmd_CgBjonYN2n', 
    'customer_id': None, 
    'meta': {}, 
    'device_fingerprint': None, 
    'client_ip': None, 
    'created_datetime': '2026-07-17T07:18:47.395Z'
}, 
'redirect_url': None, 
'reference': 'c8a2dba24632f289c6a57c3740fc2162', 
'status': 'succeeded', 
'processor_response': {'type': 'approved', 'code': '00'}, 'created_datetime': '2026-07-17T07:19:55.157Z'}}
'''
@payment_bp.post("/webhook")
@limiter.exempt  # Webhooks must be accepted without rate-limiting or auth
@csrf_protect.exempt
def handle_webhook():
    # Handle webhook events from Flutterwave
    from threading import Thread

    data = request.get_json()
    rawbody = request.get_data(as_text=True)
    print(rawbody)
    is_valid_webhook = is_valid_flutterwave_webhook(
        raw_body=rawbody,
        signature=request.headers.get("flutterwave-signature", ""),
        secret_hash=os.environ.get("FLUTTERWAVE_SECRET_HASH", "-")
    )
    if not is_valid_webhook:
        print("Not valid webhook")
        return jsonify(error="Invalid webhook signature"), 200

    print("\nData: \n",data)
    tx_id = data["data"]["id"]
    tx_ref = data["data"]["reference"]
    # flw_ref = data["data"]["flw_ref"]
    status = data["data"]["status"]
    amount = data["data"]["amount"]
    email = data["data"]["customer"]["email"]

    existing_tx = db.session.execute(db.select(Transaction).filter_by(tx_id=tx_id)).scalar_one_or_none()
    # Deduplication.
    if existing_tx:
        # Maybe it exists but its status has changed?
        if existing_tx.status.lower().startswith("succe") or\
            existing_tx.status.lower() == status.lower():
            return jsonify(error="Transaction already processed"), 200
    
    # If no previous transaction, create a new one.
    transaction = Transaction(
        status=status,
        amount=amount,
        tx_id=tx_id,
        tx_ref=tx_ref,
        flw_ref="dummy value", # webhook data does not actually contain this so I just leave it as a dummy for now.
        cust_email=email
    )
    db.session.add(transaction)
    db.session.commit()

    user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if user and status.lower() == "succeeded":
        now = datetime.now(timezone.utc)
        current_end = as_utc(user.access_until)

        # Extend from the current expiry if it's still in the future, otherwise from now
        base = current_end if current_end and current_end > now else now
        user.access_until = base + timedelta(days=app.config["ACCESS_DURATION_DAYS"])
        user.is_paid_user = True
        user.amount_paid = int(user.amount_paid or 0) + amount

        # Capture values now: the thread shouldn't touch the ORM object after the session ends
        cust_name, amount_str = user.name, str(amount)
        db.session.commit()

        # Send the receipt only after the commit succeeded
        Thread(target=send_receipt_email, kwargs=dict(
            email_dest=email,
            cust_name=cust_name,
            amount=amount_str,
            reason="Audio export support (2 weeks)",
        )).start()
    
    return jsonify(received=True), 200

@payment_bp.get("/status/<reference>")
def check_transfer_status(reference):
    ''' Endpoint for fetch request polling from the frontend'''
    # args = request.args
    # reference = args.get("reference")
    print(reference)
    if not reference:
        return jsonify(status="not found"), 404

    tx = db.session.execute(db.select(Transaction).filter_by(tx_ref=reference)).scalar_one_or_none()
    if not tx:
        return jsonify(status="not found"), 404
    
    # if tx.status.lower().startswith("succ"):
    return jsonify(status=tx.status.lower()), 200

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

app = create_app()
register_root_routes(app)

# ---------------------------------------------------------------------------
# audio conversion endpoint
# ---------------------------------------------------------------------------
from flask import send_file
from core.measure_to_audio import generate_wav

@app.post("/convert-audio")
@api_login_required
@json_required
def convert_to_audio():
    data = request.get_json()
    measure_string = data.get("measure_string", "").strip()
    tempo = data.get("tempo", 120)
    part = data.get("part", "S")
    key = data.get("key", "C")
    time_sig = data.get("time_sig", "4/4")

    if current_user.is_authenticated:
        if current_user.has_active_access or current_user.email in os.environ.get("ADMIN_EMAILS", "").split(","):
            wav_file = generate_wav(measure_string, key, time_sig, part, tempo, output_path=str(Path(__file__).parent / f"temp-{current_user.id}.wav"))
    
            return send_file(
                wav_file,
                mimetype="audio/wav",
                as_attachment=True,
                download_name="measure.wav"
            )
        return jsonify(error="Paid access required to convert measures to audio"), 403
    return jsonify(error="Authentication required"), 401


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_ENV") != "production")
