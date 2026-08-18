import os
import re
import uuid
import pytz
from datetime import datetime
from functools import wraps
from flask import Flask, request, session, jsonify, g, redirect
from flask_sqlalchemy import SQLAlchemy
from signalwire.rest import Client as SignalWireClient
from werkzeug.security import generate_password_hash, check_password_hash
from twilio.twiml.voice_response import VoiceResponse, Say, Hangup

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-prod')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SERVER_URL'] = os.environ.get('SERVER_URL', 'http://localhost:5000')

db = SQLAlchemy(app)

SIGNALWIRE_SPACE = os.environ.get('SIGNALWIRE_SPACE', '').strip()
SIGNALWIRE_PROJECT_ID = os.environ.get('SIGNALWIRE_PROJECT_ID', '').strip()
SIGNALWIRE_API_TOKEN = os.environ.get('SIGNALWIRE_API_TOKEN', '').strip()
sw_client = SignalWireClient(SIGNALWIRE_PROJECT_ID, SIGNALWIRE_API_TOKEN, signalwire_space_url=SIGNALWIRE_SPACE) if SIGNALWIRE_PROJECT_ID and SIGNALWIRE_API_TOKEN and SIGNALWIRE_SPACE else None

COUNTRY = 'US'  # USA-only for now
AREA_CODE = os.environ.get('SIGNALWIRE_AREA_CODE', '+1')  # USA default area code
# Price to charge per month (for display only — fake Stripe)
MONTHLY_PRICE = 29


# ── Models ────────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_active = db.Column(db.Boolean, default=False)
    subscription_start = db.Column(db.DateTime, nullable=True)
    twilio_number = db.Column(db.String(20), nullable=True)
    twilio_number_sid = db.Column(db.String(34), nullable=True)


class ClientConfig(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False, unique=True)
    business_number = db.Column(db.String(20), nullable=False)
    personal_number = db.Column(db.String(20), nullable=False)
    timezone = db.Column(db.String(50), default='UTC')
    working_days = db.Column(db.Text, default='0,1,2,3,4')  # CSV string
    working_hours_start = db.Column(db.String(5), default='09:00')
    working_hours_end = db.Column(db.String(5), default='18:00')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Helpers ───────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'not_logged_in'}), 401
        return f(*args, **kwargs)
    return wrapped


def require_active_subscription(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'not_logged_in'}), 401
        user = User.query.get(session['user_id'])
        if not user or not user.subscription_active:
            return jsonify({'error': 'no_active_subscription'}), 402
        return f(*args, **kwargs)
    return wrapped


def is_working_hours(cfg: ClientConfig) -> bool:
    tz_name = cfg.timezone or 'UTC'
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.UTC
    now = datetime.now(tz)
    try:
        days = [int(d.strip()) for d in cfg.working_days.split(',') if d.strip()]
    except Exception:
        days = [0, 1, 2, 3, 4]
    if now.weekday() not in days:
        return False
    now_str = now.strftime('%H:%M')
    return cfg.working_hours_start <= now_str <= cfg.working_hours_end


def format_time(tz_name: str) -> str:
    try:
        tz = pytz.timezone(tz_name or 'UTC')
    except Exception:
        tz = pytz.UTC
    return datetime.now(tz).strftime('%I:%M %p').lstrip('0') or 'unknown'


def validate_e164(phone: str) -> bool:
    """Accept +1-555-XXX-XXXX or +1555XXXXXXX or 1555XXXXXXX"""
    cleaned = re.sub(r'[^\d+]', '', phone)
    return bool(re.match(r'^\+?\d{10,15}$', cleaned))


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    if not name or not email or not password:
        return jsonify({'error': 'name_email_password_required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'password_too_short'}), 400
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return jsonify({'error': 'invalid_email'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'email_already_registered'}), 409
    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()
    session['user_id'] = user.id
    return jsonify({'ok': True, 'user': {'id': user.id, 'name': user.name, 'email': user.email}})


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    if not email or not password:
        return jsonify({'error': 'email_and_password_required'}), 400
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'invalid_credentials'}), 401
    session['user_id'] = user.id
    return jsonify({'ok': True, 'user': {'id': user.id, 'name': user.name, 'email': user.email}})


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'ok': True})


@app.route('/api/auth/me', methods=['GET'])
def me():
    if not session.get('user_id'):
        return jsonify({'not_logged_in': True}), 200
    user = User.query.get(session['user_id'])
    if not user:
        session.pop('user_id', None)
        return jsonify({'not_logged_in': True}), 200
    cfg = ClientConfig.query.filter_by(user_id=user.id).first()
    return jsonify({
        'user': {
            'id': user.id,
            'name': user.name,
            'email': user.email,
            'subscription_active': user.subscription_active,
            'subscription_start': user.subscription_start.isoformat() if user.subscription_start else None,
            'twilio_number': user.twilio_number,
        },
        'config': {
            'business_number': cfg.business_number if cfg else None,
            'personal_number': cfg.personal_number if cfg else None,
            'timezone': cfg.timezone if cfg else None,
            'working_days': cfg.working_days if cfg else None,
            'working_hours_start': cfg.working_hours_start if cfg else None,
            'working_hours_end': cfg.working_hours_end if cfg else None,
        } if cfg else None,
    })


# ── Subscription (fake Stripe) ────────────────────────────────────────────────

@app.route('/api/subscribe', methods=['POST'])
@login_required
def subscribe():
    """Fake Stripe: takes the payment token, marks subscription active, auto-starts the clock."""
    data = request.get_json(silent=True) or {}
    token = (data.get('payment_method_id') or data.get('token') or '').strip()
    if not token:
        return jsonify({'error': 'payment_token_required'}), 400
    # Fake Stripe: any non-empty token is a "success"
    user = User.query.get(session['user_id'])
    already_active = user.subscription_active
    user.subscription_active = True
    if not user.subscription_start:
        user.subscription_start = datetime.utcnow()
    db.session.commit()
    # Auto-provision SignalWire number if not already done
    try:
        provision_number(user)
    except Exception as e:
        app.logger.error(f'SignalWire provisioning failed for {user.email}: {e}')
    return jsonify({
        'ok': True,
        'subscription_active': True,
        'subscription_start': user.subscription_start.isoformat(),
        'message': 'Payment successful! Your Never Miss a Call service is now active.',
        'provisioned': bool(user.twilio_number),
    })


@app.route('/api/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    user = User.query.get(session['user_id'])
    user.subscription_active = False
    db.session.commit()
    return jsonify({'ok': True, 'subscription_active': False})


# ── Onboarding / Client Config ────────────────────────────────────────────────

@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    cfg = ClientConfig.query.filter_by(user_id=session['user_id']).first()
    if not cfg:
        return jsonify({'configured': False}), 200
    return jsonify({
        'configured': True,
        'business_number': cfg.business_number,
        'personal_number': cfg.personal_number,
        'timezone': cfg.timezone,
        'working_days': cfg.working_days,
        'working_hours_start': cfg.working_hours_start,
        'working_hours_end': cfg.working_hours_end,
        'twilio_number': cfg.user.twilio_number if cfg.user else None,
    })


@app.route('/api/config', methods=['POST'])
@require_active_subscription
def set_config():
    data = request.get_json(silent=True) or {}
    business_number = (data.get('business_number') or '').strip()
    personal_number = (data.get('personal_number') or '').strip()
    timezone = (data.get('timezone') or 'UTC').strip()
    working_days = data.get('working_days', [0, 1, 2, 3, 4])
    working_hours_start = (data.get('working_hours_start') or '09:00').strip()
    working_hours_end = (data.get('working_hours_end') or '18:00').strip()

    if not validate_e164(business_number):
        return jsonify({'error': 'invalid_business_number'}), 400
    if not validate_e164(personal_number):
        return jsonify({'error': 'invalid_personal_number'}), 400
    if not re.match(r'^[A-Za-z_/]+$', timezone):
        timezone = 'UTC'
    if isinstance(working_days, list):
        working_days = ','.join(str(d) for d in working_days)
    if not re.match(r'^\d{2}:\d{2}$', working_hours_start):
        working_hours_start = '09:00'
    if not re.match(r'^\d{2}:\d{2}$', working_hours_end):
        working_hours_end = '18:00'

    cfg = ClientConfig.query.filter_by(user_id=session['user_id']).first()
    if not cfg:
        cfg = ClientConfig(user_id=session['user_id'])
        db.session.add(cfg)
    cfg.business_number = business_number
    cfg.personal_number = personal_number
    cfg.timezone = timezone
    cfg.working_days = working_days
    cfg.working_hours_start = working_hours_start
    cfg.working_hours_end = working_hours_end
    db.session.commit()
    return jsonify({'ok': True, 'configured': True})


# ── SignalWire number provisioning ────────────────────────────────────────────

def provision_number(user: User):
    """Buy a SignalWire number for the user if they don't have one."""
    if user.twilio_number:
        return user.twilio_number
    if not sw_client:
        raise RuntimeError('SignalWire not configured')
    area = AREA_CODE.lstrip('+').replace('-', '')
    numbers = sw_client.phone_numbers.list(
        area_code=area,
        limit=5,
    )
    if not numbers:
        numbers = sw_client.phone_numbers.list(limit=5)
    if not numbers:
        raise RuntimeError('No SignalWire numbers available')
    num = numbers[0]
    num.update(voice_url=f'{app.config["SERVER_URL"]}/call/{user.id}')
    user.twilio_number = num.phone_number
    user.twilio_number_sid = num.sid
    db.session.commit()
    return num.phone_number


@app.route('/api/provision-number', methods=['POST'])
@require_active_subscription
def request_provision():
    user = User.query.get(session['user_id'])
    try:
        number = provision_number(user)
        return jsonify({
            'ok': True,
            'twilio_number': number,
            'message': f'Your Never Miss a Call number is {number}. Use this number everywhere instead of your old business number.',
        })
    except Exception as e:
        app.logger.error(f'Provisioning failed for {user.email}: {e}')
        return jsonify({'error': 'number_provisioning_failed', 'detail': str(e)}), 500


# ── Call webhook (SignalWire → our server) ────────────────────────────────────

@app.route('/call/<user_id>', methods=['POST'])
def handle_inbound_call(user_id: str):
    user = User.query.get(user_id)
    if not user:
        response = VoiceResponse()
        response.say('This number is not yet configured.')
        response.hangup()
        return str(response), 200, {'Content-Type': 'text/xml'}

    cfg = ClientConfig.query.filter_by(user_id=user_id).first()
    from_number = request.form.get('From', '').strip()

    if cfg and is_working_hours(cfg):
        # Working hours: forward to business number
        response = VoiceResponse()
        response.say('Connecting you now.')
        # SignalWire forwards directly to the business number
        response.number(cfg.business_number)
        return str(response), 200, {'Content-Type': 'text/xml'}

    # After hours: SMS personal number, do NOT ring business
    if cfg and cfg.personal_number and sw_client:
        time_str = format_time(cfg.timezone)
        caller_display = from_number if from_number else 'Unknown caller'
        message = (
            f'📞 Call from {caller_display} at {time_str} '
            f'outside working hours. Rang your Never Miss a Call number {user.twilio_number}. '
            f'Return call?'
        )
        try:
            sw_client.messages.create(
                to=cfg.personal_number,
                from_=user.twilio_number,
                body=message,
            )
            app.logger.info(f'SMS to {cfg.personal_number} for user {user_id}')
        except Exception as e:
            app.logger.error(f'SMS failed for {user_id}: {e}')

    response = VoiceResponse()
    response.say('Thanks for calling. We will have them return your call soon.')
    response.hangup()
    return str(response), 200, {'Content-Type': 'text/xml'}


# ── Dashboard data ────────────────────────────────────────────────────────────

@app.route('/api/dashboard', methods=['GET'])
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    cfg = ClientConfig.query.filter_by(user_id=user.id).first()
    return jsonify({
        'subscription_active': user.subscription_active,
        'twilio_number': user.twilio_number,
        'configured': bool(cfg),
        'business_number': cfg.business_number if cfg else None,
        'personal_number': cfg.personal_number if cfg else None,
        'timezone': cfg.timezone if cfg else None,
        'working_days': cfg.working_days if cfg else None,
        'working_hours_start': cfg.working_hours_start if cfg else None,
        'working_hours_end': cfg.working_hours_end if cfg else None,
    })


# ── Init DB ───────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
