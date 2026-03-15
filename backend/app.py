import sys
import os
import json
import logging
import requests  # Import requests for weather API
import random
import string
import sqlite3
import time
from functools import wraps
from datetime import datetime, timedelta  # Import datetime for blog post timestamps
from urllib.parse import quote_plus
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, g
import google.generativeai as genai
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from prompts import (
    generate_itinerary_prompt,
    format_itinerary_response,
    generate_packing_list_prompt,
    generate_day_replan_prompt,
    generate_trip_journal_prompt,
    parse_json_response,
)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_mail import Mail, Message
from flask_dance.contrib.google import make_google_blueprint, google

# Add the project root directory to the Python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# Load environment variables from project root .env (if present)
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

app = Flask(__name__, template_folder="templates", static_folder="static")

# Set up logging
logging.basicConfig(level=logging.INFO)

# Load API keys from environment variables (REQUIRED - no fallbacks for security)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "").strip()
ALLOW_INSECURE_UID_HEADER = os.getenv("ALLOW_INSECURE_UID_HEADER", "false").lower() in ("1", "true", "yes")
TICKETMASTER_API_KEY = os.getenv("TICKETMASTER_API_KEY", "").strip()
LIVE_PRICING_PROVIDER = os.getenv("LIVE_PRICING_PROVIDER", "amadeus").strip().lower()
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY", "").strip()
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET", "").strip()
LIVE_PRICING_ORIGIN = os.getenv("LIVE_PRICING_ORIGIN", "NYC").strip().upper() or "NYC"

_AMADEUS_TOKEN_CACHE = {
    "token": None,
    "expires_at": 0,
}

FIREBASE_HTTP_REQUEST = google_auth_requests.Request()

# Validate that API keys are set
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")
if not WEATHER_API_KEY:
    raise ValueError("WEATHER_API_KEY environment variable is required")
# Configure Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-pro-latest")  # Updated model name

# Rate limiting for Gemini API
API_CALL_HISTORY = []
MAX_CALLS_PER_MINUTE = 2  # Conservative limit for free tier
MAX_CALLS_PER_DAY = 50    # Conservative daily limit

DATABASE = os.path.join(os.path.dirname(__file__), '../Database/blog.db')

UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def init_db():
    """Initialize the database with the schema."""
    conn = get_db_connection()
    with open(os.path.join(os.path.dirname(__file__), 'schema.sql')) as f:
        conn.executescript(f.read())
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def check_rate_limit():
    """Check if we can make an API call based on rate limits."""
    global API_CALL_HISTORY
    current_time = datetime.now()

    # Remove calls older than 1 minute
    API_CALL_HISTORY = [call_time for call_time in API_CALL_HISTORY
                       if current_time - call_time < timedelta(minutes=1)]

    # Check per-minute limit
    if len(API_CALL_HISTORY) >= MAX_CALLS_PER_MINUTE:
        return False, "Rate limit exceeded. Please wait a moment before generating another itinerary."

    # Check daily limit (simplified - in production, use database)
    daily_calls = [call_time for call_time in API_CALL_HISTORY
                  if current_time - call_time < timedelta(days=1)]

    if len(daily_calls) >= MAX_CALLS_PER_DAY:
        return False, "Daily API limit reached. Please try again tomorrow."

    return True, None

def record_api_call():
    """Record an API call for rate limiting."""
    global API_CALL_HISTORY
    API_CALL_HISTORY.append(datetime.now())


def _extract_bearer_token():
    """Extract Firebase Bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return None

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1].strip()


def _verify_firebase_token(token):
    """Verify Firebase ID token and return claims dict or None."""
    try:
        audience = FIREBASE_PROJECT_ID or None
        claims = google_id_token.verify_firebase_token(
            token,
            FIREBASE_HTTP_REQUEST,
            audience=audience,
        )
        if not isinstance(claims, dict):
            return None

        if FIREBASE_PROJECT_ID and claims.get("aud") != FIREBASE_PROJECT_ID:
            logging.warning("Firebase token rejected due to audience mismatch.")
            return None

        return claims
    except Exception as verify_error:
        logging.warning(f"Firebase token verification failed: {verify_error}")
        return None


def _get_authenticated_user(optional=False):
    """Get authenticated Firebase user from token and cache it for the request."""
    if getattr(g, "auth_user", None):
        return g.auth_user

    token = _extract_bearer_token()
    if token:
        claims = _verify_firebase_token(token)
        if claims and claims.get("uid"):
            g.auth_user = {
                "uid": claims.get("uid"),
                "email": claims.get("email"),
                "claims": claims,
                "provider": "firebase-token",
            }
            return g.auth_user

    if ALLOW_INSECURE_UID_HEADER:
        insecure_uid = (request.headers.get("X-Firebase-UID") or request.args.get("uid") or "").strip()
        if insecure_uid:
            g.auth_user = {
                "uid": insecure_uid,
                "email": None,
                "claims": {},
                "provider": "insecure-header",
            }
            return g.auth_user

    if optional:
        return None
    return None


def _auth_error(message="Authentication required.", status_code=401):
    return jsonify({"error": message}), status_code


def _enforce_uid_ownership(target_uid):
    auth_user = _get_authenticated_user(optional=False)
    if not auth_user:
        return _auth_error()

    if str(auth_user.get("uid")) != str(target_uid):
        return _auth_error("Forbidden: resource ownership mismatch.", 403)

    return None


def firebase_auth_required(view_func):
    """Decorator for endpoints that require a verified Firebase user."""
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if not _get_authenticated_user(optional=False):
            return _auth_error()
        return view_func(*args, **kwargs)
    return _wrapped


def _coerce_positive_int(value):
    """Convert value to positive int; return None when invalid."""
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _normalized_email(value):
    """Normalize email-like input for case-insensitive matching."""
    return str(value or '').strip().lower()


def _table_columns(conn, table_name):
    """Return a set of column names for a SQLite table."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row['name']) for row in rows if row and row['name']}
    except Exception:
        return set()


def _serialize_saved_itinerary_row(row):
    """Convert a saved itinerary row to JSON-serializable dict with parsed JSON fields."""
    payload = dict(row)

    for field in ('preferences', 'itinerary_data'):
        if field not in payload:
            continue
        if not isinstance(payload[field], str):
            continue
        try:
            payload[field] = json.loads(payload[field])
        except (TypeError, json.JSONDecodeError):
            pass

    return payload


def _normalize_string_list(value, max_items=20):
    """Normalize tags/media payloads from list or comma-separated string."""
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    elif value is None:
        items = []
    else:
        items = [part.strip() for part in str(value).split(',') if part.strip()]

    if not items:
        return []

    unique = []
    seen = set()
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= max_items:
            break
    return unique


def _build_journal_draft_key(itinerary_id=None, destination=''):
    if itinerary_id:
        return f"itinerary:{itinerary_id}"

    normalized_destination = '-'.join(
        part for part in str(destination or '').lower().strip().split() if part
    )
    return f"destination:{normalized_destination or 'general'}"


def _normalize_places(places, fallback_places=None):
    """Normalize place objects and keep only valid entries."""
    normalized = []
    fallback_places = fallback_places or []

    for place in places or []:
        if not isinstance(place, dict):
            continue

        name = str(place.get('name', '')).strip()
        if not name:
            continue

        entry = {
            'name': name,
            'time': str(place.get('time', '')).strip() or 'Flexible timing',
            'description': str(place.get('description', '')).strip(),
            'cost_estimate': str(place.get('cost_estimate', '')).strip(),
        }

        lat = place.get('lat')
        lng = place.get('lng')
        try:
            if lat is not None and lng is not None:
                entry['lat'] = float(lat)
                entry['lng'] = float(lng)
        except (TypeError, ValueError):
            pass

        normalized.append(entry)

    if normalized:
        return normalized
    return fallback_places


def _normalize_food_recommendations(food_recommendations, fallback_food=None):
    """Normalize food recommendation objects and keep only valid entries."""
    normalized = []
    fallback_food = fallback_food or []

    for food in food_recommendations or []:
        if not isinstance(food, dict):
            continue

        name = str(food.get('name', '')).strip()
        if not name:
            continue

        normalized.append({
            'name': name,
            'cuisine': str(food.get('cuisine', '')).strip(),
            'price_range': str(food.get('price_range', '')).strip(),
            'meal': str(food.get('meal', '')).strip(),
        })

    if normalized:
        return normalized
    return fallback_food


def _select_replanned_day(payload, target_day):
    """Accept either a single day object or a payload containing a days list."""
    if not isinstance(payload, dict):
        return None

    if isinstance(payload.get('days'), list):
        day_candidates = [d for d in payload['days'] if isinstance(d, dict)]
        exact_match = next((d for d in day_candidates if _coerce_positive_int(d.get('day')) == target_day), None)
        if exact_match:
            return exact_match
        return day_candidates[0] if day_candidates else None

    return payload


def _normalize_replanned_day(payload, target_day, fallback_day):
    """Normalize a replanned day, preserving fallback values when AI omits fields."""
    selected = _select_replanned_day(payload, target_day)
    if not isinstance(selected, dict):
        return None

    fallback_day = fallback_day or {}
    normalized_day = {
        'day': target_day,
        'title': str(selected.get('title') or fallback_day.get('title') or f'Day {target_day}').strip(),
        'places': _normalize_places(selected.get('places'), fallback_day.get('places', [])),
        'food_recommendations': _normalize_food_recommendations(
            selected.get('food_recommendations'),
            fallback_day.get('food_recommendations', [])
        ),
        'tips': str(selected.get('tips') or fallback_day.get('tips') or '').strip(),
    }

    if not normalized_day['places']:
        return None

    return normalized_day

# Initialize the database when the app starts
# init_db()

app.secret_key = 'supersecretkey'  # Needed for session

# Hardcoded user for demo
users = {
    'admin': {
        'password': generate_password_hash('password123'),
        'email': 'admin@example.com'
    }
}

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
mail = Mail(app)

# Google OAuth config (load from environment variables)
app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

google_bp = make_google_blueprint(
    client_id=app.config["GOOGLE_OAUTH_CLIENT_ID"],
    client_secret=app.config["GOOGLE_OAUTH_CLIENT_SECRET"],
    scope=["profile", "email"],
    redirect_url="/profile"
)
app.register_blueprint(google_bp, url_prefix="/login")

@app.context_processor
def inject_user():
    # For Firebase auth, we'll handle login state in JavaScript
    # Keep Flask session support for backward compatibility
    return dict(logged_in=('user' in session), username=session.get('user'))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/firebase-test')
def firebase_test():
    """Route for testing Firebase authentication."""
    return render_template('firebase-test.html')

@app.route('/localhost-test')
def localhost_test():
    """Route for testing Firebase authentication on localhost."""
    return render_template('localhost-test.html')


@app.route('/api/auth-check', methods=['GET'])
def auth_check():
    """Return auth status based on verified Firebase token."""
    auth_user = _get_authenticated_user(optional=True)
    if auth_user:
        return jsonify({
            'authenticated': True,
            'uid': auth_user.get('uid'),
            'email': auth_user.get('email'),
            'provider': auth_user.get('provider', 'firebase-token')
        })

    return jsonify({'authenticated': False}), 401

# Profile and Wishlist API Routes
@app.route('/api/profile/<firebase_uid>', methods=['GET'])
@firebase_auth_required
def get_profile(firebase_uid):
    """Get user profile by Firebase UID."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    try:
        conn = get_db_connection()
        profile = conn.execute(
            'SELECT * FROM user_profiles WHERE firebase_uid = ?',
            (firebase_uid,)
        ).fetchone()
        conn.close()

        if profile:
            return jsonify(dict(profile))
        else:
            return jsonify({'error': 'Profile not found'}), 404
    except Exception as e:
        logging.error(f"Error getting profile: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/profile', methods=['POST'])
@firebase_auth_required
def create_profile():
    """Create a new user profile."""
    try:
        data = request.json or {}
        auth_user = _get_authenticated_user(optional=False)
        firebase_uid = auth_user['uid']
        email = auth_user.get('email') or data.get('email', '')
        profile_picture = str(data.get('profile_picture') or '').strip() or None

        if data.get('firebase_uid') and data.get('firebase_uid') != firebase_uid:
            return jsonify({'error': 'Forbidden: resource ownership mismatch.'}), 403

        conn = get_db_connection()

        existing = conn.execute(
            'SELECT * FROM user_profiles WHERE firebase_uid = ?',
            (firebase_uid,)
        ).fetchone()

        if existing:
            conn.close()
            return jsonify(dict(existing)), 200

        cursor = conn.execute(
                '''INSERT INTO user_profiles (firebase_uid, email, display_name, bio, profile_picture, travel_preferences)
                    VALUES (?, ?, ?, ?, ?, ?)''',
            (firebase_uid, email, data.get('display_name', ''),
                 data.get('bio', ''), profile_picture, data.get('travel_preferences', '{}'))
        )

        profile_id = cursor.lastrowid
        conn.commit()

        # Get the created profile
        profile = conn.execute(
            'SELECT * FROM user_profiles WHERE id = ?',
            (profile_id,)
        ).fetchone()
        conn.close()

        return jsonify(dict(profile)), 201
    except Exception as e:
        logging.error(f"Error creating profile: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/profile/<firebase_uid>', methods=['PUT'])
@firebase_auth_required
def update_profile(firebase_uid):
    """Update user profile."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    try:
        data = request.json or {}
        conn = get_db_connection()

        update_fields = []
        update_values = []

        if 'display_name' in data:
            update_fields.append('display_name = ?')
            update_values.append(data.get('display_name'))
        if 'bio' in data:
            update_fields.append('bio = ?')
            update_values.append(data.get('bio'))
        if 'travel_preferences' in data:
            update_fields.append('travel_preferences = ?')
            update_values.append(data.get('travel_preferences'))
        if 'profile_picture' in data:
            profile_picture = str(data.get('profile_picture') or '').strip() or None
            update_fields.append('profile_picture = ?')
            update_values.append(profile_picture)

        if not update_fields:
            conn.close()
            return jsonify({'error': 'No profile fields provided for update'}), 400

        update_fields.append('updated_at = CURRENT_TIMESTAMP')
        update_values.append(firebase_uid)

        conn.execute(
            f'''UPDATE user_profiles
               SET {', '.join(update_fields)}
               WHERE firebase_uid = ?''',
            tuple(update_values)
        )
        conn.commit()

        # Get the updated profile
        profile = conn.execute(
            'SELECT * FROM user_profiles WHERE firebase_uid = ?',
            (firebase_uid,)
        ).fetchone()

        if not profile:
            conn.close()
            return jsonify({'error': 'Profile not found'}), 404

        conn.close()

        return jsonify(dict(profile))
    except Exception as e:
        logging.error(f"Error updating profile: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/profile/<firebase_uid>/picture', methods=['POST'])
@firebase_auth_required
def upload_profile_picture(firebase_uid):
    """Upload and persist a profile picture for the authenticated user."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    if 'image' not in request.files:
        return jsonify({'error': 'image file is required'}), 400

    image_file = request.files['image']
    if not image_file or not image_file.filename:
        return jsonify({'error': 'image file is required'}), 400

    if not allowed_file(image_file.filename):
        return jsonify({'error': 'Unsupported file type'}), 400

    try:
        conn = get_db_connection()
        profile = conn.execute(
            'SELECT profile_picture FROM user_profiles WHERE firebase_uid = ?',
            (firebase_uid,)
        ).fetchone()

        if not profile:
            conn.close()
            return jsonify({'error': 'Profile not found'}), 404

        original_name = secure_filename(image_file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
        safe_uid = secure_filename(firebase_uid)
        filename = f"profile_{safe_uid}_{timestamp}_{original_name}"

        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles')
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, filename)
        image_file.save(file_path)
        profile_picture_url = '/' + file_path.replace('\\', '/')

        conn.execute(
            '''UPDATE user_profiles
               SET profile_picture = ?, updated_at = CURRENT_TIMESTAMP
               WHERE firebase_uid = ?''',
            (profile_picture_url, firebase_uid)
        )
        conn.commit()
        conn.close()

        previous_picture = str(profile['profile_picture'] or '').strip()
        if previous_picture.startswith('/static/uploads/profiles/'):
            previous_path = os.path.join(PROJECT_ROOT, previous_picture.lstrip('/').replace('/', os.sep))
            if os.path.isfile(previous_path):
                try:
                    os.remove(previous_path)
                except OSError:
                    pass

        return jsonify({
            'message': 'Profile picture updated.',
            'profile_picture': profile_picture_url,
        })
    except Exception as e:
        logging.error(f"Error uploading profile picture: {e}")
        return jsonify({'error': 'Failed to upload profile picture'}), 500

@app.route('/api/destinations', methods=['GET'])
def get_destinations():
    """Get all available destinations."""
    try:
        conn = get_db_connection()
        destinations = conn.execute('SELECT * FROM destinations ORDER BY name').fetchall()
        conn.close()

        return jsonify([dict(dest) for dest in destinations])
    except Exception as e:
        logging.error(f"Error getting destinations: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/wishlist/<firebase_uid>', methods=['GET'])
@firebase_auth_required
def get_wishlist(firebase_uid):
    """Get user's wishlist."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    try:
        conn = get_db_connection()

        # Get user profile first
        user = conn.execute(
            'SELECT id FROM user_profiles WHERE firebase_uid = ?',
            (firebase_uid,)
        ).fetchone()

        if not user:
            return jsonify([])

        # Get wishlist with destination details
        wishlist = conn.execute(
            '''SELECT w.*, d.name, d.description, d.category, d.image_url,
                      d.location, d.country, d.rating
               FROM wishlists w
               JOIN destinations d ON w.destination_id = d.id
               WHERE w.user_id = ?
               ORDER BY w.priority DESC, w.added_at DESC''',
            (user['id'],)
        ).fetchall()
        conn.close()

        return jsonify([dict(item) for item in wishlist])
    except Exception as e:
        logging.error(f"Error getting wishlist: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/wishlist', methods=['POST'])
@firebase_auth_required
def add_to_wishlist():
    """Add destination to user's wishlist."""
    try:
        data = request.json or {}
        auth_user = _get_authenticated_user(optional=False)
        user_uid = auth_user['uid']

        if data.get('user_uid') and data.get('user_uid') != user_uid:
            return jsonify({'error': 'Forbidden: resource ownership mismatch.'}), 403

        conn = get_db_connection()

        # Get user profile
        user = conn.execute(
            'SELECT id FROM user_profiles WHERE firebase_uid = ?',
            (user_uid,)
        ).fetchone()

        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Add to wishlist
        conn.execute(
            '''INSERT OR IGNORE INTO wishlists (user_id, destination_id, priority, notes)
               VALUES (?, ?, ?, ?)''',
            (user['id'], data.get('destination_id'),
             data.get('priority', 1), data.get('notes', ''))
        )
        conn.commit()
        conn.close()

        return jsonify({'message': 'Added to wishlist'}), 201
    except Exception as e:
        logging.error(f"Error adding to wishlist: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/wishlist/<firebase_uid>/<int:destination_id>', methods=['DELETE'])
@firebase_auth_required
def remove_from_wishlist(firebase_uid, destination_id):
    """Remove destination from user's wishlist."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    try:
        conn = get_db_connection()

        # Get user profile
        user = conn.execute(
            'SELECT id FROM user_profiles WHERE firebase_uid = ?',
            (firebase_uid,)
        ).fetchone()

        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Remove from wishlist
        conn.execute(
            'DELETE FROM wishlists WHERE user_id = ? AND destination_id = ?',
            (user['id'], destination_id)
        )
        conn.commit()
        conn.close()

        return jsonify({'message': 'Removed from wishlist'})
    except Exception as e:
        logging.error(f"Error removing from wishlist: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/destinations')
def destinations():
    """Route for the destinations page."""
    return render_template('destinations.html')

@app.route('/submit-contact', methods=['POST'])
def submit_contact():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    message = request.form.get('message', '').strip()

    if not name or not email or not message:
        return jsonify({"error": "All fields are required!"}), 400

    logging.info(f"Received contact form submission: Name={name}, Email={email}, Message={message}")
    return jsonify({"message": "Thank you for contacting us!"})

@app.route('/generate-itinerary', methods=['POST'])
def generate_itinerary():
    data = request.json

    # Check rate limits first
    can_proceed, rate_limit_error = check_rate_limit()
    if not can_proceed:
        return jsonify({"error": rate_limit_error}), 429

    # Validate required fields
    required_fields = ["destination", "budget", "duration", "purpose", "preferences"]
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({"error": f"Missing or invalid field: {field}"}), 400

    destination = data.get("destination", "").strip()
    budget = data.get("budget", "").strip()
    duration = data.get("duration", "").strip()
    purpose = data.get("purpose", "").strip()
    preferences = data.get("preferences", [])  # Keep preferences as a list

    logging.info(f"Generating itinerary for destination: {destination}")

    itinerary_data = None  # Raw JSON data for map rendering

    try:
        # Record the API call for rate limiting
        record_api_call()

        # Generate the prompt using the function from prompts.py
        prompt = generate_itinerary_prompt(destination, budget, duration, purpose, preferences)
        logging.info(f"Generated prompt (first 200 chars): {prompt[:200]}")

        # Get the response from the Gemini API with retry logic
        max_retries = 3
        itinerary_text = "No response from AI."
        for attempt in range(max_retries):
            try:
                response = model.generate_content(prompt)
                itinerary_text = response.text.strip() if response and response.text else "No response from AI."
                logging.info(f"Received response from Gemini API on attempt {attempt + 1}.")
                break
            except Exception as api_error:
                if "429" in str(api_error) or "quota" in str(api_error).lower():
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 15  # Progressive backoff: 15, 30, 45 seconds
                        logging.warning(f"Rate limit hit, waiting {wait_time} seconds before retry {attempt + 2}")
                        time.sleep(wait_time)
                        continue
                    else:
                        return jsonify({
                            "error": "API quota exceeded. Please try again later. The free tier has limited requests per day."
                        }), 429
                else:
                    raise api_error

        # Try to parse structured JSON for map data
        itinerary_data = parse_json_response(itinerary_text)

        # Format the itinerary using the function from prompts.py
        formatted_itinerary = format_itinerary_response(itinerary_text)

    except Exception as e:
        error_message = str(e)
        logging.error(f"Error generating itinerary: {error_message}")

        # Handle specific API errors
        if "429" in error_message or "quota" in error_message.lower():
            formatted_itinerary = """
            <div style="text-align: center; padding: 20px; background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #856404;">⚠️ API Limit Reached</h3>
                <p style="color: #856404; margin: 10px 0;">We've reached the daily limit for AI-generated itineraries.</p>
                <p style="color: #856404; margin: 10px 0;"><strong>What you can do:</strong></p>
                <ul style="color: #856404; text-align: left; max-width: 400px; margin: 0 auto;">
                    <li>Try again in a few hours</li>
                    <li>Use our destination guides in the meantime</li>
                    <li>Browse popular destinations for inspiration</li>
                </ul>
                <p style="color: #856404; margin-top: 15px; font-size: 14px;">
                    <em>This helps us keep the service free for everyone!</em>
                </p>
            </div>
            """
        else:
            formatted_itinerary = f"""
            <div style="text-align: center; padding: 20px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #721c24;">❌ Error Generating Itinerary</h3>
                <p style="color: #721c24;">We encountered an issue while creating your itinerary.</p>
                <p style="color: #721c24; font-size: 14px;">Please try again in a few moments.</p>
            </div>
            """

    result = {"itinerary": formatted_itinerary}
    if itinerary_data:
        result["itinerary_data"] = itinerary_data
    return jsonify(result)


@app.route('/generate-packing-list', methods=['POST'])
def generate_packing_list():
    """Generate an AI-powered packing list based on trip details."""
    data = request.json

    # Check rate limits
    can_proceed, rate_limit_error = check_rate_limit()
    if not can_proceed:
        return jsonify({"error": rate_limit_error}), 429

    destination = data.get("destination", "").strip()
    duration = data.get("duration", "").strip()
    purpose = data.get("purpose", "").strip()
    preferences = data.get("preferences", [])

    if not destination or not duration:
        return jsonify({"error": "Destination and duration are required"}), 400

    # Optionally fetch weather data for smarter packing suggestions
    weather_info = None
    try:
        weather_url = f"http://api.openweathermap.org/data/2.5/weather?q={destination}&appid={WEATHER_API_KEY}&units=metric"
        weather_response = requests.get(weather_url, timeout=5)
        if weather_response.status_code == 200:
            wd = weather_response.json()
            weather_info = {
                "temperature": wd["main"]["temp"],
                "description": wd["weather"][0]["description"],
                "humidity": wd["main"]["humidity"]
            }
    except Exception as e:
        logging.warning(f"Could not fetch weather for packing list: {e}")

    try:
        record_api_call()
        prompt = generate_packing_list_prompt(destination, duration, purpose, preferences, weather_info)

        response = model.generate_content(prompt)
        response_text = response.text.strip() if response and response.text else ""

        packing_data = parse_json_response(response_text)
        if packing_data and 'categories' in packing_data:
            return jsonify({"packing_list": packing_data})
        else:
            return jsonify({"error": "Could not parse packing list. Please try again."}), 500

    except Exception as e:
        error_message = str(e)
        logging.error(f"Error generating packing list: {error_message}")
        if "429" in error_message or "quota" in error_message.lower():
            return jsonify({"error": "API quota exceeded. Please try again later."}), 429
        return jsonify({"error": "Failed to generate packing list"}), 500


@app.route('/api/replan-day', methods=['POST'])
def replan_day():
    """Regenerate a single day in an existing itinerary based on user instruction."""
    data = request.json or {}

    can_proceed, rate_limit_error = check_rate_limit()
    if not can_proceed:
        return jsonify({"error": rate_limit_error}), 429

    itinerary_data = data.get('itinerary_data')
    day_number = data.get('day_number')
    instruction = str(data.get('instruction', '')).strip()

    if itinerary_data is None or day_number is None or not instruction:
        return jsonify({"error": "itinerary_data, day_number, and instruction are required."}), 400

    if len(instruction) < 5:
        return jsonify({"error": "Instruction must be at least 5 characters."}), 400

    if not isinstance(itinerary_data, dict) or not isinstance(itinerary_data.get('days'), list) or not itinerary_data['days']:
        return jsonify({"error": "itinerary_data must include a non-empty days list."}), 400

    try:
        day_number = int(day_number)
        if day_number < 1:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "day_number must be a positive integer."}), 400

    day_index = next(
        (idx for idx, day in enumerate(itinerary_data['days']) if _coerce_positive_int(day.get('day')) == day_number),
        None
    )

    if day_index is None:
        return jsonify({"error": f"Day {day_number} not found in itinerary."}), 404

    existing_day = itinerary_data['days'][day_index]
    destination = str(data.get('destination') or itinerary_data.get('destination') or '').strip() or 'Trip destination'
    budget = str(data.get('budget', '')).strip()
    purpose = str(data.get('purpose', '')).strip()
    preferences = data.get('preferences', [])
    if not isinstance(preferences, list):
        preferences = []

    try:
        record_api_call()
        prompt = generate_day_replan_prompt(
            destination=destination,
            day_number=day_number,
            current_day=existing_day,
            instruction=instruction,
            budget=budget,
            purpose=purpose,
            preferences=preferences,
        )

        response = model.generate_content(prompt)
        response_text = response.text.strip() if response and getattr(response, 'text', None) else ''
        parsed_day = parse_json_response(response_text)

        normalized_day = _normalize_replanned_day(parsed_day, day_number, existing_day)
        if not normalized_day:
            return jsonify({"error": "AI returned invalid day format. Please try again."}), 500

        updated_itinerary = json.loads(json.dumps(itinerary_data))
        updated_itinerary['days'][day_index] = normalized_day
        formatted_itinerary = format_itinerary_response(json.dumps(updated_itinerary))

        return jsonify({
            "message": "Day replanned successfully.",
            "day_number": day_number,
            "replanned_day": normalized_day,
            "itinerary_data": updated_itinerary,
            "itinerary": formatted_itinerary,
        })

    except Exception as e:
        error_message = str(e)
        logging.error(f"Error replanning day {day_number}: {error_message}")
        if "429" in error_message or "quota" in error_message.lower():
            return jsonify({"error": "API quota exceeded. Please try again later."}), 429
        return jsonify({"error": "Failed to replan day. Please try again."}), 500


# ==================== PHASE 2 - SHAREABLE ITINERARY LINKS ====================

def ensure_phase2_tables():
    """Create Phase 2 tables if they don't exist."""
    conn = get_db_connection()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS saved_itineraries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT,
            share_token TEXT UNIQUE NOT NULL,
            destination TEXT NOT NULL,
            duration TEXT,
            budget TEXT,
            purpose TEXT,
            preferences TEXT,
            itinerary_html TEXT NOT NULL,
            itinerary_data TEXT,
            is_public INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS trip_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT NOT NULL,
            itinerary_id INTEGER,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            date TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
        CREATE TABLE IF NOT EXISTS digital_passport (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT NOT NULL,
            country TEXT NOT NULL,
            country_code TEXT,
            visited_date TEXT,
            trip_notes TEXT,
            stamp_type TEXT DEFAULT 'visited',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(firebase_uid, country, stamp_type)
        );
        CREATE TABLE IF NOT EXISTS packing_list_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT NOT NULL,
            trip_key TEXT NOT NULL,
            itinerary_id INTEGER,
            packing_data TEXT,
            checked_state TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(firebase_uid, trip_key),
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
        CREATE TABLE IF NOT EXISTS itinerary_collaborators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            itinerary_id INTEGER NOT NULL,
            collaborator_uid TEXT,
            invited_email TEXT,
            invited_by_uid TEXT NOT NULL,
            status TEXT DEFAULT 'accepted',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(itinerary_id, collaborator_uid),
            UNIQUE(itinerary_id, invited_email),
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
        CREATE TABLE IF NOT EXISTS itinerary_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            itinerary_id INTEGER NOT NULL,
            actor_uid TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
        CREATE TABLE IF NOT EXISTS itinerary_presence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            itinerary_id INTEGER NOT NULL,
            firebase_uid TEXT NOT NULL,
            email TEXT,
            status TEXT DEFAULT 'viewing',
            cursor_context TEXT,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(itinerary_id, firebase_uid),
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
        CREATE TABLE IF NOT EXISTS trip_journal_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT NOT NULL,
            itinerary_id INTEGER,
            draft_key TEXT NOT NULL,
            destination TEXT,
            title TEXT,
            content TEXT,
            tags TEXT,
            media_urls TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(firebase_uid, draft_key),
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
        CREATE TABLE IF NOT EXISTS trip_journal_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            firebase_uid TEXT NOT NULL,
            itinerary_id INTEGER,
            title TEXT,
            content TEXT,
            tags TEXT,
            media_urls TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (draft_id) REFERENCES trip_journal_drafts (id),
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
        CREATE TABLE IF NOT EXISTS user_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_uid TEXT,
            recipient_email TEXT,
            actor_uid TEXT,
            itinerary_id INTEGER,
            notification_type TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata TEXT,
            is_read INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
        );
    ''')

    # Lightweight migrations for sync/presence features.
    saved_itinerary_columns = _table_columns(conn, 'saved_itineraries')
    if 'revision' not in saved_itinerary_columns:
        conn.execute('ALTER TABLE saved_itineraries ADD COLUMN revision INTEGER DEFAULT 1')
    if 'last_editor_uid' not in saved_itinerary_columns:
        conn.execute('ALTER TABLE saved_itineraries ADD COLUMN last_editor_uid TEXT')

    user_profile_columns = _table_columns(conn, 'user_profiles')
    if user_profile_columns and 'profile_picture' not in user_profile_columns:
        conn.execute('ALTER TABLE user_profiles ADD COLUMN profile_picture TEXT')

    conn.execute(
        '''CREATE INDEX IF NOT EXISTS idx_itinerary_presence_recent
           ON itinerary_presence (itinerary_id, last_seen)'''
    )
    conn.execute(
        '''CREATE INDEX IF NOT EXISTS idx_journal_drafts_owner
           ON trip_journal_drafts (firebase_uid, updated_at DESC)'''
    )
    conn.execute(
        '''CREATE INDEX IF NOT EXISTS idx_journal_versions_draft
           ON trip_journal_versions (draft_id, created_at DESC)'''
    )
    conn.execute(
        '''CREATE INDEX IF NOT EXISTS idx_notifications_recipient_uid
           ON user_notifications (recipient_uid, is_read, created_at DESC)'''
    )
    conn.execute(
        '''CREATE INDEX IF NOT EXISTS idx_notifications_recipient_email
           ON user_notifications (recipient_email, is_read, created_at DESC)'''
    )

    conn.commit()
    conn.close()

# Auto-create Phase 2 tables on startup
ensure_phase2_tables()


def generate_share_token():
    """Generate a unique share token."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


def _resolve_itinerary_access(conn, itinerary_id, requester_uid):
    """Return itinerary row and access flags for owner/collaborator."""
    itinerary = conn.execute(
        'SELECT * FROM saved_itineraries WHERE id = ?',
        (itinerary_id,)
    ).fetchone()

    if not itinerary:
        return None, False, False

    is_owner = str(itinerary['firebase_uid'] or '') == str(requester_uid)
    if is_owner:
        return itinerary, True, True

    collaborator = conn.execute(
        '''SELECT id
           FROM itinerary_collaborators
           WHERE itinerary_id = ?
             AND collaborator_uid = ?
             AND status = 'accepted' ''',
        (itinerary_id, requester_uid)
    ).fetchone()

    return itinerary, bool(collaborator), False


def _log_itinerary_activity(conn, itinerary_id, actor_uid, action, details=None):
    """Write an itinerary activity event."""
    if isinstance(details, (dict, list)):
        details_text = json.dumps(details)
    elif details is None:
        details_text = None
    else:
        details_text = str(details)

    conn.execute(
        '''INSERT INTO itinerary_activity_log (itinerary_id, actor_uid, action, details)
           VALUES (?, ?, ?, ?)''',
        (itinerary_id, actor_uid, action, details_text)
    )


def _create_user_notification(
    conn,
    *,
    recipient_uid=None,
    recipient_email=None,
    actor_uid=None,
    itinerary_id=None,
    notification_type='info',
    message='',
    metadata=None,
):
    if not message:
        return

    normalized_uid = str(recipient_uid or '').strip() or None
    normalized_email = _normalized_email(recipient_email)
    if normalized_email == '':
        normalized_email = None

    if not normalized_uid and not normalized_email:
        return

    if isinstance(metadata, (dict, list)):
        metadata_text = json.dumps(metadata)
    elif metadata is None:
        metadata_text = None
    else:
        metadata_text = str(metadata)

    conn.execute(
        '''INSERT INTO user_notifications
           (recipient_uid, recipient_email, actor_uid, itinerary_id, notification_type, message, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            normalized_uid,
            normalized_email,
            str(actor_uid or '').strip() or None,
            itinerary_id,
            str(notification_type or 'info').strip() or 'info',
            str(message).strip(),
            metadata_text,
        )
    )


def _normalize_presence_cursor(value):
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return json.dumps(value)

    text = str(value).strip()
    return text or None


def _decode_presence_cursor(value):
    if not value:
        return None

    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _prune_itinerary_presence(conn):
    # Keep only recent heartbeat rows to avoid unbounded growth.
    conn.execute(
        "DELETE FROM itinerary_presence WHERE last_seen < datetime('now', '-5 minutes')"
    )


def _list_active_itinerary_presence(conn, itinerary_id):
    rows = conn.execute(
        '''SELECT firebase_uid, email, status, cursor_context, last_seen
           FROM itinerary_presence
           WHERE itinerary_id = ?
             AND last_seen >= datetime('now', '-90 seconds')
           ORDER BY last_seen DESC''',
        (itinerary_id,)
    ).fetchall()

    active = []
    for row in rows:
        entry = dict(row)
        entry['cursor_context'] = _decode_presence_cursor(entry.get('cursor_context'))
        active.append(entry)
    return active


def _iso_timestamp_now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _build_price_deep_links(destination):
    return {
        "flight_link": f"https://www.aviasales.com/search?destination={quote_plus(destination)}",
        "hotel_link": f"https://search.hotellook.com/?destination={quote_plus(destination)}",
    }


def _parse_price_value(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed > 0 else None

    cleaned = str(value).strip().replace(',', '')
    if not cleaned:
        return None

    try:
        parsed = float(cleaned)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _get_amadeus_access_token():
    """Return a cached Amadeus access token when credentials are configured."""
    if not AMADEUS_API_KEY or not AMADEUS_API_SECRET:
        return None

    now = time.time()
    cached_token = _AMADEUS_TOKEN_CACHE.get("token")
    cached_expiry = _AMADEUS_TOKEN_CACHE.get("expires_at", 0)
    if cached_token and now < cached_expiry:
        return cached_token

    try:
        resp = requests.post(
            "https://test.api.amadeus.com/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": AMADEUS_API_KEY,
                "client_secret": AMADEUS_API_SECRET,
            },
            timeout=6,
        )
        if resp.status_code != 200:
            logging.warning(f"Amadeus token request failed: {resp.status_code}")
            return None

        payload = resp.json()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            return None

        expires_in = _coerce_positive_int(payload.get("expires_in")) or 1500
        # Keep a safety window so we refresh before token expiration.
        _AMADEUS_TOKEN_CACHE["token"] = token
        _AMADEUS_TOKEN_CACHE["expires_at"] = now + max(expires_in - 45, 60)
        return token
    except Exception as token_error:
        logging.warning(f"Amadeus auth failed: {token_error}")
        return None


def _resolve_amadeus_city_code(destination, token):
    """Resolve destination name to Amadeus city IATA code."""
    try:
        resp = requests.get(
            "https://test.api.amadeus.com/v1/reference-data/locations",
            params={
                "keyword": destination,
                "subType": "CITY",
                "page[limit]": 1,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=6,
        )
        if resp.status_code != 200:
            return None

        payload = resp.json()
        rows = payload.get("data") or []
        if not rows:
            return None

        return str(rows[0].get("iataCode") or "").strip().upper() or None
    except Exception as city_error:
        logging.warning(f"Amadeus city lookup failed: {city_error}")
        return None


def _extract_min_flight_price(payload):
    prices = []
    for offer in payload.get("data") or []:
        price = offer.get("price") if isinstance(offer, dict) else {}
        total = _parse_price_value((price or {}).get("grandTotal"))
        if total is None:
            total = _parse_price_value((price or {}).get("total"))
        if total is not None:
            prices.append(total)

    if not prices:
        return None
    return min(prices)


def _extract_min_hotel_total(payload):
    totals = []
    for hotel in payload.get("data") or []:
        offers = hotel.get("offers") if isinstance(hotel, dict) else []
        for offer in offers or []:
            price = offer.get("price") if isinstance(offer, dict) else {}
            total = _parse_price_value((price or {}).get("total"))
            if total is not None:
                totals.append(total)

    if not totals:
        return None
    return min(totals)


def _fetch_amadeus_live_price_hints(destination, duration_days=3, currency='USD'):
    """Fetch near-real-time flight and hotel quote hints from Amadeus APIs."""
    token = _get_amadeus_access_token()
    if not token:
        return None

    city_code = _resolve_amadeus_city_code(destination, token)
    if not city_code:
        return None

    duration_days = max(1, min(duration_days, 30))
    departure_date = (datetime.utcnow() + timedelta(days=45)).date()
    check_in = departure_date
    check_out = check_in + timedelta(days=duration_days)

    headers = {"Authorization": f"Bearer {token}"}

    min_flight = None
    min_hotel_total = None

    try:
        flight_resp = requests.get(
            "https://test.api.amadeus.com/v2/shopping/flight-offers",
            params={
                "originLocationCode": LIVE_PRICING_ORIGIN,
                "destinationLocationCode": city_code,
                "departureDate": departure_date.isoformat(),
                "adults": 1,
                "currencyCode": currency,
                "max": 8,
            },
            headers=headers,
            timeout=7,
        )
        if flight_resp.status_code == 200:
            min_flight = _extract_min_flight_price(flight_resp.json())
    except Exception as flight_error:
        logging.warning(f"Live flight quotes failed: {flight_error}")

    try:
        hotel_list_resp = requests.get(
            "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city",
            params={"cityCode": city_code},
            headers=headers,
            timeout=7,
        )
        hotel_ids = []
        if hotel_list_resp.status_code == 200:
            for row in hotel_list_resp.json().get("data") or []:
                hid = str(row.get("hotelId") or "").strip()
                if hid:
                    hotel_ids.append(hid)
                if len(hotel_ids) >= 10:
                    break

        if hotel_ids:
            offers_resp = requests.get(
                "https://test.api.amadeus.com/v3/shopping/hotel-offers",
                params={
                    "hotelIds": ','.join(hotel_ids),
                    "checkInDate": check_in.isoformat(),
                    "checkOutDate": check_out.isoformat(),
                    "adults": 1,
                    "roomQuantity": 1,
                    "currency": currency,
                },
                headers=headers,
                timeout=7,
            )
            if offers_resp.status_code == 200:
                min_hotel_total = _extract_min_hotel_total(offers_resp.json())
    except Exception as hotel_error:
        logging.warning(f"Live hotel quotes failed: {hotel_error}")

    if min_flight is None and min_hotel_total is None:
        return None

    links = _build_price_deep_links(destination)
    nightly = None
    if min_hotel_total is not None:
        nightly = min_hotel_total / max(duration_days, 1)

    return {
        "destination": destination,
        "currency": currency,
        "flight_from": round(min_flight, 2) if min_flight is not None else None,
        "hotel_from_per_night": round(nightly, 2) if nightly is not None else None,
        "hotel_estimated_total": round(min_hotel_total, 2) if min_hotel_total is not None else None,
        "flight_link": links["flight_link"],
        "hotel_link": links["hotel_link"],
        "source": "live-amadeus",
        "quoted_at": _iso_timestamp_now(),
        "note": "Live provider-backed quote hints. Final booking prices can change at checkout.",
    }


def _fetch_live_provider_price_hints(destination, duration_days=3, currency='USD'):
    if LIVE_PRICING_PROVIDER == 'amadeus':
        return _fetch_amadeus_live_price_hints(destination, duration_days, currency)
    return None


def _merge_price_hints(estimate_hints, live_hints):
    """Merge live quote payload over fallback estimation while preserving required fields."""
    if not live_hints:
        return estimate_hints

    merged = dict(estimate_hints)
    for key, value in live_hints.items():
        if value is not None and value != '':
            merged[key] = value

    merged['is_live'] = bool(str(merged.get('source', '')).startswith('live-'))
    return merged


def _estimate_price_hints(destination, duration_days=3, currency='USD'):
    """Build practical price hint estimates and deep links for booking research."""
    seed = sum(ord(char) for char in destination.lower())
    duration_days = max(1, min(duration_days, 30))

    flight_estimate = 220 + (seed % 520)
    hotel_nightly = 55 + (seed % 170)
    total_hotel = hotel_nightly * duration_days

    links = _build_price_deep_links(destination)
    return {
        "destination": destination,
        "currency": currency,
        "flight_from": round(flight_estimate, 2),
        "hotel_from_per_night": round(hotel_nightly, 2),
        "hotel_estimated_total": round(total_hotel, 2),
        "flight_link": links["flight_link"],
        "hotel_link": links["hotel_link"],
        "note": "Indicative price hints only. Final prices vary by date and availability.",
        "source": "estimation",
        "quoted_at": _iso_timestamp_now(),
        "is_live": False,
    }


def _geocode_destination(destination):
    """Resolve destination to lat/lng via OpenStreetMap Nominatim."""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": destination, "format": "json", "limit": 1},
            headers={"User-Agent": "ITENARO/1.0"},
            timeout=5,
        )
        if resp.status_code != 200:
            return None

        payload = resp.json()
        if not payload:
            return None

        return {
            "lat": float(payload[0].get("lat")),
            "lng": float(payload[0].get("lon")),
        }
    except Exception:
        return None


def _generate_fallback_events(destination, start_date=None, end_date=None):
    """Generate local fallback events so the map panel is still useful without external API keys."""
    center = _geocode_destination(destination) or {"lat": 20.5937, "lng": 78.9629}
    categories = ["music", "food", "culture", "sports", "community"]
    template_names = [
        "Night Market Walk",
        "Live Acoustic Session",
        "Street Food Crawl",
        "Cultural Craft Fair",
        "Sunset Community Run",
    ]
    events = []

    for idx, name in enumerate(template_names):
        day_suggestion = (idx % 3) + 1
        events.append({
            "id": f"fallback-{idx + 1}",
            "name": f"{destination} {name}",
            "category": categories[idx % len(categories)],
            "start_time": f"Day {day_suggestion}, {6 + idx}:00 PM",
            "venue": f"{destination} Central District",
            "url": f"https://www.ticketmaster.com/search?q={quote_plus(destination + ' ' + name)}",
            "lat": center["lat"] + ((idx - 2) * 0.01),
            "lng": center["lng"] + ((2 - idx) * 0.01),
            "description": "Community-curated local event suggestion.",
            "day_suggestion": day_suggestion,
            "price_hint": "Varies",
            "source": "fallback",
            "start_date": start_date,
            "end_date": end_date,
        })

    return events


def _fetch_ticketmaster_events(destination, start_date=None, end_date=None):
    """Fetch events from Ticketmaster Discovery API when key is configured."""
    if not TICKETMASTER_API_KEY:
        return []

    try:
        params = {
            "apikey": TICKETMASTER_API_KEY,
            "city": destination,
            "size": 20,
            "sort": "date,asc",
        }
        if start_date:
            params["startDateTime"] = f"{start_date}T00:00:00Z"
        if end_date:
            params["endDateTime"] = f"{end_date}T23:59:59Z"

        resp = requests.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params=params,
            timeout=6,
        )
        if resp.status_code != 200:
            return []

        payload = resp.json()
        raw_events = payload.get("_embedded", {}).get("events", [])
        events = []

        for idx, event in enumerate(raw_events):
            venue = (event.get("_embedded", {}).get("venues") or [{}])[0]
            location = venue.get("location", {}) if isinstance(venue, dict) else {}
            classifications = event.get("classifications") or []
            segment = (classifications[0].get("segment", {}) if classifications else {})
            category = str(segment.get("name", "other")).lower()

            events.append({
                "id": event.get("id") or f"tm-{idx}",
                "name": event.get("name", "Event"),
                "category": category,
                "start_time": event.get("dates", {}).get("start", {}).get("localDate", "TBD"),
                "venue": venue.get("name", "Venue TBA") if isinstance(venue, dict) else "Venue TBA",
                "url": event.get("url", ""),
                "lat": float(location.get("latitude")) if location.get("latitude") else None,
                "lng": float(location.get("longitude")) if location.get("longitude") else None,
                "description": event.get("info") or event.get("pleaseNote") or "",
                "day_suggestion": (idx % 3) + 1,
                "price_hint": "Ticketed",
                "source": "ticketmaster",
            })

        return events
    except Exception as fetch_error:
        logging.warning(f"Ticketmaster fetch failed: {fetch_error}")
        return []


def _extract_itinerary_highlights(itinerary_data, max_items=6):
    """Derive concise day-level highlights from itinerary data."""
    highlights = []
    days = itinerary_data.get('days') if isinstance(itinerary_data, dict) else []
    if not isinstance(days, list):
        return highlights

    for day in days:
        if not isinstance(day, dict):
            continue

        day_number = _coerce_positive_int(day.get('day')) or (len(highlights) + 1)
        title = str(day.get('title') or f"Day {day_number}").strip()

        place_names = []
        for place in day.get('places') or []:
            if not isinstance(place, dict):
                continue
            name = str(place.get('name') or '').strip()
            if name:
                place_names.append(name)
            if len(place_names) >= 2:
                break

        if place_names:
            highlights.append(f"Day {day_number}: {title} - {', '.join(place_names)}")
        else:
            highlights.append(f"Day {day_number}: {title}")

        if len(highlights) >= max_items:
            break

    return highlights


def _build_fallback_trip_journal(destination, purpose, itinerary_data):
    """Create a local recap when AI output is unavailable or malformed."""
    destination = str(destination or itinerary_data.get('destination') or 'your trip').strip()
    purpose_text = str(purpose or '').strip()
    summary = str(itinerary_data.get('summary') or '').strip() if isinstance(itinerary_data, dict) else ''
    highlights = _extract_itinerary_highlights(itinerary_data, max_items=5)

    intro = f"I recently explored {destination} and the trip felt thoughtfully paced from start to finish."
    if purpose_text:
        intro = f"I recently explored {destination} for a {purpose_text.lower()} trip, and each day felt purposeful."

    recap_parts = [summary or intro]
    if highlights:
        recap_parts.append("Key moments included " + "; ".join(highlights[:3]) + ".")
    recap_parts.append(
        "What stood out most was how the plan balanced iconic spots with local experiences while still leaving room for spontaneity."
    )

    recap = " ".join(part.strip() for part in recap_parts if part and part.strip())
    return {
        'title': f"{destination} Trip Journal",
        'recap': recap,
        'highlights': highlights or [f"Explored {destination} with a structured day-by-day plan."],
        'takeaway': "A flexible plan made the trip more memorable and less stressful.",
    }


@app.route('/api/save-itinerary', methods=['POST'])
@firebase_auth_required
def save_itinerary():
    """Save an itinerary and generate a shareable link."""
    data = request.json or {}
    auth_user = _get_authenticated_user(optional=False)
    share_token = generate_share_token()

    destination = str(data.get('destination', '')).strip()
    itinerary_html = str(data.get('itinerary_html', '')).strip()

    if not destination or not itinerary_html:
        return jsonify({"error": "destination and itinerary_html are required"}), 400

    try:
        conn = get_db_connection()
        saved_columns = _table_columns(conn, 'saved_itineraries')

        insert_fields = [
            'firebase_uid',
            'share_token',
            'destination',
            'duration',
            'budget',
            'purpose',
            'preferences',
            'itinerary_html',
            'itinerary_data',
            'is_public',
        ]
        insert_values = [
            auth_user['uid'],
            share_token,
            destination,
            data.get('duration', ''),
            data.get('budget', ''),
            data.get('purpose', ''),
            json.dumps(data.get('preferences', [])),
            itinerary_html,
            json.dumps(data.get('itinerary_data', {})),
            1 if data.get('is_public', True) else 0,
        ]

        if 'revision' in saved_columns:
            insert_fields.append('revision')
            insert_values.append(1)
        if 'last_editor_uid' in saved_columns:
            insert_fields.append('last_editor_uid')
            insert_values.append(auth_user['uid'])

        placeholders = ', '.join(['?'] * len(insert_fields))
        cursor = conn.execute(
            f'''INSERT INTO saved_itineraries
                ({', '.join(insert_fields)})
                VALUES ({placeholders})''',
            insert_values,
        )

        itinerary_id = cursor.lastrowid
        revision = 1
        if 'revision' in saved_columns:
            revision_row = conn.execute(
                'SELECT revision FROM saved_itineraries WHERE id = ?',
                (itinerary_id,)
            ).fetchone()
            revision = _coerce_positive_int(revision_row['revision']) if revision_row else 1
            revision = revision or 1

        _log_itinerary_activity(
            conn,
            itinerary_id,
            auth_user['uid'],
            'create_itinerary',
            {'destination': destination}
        )

        conn.commit()
        conn.close()

        share_url = f"{request.host_url}shared/{share_token}"
        return jsonify({
            "itinerary_id": itinerary_id,
            "revision": revision,
            "share_token": share_token,
            "share_url": share_url,
            "message": "Itinerary saved successfully!"
        }), 201
    except Exception as e:
        logging.error(f"Error saving itinerary: {e}")
        return jsonify({"error": "Failed to save itinerary"}), 500


@app.route('/shared/<share_token>')
def view_shared_itinerary(share_token):
    """View a shared itinerary by its token."""
    try:
        conn = get_db_connection()
        itinerary = conn.execute(
            'SELECT * FROM saved_itineraries WHERE share_token = ? AND is_public = 1',
            (share_token,)
        ).fetchone()
        conn.close()

        if not itinerary:
            return "Itinerary not found or is not public.", 404

        return render_template('shared_itinerary.html', itinerary=dict(itinerary))
    except Exception as e:
        logging.error(f"Error viewing shared itinerary: {e}")
        return "Error loading itinerary", 500


@app.route('/api/shared/<share_token>', methods=['GET'])
def get_shared_itinerary_data(share_token):
    """Get shared itinerary data as JSON."""
    try:
        conn = get_db_connection()
        itinerary = conn.execute(
            'SELECT * FROM saved_itineraries WHERE share_token = ? AND is_public = 1',
            (share_token,)
        ).fetchone()
        conn.close()

        if not itinerary:
            return jsonify({"error": "Itinerary not found"}), 404

        result = dict(itinerary)
        # Parse JSON fields
        if result.get('itinerary_data'):
            try:
                result['itinerary_data'] = json.loads(result['itinerary_data'])
            except (json.JSONDecodeError, TypeError):
                pass
        if result.get('preferences'):
            try:
                result['preferences'] = json.loads(result['preferences'])
            except (json.JSONDecodeError, TypeError):
                pass

        return jsonify(result)
    except Exception as e:
        logging.error(f"Error getting shared itinerary: {e}")
        return jsonify({"error": "Internal error"}), 500


@app.route('/api/my-itineraries/<firebase_uid>', methods=['GET'])
@firebase_auth_required
def get_my_itineraries(firebase_uid):
    """Get all saved itineraries for a user."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    try:
        conn = get_db_connection()
        select_fields = [
            'id',
            'share_token',
            'destination',
            'duration',
            'budget',
            'purpose',
            'is_public',
            'created_at',
        ]
        if 'revision' in _table_columns(conn, 'saved_itineraries'):
            select_fields.append('revision')

        itineraries = conn.execute(
            f"SELECT {', '.join(select_fields)} FROM saved_itineraries WHERE firebase_uid = ? ORDER BY created_at DESC",
            (firebase_uid,)
        ).fetchall()
        conn.close()
        return jsonify([dict(row) for row in itineraries])
    except Exception as e:
        logging.error(f"Error getting user itineraries: {e}")
        return jsonify({"error": "Internal error"}), 500


@app.route('/api/my-shared-itineraries', methods=['GET'])
@firebase_auth_required
def get_my_shared_itineraries():
    """List itineraries shared with the authenticated user by UID or invited email."""
    auth_user = _get_authenticated_user(optional=False)
    requester_uid = str(auth_user.get('uid') or '').strip()
    requester_email = _normalized_email(auth_user.get('email'))

    try:
        conn = get_db_connection()
        rows = conn.execute(
            '''SELECT s.id,
                      s.share_token,
                      s.destination,
                      s.duration,
                      s.budget,
                      s.purpose,
                      s.firebase_uid AS owner_uid,
                      c.status,
                      c.invited_email,
                      c.collaborator_uid,
                      c.created_at AS invited_at
               FROM itinerary_collaborators c
               JOIN saved_itineraries s ON s.id = c.itinerary_id
               WHERE (
                     c.collaborator_uid = ?
                  OR (? != '' AND LOWER(COALESCE(c.invited_email, '')) = ?)
               )
                 AND c.status IN ('pending', 'accepted')
               ORDER BY c.created_at DESC''',
            (requester_uid, requester_email, requester_email)
        ).fetchall()
        conn.close()

        result = []
        for row in rows:
            item = dict(row)
            item['can_accept'] = bool(
                item.get('status') == 'pending'
                and requester_email
                and _normalized_email(item.get('invited_email')) == requester_email
            )
            item['can_decline'] = bool(
                item.get('status') == 'pending'
                and (
                    (requester_uid and str(item.get('collaborator_uid') or '') == requester_uid)
                    or (requester_email and _normalized_email(item.get('invited_email')) == requester_email)
                )
            )
            item['can_leave'] = bool(
                item.get('status') == 'accepted'
                and requester_uid
                and str(item.get('collaborator_uid') or '') == requester_uid
                and str(item.get('owner_uid') or '') != requester_uid
            )
            result.append(item)

        return jsonify({"itineraries": result})
    except Exception as e:
        logging.error(f"Error getting shared itineraries: {e}")
        return jsonify({"error": "Failed to load shared itineraries"}), 500


@app.route('/api/notifications', methods=['GET'])
@firebase_auth_required
def get_my_notifications():
    """Fetch notification inbox for the authenticated user (uid + email targets)."""
    auth_user = _get_authenticated_user(optional=False)
    requester_uid = str(auth_user.get('uid') or '').strip()
    requester_email = _normalized_email(auth_user.get('email'))
    unread_only = str(request.args.get('unread_only', '')).strip().lower() in {'1', 'true', 'yes'}
    status_filter = str(request.args.get('status', 'all')).strip().lower()
    notification_type = str(request.args.get('notification_type', '')).strip().lower()
    limit = _coerce_positive_int(request.args.get('limit')) or 30
    try:
        offset = max(0, int(request.args.get('offset', 0) or 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, 100))

    try:
        conn = get_db_connection()

        if unread_only:
            status_filter = 'unread'
        if status_filter not in {'all', 'unread', 'read'}:
            status_filter = 'all'
        if notification_type == 'all':
            notification_type = ''

        where_clauses = [
            '''(
                  (recipient_uid IS NOT NULL AND recipient_uid = ?)
               OR (? != '' AND LOWER(COALESCE(recipient_email, '')) = ?)
            )'''
        ]
        query_params = [requester_uid, requester_email, requester_email]

        if status_filter == 'unread':
            where_clauses.append('is_read = 0')
        elif status_filter == 'read':
            where_clauses.append('is_read = 1')

        if notification_type:
            where_clauses.append('LOWER(COALESCE(notification_type, "")) = ?')
            query_params.append(notification_type)

        where_sql = ' AND '.join(where_clauses)

        total_row = conn.execute(
            f'''SELECT COUNT(*) AS count
                FROM user_notifications
                WHERE {where_sql}''',
            tuple(query_params)
        ).fetchone()
        total_count = int(total_row['count']) if total_row else 0

        unread_row = conn.execute(
            '''SELECT COUNT(*) AS count
               FROM user_notifications
               WHERE (
                      (recipient_uid IS NOT NULL AND recipient_uid = ?)
                   OR (? != '' AND LOWER(COALESCE(recipient_email, '')) = ?)
               )
                 AND is_read = 0''',
            (requester_uid, requester_email, requester_email)
        ).fetchone()
        unread_count = int(unread_row['count']) if unread_row else 0

        rows = conn.execute(
            f'''SELECT id, recipient_uid, recipient_email, actor_uid, itinerary_id,
                       notification_type, message, metadata, is_read, created_at
                FROM user_notifications
                WHERE {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?''',
            tuple(query_params + [limit, offset])
        ).fetchall()
        conn.close()

        notifications = []
        for row in rows:
            item = dict(row)
            try:
                item['metadata'] = json.loads(item['metadata']) if item.get('metadata') else None
            except (TypeError, json.JSONDecodeError):
                pass
            item['is_read'] = bool(item.get('is_read'))
            notifications.append(item)

        return jsonify({
            'notifications': notifications,
            'unread_count': unread_count,
            'total_count': total_count,
            'limit': limit,
            'offset': offset,
            'has_more': (offset + len(notifications)) < total_count,
        })
    except Exception as e:
        logging.error(f"Error loading notifications: {e}")
        return jsonify({'error': 'Failed to load notifications'}), 500


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@firebase_auth_required
def mark_notification_read(notification_id):
    """Mark a single inbox notification as read for current user."""
    auth_user = _get_authenticated_user(optional=False)
    requester_uid = str(auth_user.get('uid') or '').strip()
    requester_email = _normalized_email(auth_user.get('email'))

    try:
        conn = get_db_connection()
        row = conn.execute(
            '''SELECT id
               FROM user_notifications
               WHERE id = ?
                 AND (
                      (recipient_uid IS NOT NULL AND recipient_uid = ?)
                   OR (? != '' AND LOWER(COALESCE(recipient_email, '')) = ?)
                 )
               LIMIT 1''',
            (notification_id, requester_uid, requester_email, requester_email)
        ).fetchone()

        if not row:
            conn.close()
            return jsonify({'error': 'Notification not found'}), 404

        conn.execute(
            'UPDATE user_notifications SET is_read = 1 WHERE id = ?',
            (notification_id,)
        )
        conn.commit()
        conn.close()
        return jsonify({'message': 'Notification marked as read.'})
    except Exception as e:
        logging.error(f"Error marking notification read: {e}")
        return jsonify({'error': 'Failed to mark notification as read'}), 500


@app.route('/api/notifications/read-all', methods=['POST'])
@firebase_auth_required
def mark_all_notifications_read():
    """Mark all notifications as read for current user inbox."""
    auth_user = _get_authenticated_user(optional=False)
    requester_uid = str(auth_user.get('uid') or '').strip()
    requester_email = _normalized_email(auth_user.get('email'))

    try:
        conn = get_db_connection()
        conn.execute(
            '''UPDATE user_notifications
               SET is_read = 1
               WHERE (
                     (recipient_uid IS NOT NULL AND recipient_uid = ?)
                  OR (? != '' AND LOWER(COALESCE(recipient_email, '')) = ?)
               )''',
            (requester_uid, requester_email, requester_email)
        )
        conn.commit()
        conn.close()
        return jsonify({'message': 'All notifications marked as read.'})
    except Exception as e:
        logging.error(f"Error marking all notifications read: {e}")
        return jsonify({'error': 'Failed to mark notifications as read'}), 500


# ==================== PHASE 2 - COLLABORATIVE ITINERARIES ====================

@app.route('/api/itineraries/<int:itinerary_id>/invite', methods=['POST'])
@firebase_auth_required
def invite_itinerary_collaborator(itinerary_id):
    """Invite a collaborator to a saved itinerary."""
    auth_user = _get_authenticated_user(optional=False)
    data = request.json or {}

    collaborator_uid = str(data.get('collaborator_uid', '')).strip() or None
    invited_email = _normalized_email(data.get('invited_email')) or None
    requester_email = _normalized_email(auth_user.get('email'))

    if not collaborator_uid and not invited_email:
        return jsonify({"error": "collaborator_uid or invited_email is required"}), 400

    if collaborator_uid and collaborator_uid == auth_user['uid']:
        return jsonify({"error": "You are already the owner of this itinerary."}), 400

    if invited_email:
        if '@' not in invited_email:
            return jsonify({"error": "invited_email must be a valid email address"}), 400
        if requester_email and invited_email == requester_email:
            return jsonify({"error": "You cannot invite yourself."}), 400

    try:
        conn = get_db_connection()
        itinerary, has_access, is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access or not is_owner:
            conn.close()
            return jsonify({"error": "Only the itinerary owner can invite collaborators."}), 403

        status = 'accepted' if collaborator_uid else 'pending'

        if collaborator_uid:
            conn.execute(
                '''INSERT INTO itinerary_collaborators
                   (itinerary_id, collaborator_uid, invited_email, invited_by_uid, status)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(itinerary_id, collaborator_uid) DO UPDATE SET
                       invited_by_uid = excluded.invited_by_uid,
                       invited_email = excluded.invited_email,
                       status = excluded.status,
                       created_at = CURRENT_TIMESTAMP''',
                (itinerary_id, collaborator_uid, invited_email, auth_user['uid'], status)
            )

        if invited_email:
            conn.execute(
                '''INSERT INTO itinerary_collaborators
                   (itinerary_id, collaborator_uid, invited_email, invited_by_uid, status)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(itinerary_id, invited_email) DO UPDATE SET
                       invited_by_uid = excluded.invited_by_uid,
                       collaborator_uid = COALESCE(excluded.collaborator_uid, itinerary_collaborators.collaborator_uid),
                       status = excluded.status,
                       created_at = CURRENT_TIMESTAMP''',
                (itinerary_id, collaborator_uid, invited_email, auth_user['uid'], status)
            )

        _log_itinerary_activity(
            conn,
            itinerary_id,
            auth_user['uid'],
            'invite_collaborator',
            {
                'collaborator_uid': collaborator_uid,
                'invited_email': invited_email,
                'status': status,
            }
        )

        _create_user_notification(
            conn,
            recipient_uid=collaborator_uid,
            recipient_email=invited_email,
            actor_uid=auth_user['uid'],
            itinerary_id=itinerary_id,
            notification_type='itinerary_invite',
            message=(
                f"You were {'added to' if status == 'accepted' else 'invited to'} "
                f"the itinerary for {str(itinerary['destination'] or 'this trip')}."
            ),
            metadata={
                'status': status,
                'destination': itinerary['destination'],
                'collaborator_uid': collaborator_uid,
                'invited_email': invited_email,
            }
        )

        conn.commit()
        conn.close()

        return jsonify({
            "message": "Collaborator invitation saved.",
            "itinerary_id": itinerary_id,
            "collaborator_uid": collaborator_uid,
            "invited_email": invited_email,
            "status": status,
        }), 201
    except Exception as e:
        logging.error(f"Error inviting collaborator: {e}")
        return jsonify({"error": "Failed to invite collaborator"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/accept-invite', methods=['POST'])
@firebase_auth_required
def accept_itinerary_invite(itinerary_id):
    """Accept a pending itinerary invite by UID or invited email."""
    auth_user = _get_authenticated_user(optional=False)
    requester_uid = str(auth_user.get('uid') or '').strip()
    requester_email = _normalized_email(auth_user.get('email'))

    try:
        conn = get_db_connection()
        itinerary = conn.execute(
            'SELECT id, firebase_uid, destination FROM saved_itineraries WHERE id = ?',
            (itinerary_id,)
        ).fetchone()

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if str(itinerary['firebase_uid'] or '') == requester_uid:
            conn.close()
            return jsonify({"error": "Owner does not need to accept an invite."}), 400

        invite_row = conn.execute(
            '''SELECT id, status, invited_email, collaborator_uid
               FROM itinerary_collaborators
               WHERE itinerary_id = ?
                 AND (
                       collaborator_uid = ?
                    OR (? != '' AND LOWER(COALESCE(invited_email, '')) = ?)
                 )
               ORDER BY created_at DESC
               LIMIT 1''',
            (itinerary_id, requester_uid, requester_email, requester_email)
        ).fetchone()

        if not invite_row:
            conn.close()
            return jsonify({"error": "Invite not found for this user."}), 404

        if invite_row['status'] == 'accepted' and str(invite_row['collaborator_uid'] or '') == requester_uid:
            conn.close()
            return jsonify({"message": "Invite already accepted."})

        conn.execute(
            '''UPDATE itinerary_collaborators
               SET collaborator_uid = ?,
                   status = 'accepted',
                   created_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (requester_uid, invite_row['id'])
        )

        _log_itinerary_activity(
            conn,
            itinerary_id,
            requester_uid,
            'accept_invitation',
            {
                'invited_email': invite_row['invited_email'],
            }
        )

        _create_user_notification(
            conn,
            recipient_uid=itinerary['firebase_uid'],
            actor_uid=requester_uid,
            itinerary_id=itinerary_id,
            notification_type='invite_accepted',
            message=f"A collaborator accepted your invite for {str(itinerary['destination'] or 'your itinerary')}.",
            metadata={'invited_email': invite_row['invited_email']}
        )

        conn.commit()
        conn.close()
        return jsonify({"message": "Invitation accepted."})
    except Exception as e:
        logging.error(f"Error accepting itinerary invite: {e}")
        return jsonify({"error": "Failed to accept invitation"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/decline-invite', methods=['POST'])
@firebase_auth_required
def decline_itinerary_invite(itinerary_id):
    """Decline a pending itinerary invite by UID or invited email."""
    auth_user = _get_authenticated_user(optional=False)
    requester_uid = str(auth_user.get('uid') or '').strip()
    requester_email = _normalized_email(auth_user.get('email'))

    try:
        conn = get_db_connection()
        itinerary = conn.execute(
            'SELECT id, firebase_uid, destination FROM saved_itineraries WHERE id = ?',
            (itinerary_id,)
        ).fetchone()

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if str(itinerary['firebase_uid'] or '') == requester_uid:
            conn.close()
            return jsonify({"error": "Owner cannot decline their own itinerary invite."}), 400

        invite_row = conn.execute(
            '''SELECT id, status, invited_email, collaborator_uid
               FROM itinerary_collaborators
               WHERE itinerary_id = ?
                 AND (
                       collaborator_uid = ?
                    OR (? != '' AND LOWER(COALESCE(invited_email, '')) = ?)
                 )
               ORDER BY created_at DESC
               LIMIT 1''',
            (itinerary_id, requester_uid, requester_email, requester_email)
        ).fetchone()

        if not invite_row:
            conn.close()
            return jsonify({"error": "Invite not found for this user."}), 404

        if invite_row['status'] != 'pending':
            conn.close()
            return jsonify({"error": "Only pending invites can be declined."}), 400

        conn.execute(
            'DELETE FROM itinerary_collaborators WHERE id = ?',
            (invite_row['id'],)
        )

        _log_itinerary_activity(
            conn,
            itinerary_id,
            requester_uid,
            'decline_invitation',
            {'invited_email': invite_row['invited_email']}
        )

        _create_user_notification(
            conn,
            recipient_uid=itinerary['firebase_uid'],
            actor_uid=requester_uid,
            itinerary_id=itinerary_id,
            notification_type='invite_declined',
            message=f"An invite was declined for {str(itinerary['destination'] or 'your itinerary')}.",
            metadata={'invited_email': invite_row['invited_email']}
        )

        conn.commit()
        conn.close()
        return jsonify({"message": "Invitation declined."})
    except Exception as e:
        logging.error(f"Error declining itinerary invite: {e}")
        return jsonify({"error": "Failed to decline invitation"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/leave', methods=['POST'])
@firebase_auth_required
def leave_itinerary_collaboration(itinerary_id):
    """Allow accepted collaborators to leave an itinerary."""
    auth_user = _get_authenticated_user(optional=False)
    requester_uid = str(auth_user.get('uid') or '').strip()

    try:
        conn = get_db_connection()
        itinerary = conn.execute(
            'SELECT id, firebase_uid, destination FROM saved_itineraries WHERE id = ?',
            (itinerary_id,)
        ).fetchone()

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if str(itinerary['firebase_uid'] or '') == requester_uid:
            conn.close()
            return jsonify({"error": "Owner cannot leave their own itinerary."}), 400

        row = conn.execute(
            '''SELECT id, status
               FROM itinerary_collaborators
               WHERE itinerary_id = ?
                 AND collaborator_uid = ?
               ORDER BY created_at DESC
               LIMIT 1''',
            (itinerary_id, requester_uid)
        ).fetchone()

        if not row:
            conn.close()
            return jsonify({"error": "You are not a collaborator on this itinerary."}), 404

        if row['status'] != 'accepted':
            conn.close()
            return jsonify({"error": "Only accepted collaborators can leave."}), 400

        conn.execute('DELETE FROM itinerary_collaborators WHERE id = ?', (row['id'],))
        _log_itinerary_activity(
            conn,
            itinerary_id,
            requester_uid,
            'leave_itinerary',
            None
        )

        _create_user_notification(
            conn,
            recipient_uid=itinerary['firebase_uid'],
            actor_uid=requester_uid,
            itinerary_id=itinerary_id,
            notification_type='collaborator_left',
            message=f"A collaborator left {str(itinerary['destination'] or 'your itinerary')}.",
            metadata={'collaborator_uid': requester_uid}
        )

        conn.commit()
        conn.close()
        return jsonify({"message": "You left this itinerary."})
    except Exception as e:
        logging.error(f"Error leaving itinerary collaboration: {e}")
        return jsonify({"error": "Failed to leave itinerary"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/collaborators', methods=['DELETE'])
@firebase_auth_required
def remove_itinerary_collaborator(itinerary_id):
    """Allow itinerary owner to remove a collaborator or pending invite."""
    auth_user = _get_authenticated_user(optional=False)
    data = request.json or {}

    collaborator_uid = str(data.get('collaborator_uid') or '').strip() or None
    invited_email = _normalized_email(data.get('invited_email')) or None

    if not collaborator_uid and not invited_email:
        return jsonify({"error": "collaborator_uid or invited_email is required"}), 400

    try:
        conn = get_db_connection()
        itinerary, has_access, is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access or not is_owner:
            conn.close()
            return jsonify({"error": "Only the itinerary owner can remove collaborators."}), 403

        if collaborator_uid and str(itinerary['firebase_uid'] or '') == collaborator_uid:
            conn.close()
            return jsonify({"error": "Owner cannot be removed as collaborator."}), 400

        if collaborator_uid:
            row = conn.execute(
                '''SELECT id, collaborator_uid, invited_email, status
                   FROM itinerary_collaborators
                   WHERE itinerary_id = ? AND collaborator_uid = ?
                   ORDER BY created_at DESC
                   LIMIT 1''',
                (itinerary_id, collaborator_uid)
            ).fetchone()
        else:
            row = conn.execute(
                '''SELECT id, collaborator_uid, invited_email, status
                   FROM itinerary_collaborators
                   WHERE itinerary_id = ? AND LOWER(COALESCE(invited_email, '')) = ?
                   ORDER BY created_at DESC
                   LIMIT 1''',
                (itinerary_id, invited_email)
            ).fetchone()

        if not row:
            conn.close()
            return jsonify({"error": "Collaborator invite not found."}), 404

        conn.execute('DELETE FROM itinerary_collaborators WHERE id = ?', (row['id'],))
        _log_itinerary_activity(
            conn,
            itinerary_id,
            auth_user['uid'],
            'remove_collaborator',
            {
                'collaborator_uid': row['collaborator_uid'],
                'invited_email': row['invited_email'],
                'status': row['status'],
            }
        )

        _create_user_notification(
            conn,
            recipient_uid=row['collaborator_uid'],
            recipient_email=row['invited_email'],
            actor_uid=auth_user['uid'],
            itinerary_id=itinerary_id,
            notification_type='removed_from_itinerary',
            message=f"You were removed from itinerary {itinerary_id}.",
            metadata={
                'status': row['status'],
                'collaborator_uid': row['collaborator_uid'],
                'invited_email': row['invited_email'],
            }
        )

        conn.commit()
        conn.close()
        return jsonify({"message": "Collaborator removed."})
    except Exception as e:
        logging.error(f"Error removing collaborator: {e}")
        return jsonify({"error": "Failed to remove collaborator"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/collaborators', methods=['GET'])
@firebase_auth_required
def get_itinerary_collaborators(itinerary_id):
    """List itinerary collaborators for owner/collaborators."""
    auth_user = _get_authenticated_user(optional=False)

    try:
        conn = get_db_connection()
        itinerary, has_access, is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access:
            conn.close()
            return jsonify({"error": "Forbidden: you do not have access to this itinerary."}), 403

        rows = conn.execute(
            '''SELECT collaborator_uid, invited_email, invited_by_uid, status, created_at
               FROM itinerary_collaborators
               WHERE itinerary_id = ?
               ORDER BY created_at DESC''',
            (itinerary_id,)
        ).fetchall()
        conn.close()

        return jsonify({
            "itinerary_id": itinerary_id,
            "owner_uid": itinerary['firebase_uid'],
            "is_owner": is_owner,
            "collaborators": [dict(row) for row in rows],
        })
    except Exception as e:
        logging.error(f"Error listing collaborators: {e}")
        return jsonify({"error": "Failed to load collaborators"}), 500


@app.route('/api/itineraries/<int:itinerary_id>', methods=['GET'])
@firebase_auth_required
def get_saved_itinerary(itinerary_id):
    """Return a saved itinerary payload for owner or accepted collaborators."""
    auth_user = _get_authenticated_user(optional=False)

    try:
        conn = get_db_connection()
        itinerary, has_access, is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access:
            conn.close()
            return jsonify({"error": "Forbidden: you do not have access to this itinerary."}), 403

        payload = _serialize_saved_itinerary_row(itinerary)
        if 'revision' not in payload:
            payload['revision'] = 1
        payload['is_owner'] = is_owner
        conn.close()
        return jsonify(payload)
    except Exception as e:
        logging.error(f"Error loading saved itinerary {itinerary_id}: {e}")
        return jsonify({"error": "Failed to load itinerary"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/presence', methods=['GET'])
@firebase_auth_required
def get_itinerary_presence(itinerary_id):
    """List active collaborators currently viewing/editing an itinerary."""
    auth_user = _get_authenticated_user(optional=False)

    try:
        conn = get_db_connection()
        itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access:
            conn.close()
            return jsonify({"error": "Forbidden: you do not have access to this itinerary."}), 403

        conn.execute(
            '''CREATE TABLE IF NOT EXISTS itinerary_presence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                itinerary_id INTEGER NOT NULL,
                firebase_uid TEXT NOT NULL,
                email TEXT,
                status TEXT DEFAULT 'viewing',
                cursor_context TEXT,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(itinerary_id, firebase_uid)
            )'''
        )

        _prune_itinerary_presence(conn)
        active = _list_active_itinerary_presence(conn, itinerary_id)
        conn.commit()
        conn.close()

        return jsonify({
            "itinerary_id": itinerary_id,
            "active": active,
            "server_time": _iso_timestamp_now(),
        })
    except Exception as e:
        logging.error(f"Error loading itinerary presence: {e}")
        return jsonify({"error": "Failed to load presence"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/presence', methods=['POST'])
@firebase_auth_required
def heartbeat_itinerary_presence(itinerary_id):
    """Upsert active presence heartbeat for owner/collaborator sessions."""
    auth_user = _get_authenticated_user(optional=False)
    data = request.json or {}

    raw_status = str(data.get('status') or 'viewing').strip().lower()
    status = raw_status if raw_status in {'viewing', 'editing', 'idle'} else 'viewing'
    cursor_context = _normalize_presence_cursor(data.get('cursor_context'))

    try:
        conn = get_db_connection()
        itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access:
            conn.close()
            return jsonify({"error": "Forbidden: you do not have access to this itinerary."}), 403

        conn.execute(
            '''CREATE TABLE IF NOT EXISTS itinerary_presence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                itinerary_id INTEGER NOT NULL,
                firebase_uid TEXT NOT NULL,
                email TEXT,
                status TEXT DEFAULT 'viewing',
                cursor_context TEXT,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(itinerary_id, firebase_uid)
            )'''
        )

        conn.execute(
            '''INSERT INTO itinerary_presence
               (itinerary_id, firebase_uid, email, status, cursor_context, last_seen)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(itinerary_id, firebase_uid) DO UPDATE SET
                   email = excluded.email,
                   status = excluded.status,
                   cursor_context = excluded.cursor_context,
                   last_seen = CURRENT_TIMESTAMP''',
            (
                itinerary_id,
                str(auth_user.get('uid') or '').strip(),
                _normalized_email(auth_user.get('email')),
                status,
                cursor_context,
            )
        )

        _prune_itinerary_presence(conn)
        active = _list_active_itinerary_presence(conn, itinerary_id)
        conn.commit()
        conn.close()

        return jsonify({
            "message": "Presence heartbeat updated.",
            "itinerary_id": itinerary_id,
            "active": active,
            "server_time": _iso_timestamp_now(),
        })
    except Exception as e:
        logging.error(f"Error updating itinerary presence: {e}")
        return jsonify({"error": "Failed to update presence"}), 500


@app.route('/api/itineraries/<int:itinerary_id>', methods=['PUT'])
@firebase_auth_required
def update_saved_itinerary(itinerary_id):
    """Update a saved itinerary by owner or accepted collaborator."""
    auth_user = _get_authenticated_user(optional=False)
    data = request.json or {}
    base_revision = _coerce_positive_int(data.get('base_revision'))

    allowed_fields = {
        'destination',
        'duration',
        'budget',
        'purpose',
        'preferences',
        'itinerary_html',
        'itinerary_data',
        'is_public',
    }

    updates = {k: data[k] for k in allowed_fields if k in data}
    if not updates:
        return jsonify({"error": "No editable fields provided."}), 400

    if 'destination' in updates:
        updates['destination'] = str(updates['destination']).strip()
        if not updates['destination']:
            return jsonify({"error": "destination cannot be empty"}), 400

    if 'itinerary_html' in updates:
        updates['itinerary_html'] = str(updates['itinerary_html']).strip()
        if not updates['itinerary_html']:
            return jsonify({"error": "itinerary_html cannot be empty"}), 400

    if 'preferences' in updates:
        if not isinstance(updates['preferences'], list):
            return jsonify({"error": "preferences must be a list"}), 400
        updates['preferences'] = json.dumps(updates['preferences'])

    if 'itinerary_data' in updates:
        if not isinstance(updates['itinerary_data'], dict):
            return jsonify({"error": "itinerary_data must be an object"}), 400
        updates['itinerary_data'] = json.dumps(updates['itinerary_data'])

    if 'is_public' in updates:
        updates['is_public'] = 1 if bool(updates['is_public']) else 0

    try:
        conn = get_db_connection()
        itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access:
            conn.close()
            return jsonify({"error": "Forbidden: you do not have edit access."}), 403

        saved_columns = _table_columns(conn, 'saved_itineraries')
        has_revision = 'revision' in saved_columns
        current_revision = None
        if has_revision:
            current_revision = _coerce_positive_int(dict(itinerary).get('revision')) or 1
            if base_revision and base_revision != current_revision:
                latest_row = conn.execute(
                    'SELECT * FROM saved_itineraries WHERE id = ?',
                    (itinerary_id,)
                ).fetchone()
                latest_payload = _serialize_saved_itinerary_row(latest_row) if latest_row else None
                conn.close()
                return jsonify({
                    "error": "Conflict: itinerary has newer updates from another collaborator.",
                    "code": "revision_conflict",
                    "server_revision": current_revision,
                    "latest": latest_payload,
                }), 409

        fields = list(updates.keys())
        set_parts = [f"{field} = ?" for field in fields]
        values = [updates[field] for field in fields]

        if has_revision:
            set_parts.append('revision = COALESCE(revision, 1) + 1')
        if 'last_editor_uid' in saved_columns:
            set_parts.append('last_editor_uid = ?')
            values.append(str(auth_user.get('uid') or '').strip())

        set_parts.append('updated_at = CURRENT_TIMESTAMP')
        set_clause = ', '.join(set_parts)
        values.append(itinerary_id)

        conn.execute(f'UPDATE saved_itineraries SET {set_clause} WHERE id = ?', values)

        response_revision = current_revision
        if has_revision:
            rev_row = conn.execute(
                'SELECT revision FROM saved_itineraries WHERE id = ?',
                (itinerary_id,)
            ).fetchone()
            response_revision = _coerce_positive_int(rev_row['revision']) if rev_row else current_revision

        _log_itinerary_activity(
            conn,
            itinerary_id,
            auth_user['uid'],
            'update_itinerary',
            {
                'updated_fields': fields,
                'base_revision': base_revision,
                'new_revision': response_revision,
            }
        )
        conn.commit()
        conn.close()

        payload = {"message": "Itinerary updated successfully."}
        if response_revision:
            payload['revision'] = response_revision
        return jsonify(payload)
    except Exception as e:
        logging.error(f"Error updating itinerary: {e}")
        return jsonify({"error": "Failed to update itinerary"}), 500


@app.route('/api/itineraries/<int:itinerary_id>/activity', methods=['GET'])
@firebase_auth_required
def get_itinerary_activity(itinerary_id):
    """Get itinerary activity log for owner/collaborators."""
    auth_user = _get_authenticated_user(optional=False)

    try:
        conn = get_db_connection()
        itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])

        if not itinerary:
            conn.close()
            return jsonify({"error": "Itinerary not found"}), 404

        if not has_access:
            conn.close()
            return jsonify({"error": "Forbidden: you do not have access to this itinerary."}), 403

        rows = conn.execute(
            '''SELECT actor_uid, action, details, created_at
               FROM itinerary_activity_log
               WHERE itinerary_id = ?
               ORDER BY created_at DESC
               LIMIT 100''',
            (itinerary_id,)
        ).fetchall()
        conn.close()

        activity = []
        for row in rows:
            entry = dict(row)
            try:
                entry['details'] = json.loads(entry['details']) if entry.get('details') else None
            except (TypeError, json.JSONDecodeError):
                pass
            activity.append(entry)

        return jsonify({"itinerary_id": itinerary_id, "activity": activity})
    except Exception as e:
        logging.error(f"Error getting itinerary activity: {e}")
        return jsonify({"error": "Failed to load itinerary activity"}), 500


# ==================== PHASE 2 - PACKING LIST SYNC ====================

@app.route('/api/packing-list-state/<firebase_uid>', methods=['GET'])
@firebase_auth_required
def get_packing_list_state(firebase_uid):
    """Get saved packing list data and checklist state for a user trip key."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    trip_key = str(request.args.get('trip_key', '')).strip()
    if not trip_key:
        return jsonify({"error": "trip_key query parameter is required"}), 400

    try:
        conn = get_db_connection()
        row = conn.execute(
            '''SELECT packing_data, checked_state, updated_at
               FROM packing_list_states
               WHERE firebase_uid = ? AND trip_key = ?''',
            (firebase_uid, trip_key)
        ).fetchone()
        conn.close()

        if not row:
            return jsonify({
                "trip_key": trip_key,
                "packing_data": None,
                "checked_state": {},
                "updated_at": None,
            })

        packing_data = None
        checked_state = {}

        try:
            if row['packing_data']:
                packing_data = json.loads(row['packing_data'])
        except (TypeError, json.JSONDecodeError):
            packing_data = None

        try:
            if row['checked_state']:
                parsed_state = json.loads(row['checked_state'])
                if isinstance(parsed_state, dict):
                    checked_state = parsed_state
        except (TypeError, json.JSONDecodeError):
            checked_state = {}

        return jsonify({
            "trip_key": trip_key,
            "packing_data": packing_data,
            "checked_state": checked_state,
            "updated_at": row['updated_at'],
        })
    except Exception as e:
        logging.error(f"Error getting packing list state: {e}")
        return jsonify({"error": "Internal error"}), 500


@app.route('/api/packing-list-state', methods=['POST'])
@firebase_auth_required
def save_packing_list_state():
    """Save packing list data and checklist state for cross-device sync."""
    auth_user = _get_authenticated_user(optional=False)
    data = request.json or {}

    trip_key = str(data.get('trip_key', '')).strip()
    checked_state = data.get('checked_state', {})
    packing_data = data.get('packing_data')
    itinerary_id = data.get('itinerary_id')

    if not trip_key:
        return jsonify({"error": "trip_key is required"}), 400

    if not isinstance(checked_state, dict):
        return jsonify({"error": "checked_state must be an object"}), 400

    if packing_data is not None and not isinstance(packing_data, dict):
        return jsonify({"error": "packing_data must be an object when provided"}), 400

    try:
        conn = get_db_connection()

        if itinerary_id:
            itinerary = conn.execute(
                'SELECT id FROM saved_itineraries WHERE id = ? AND firebase_uid = ?',
                (itinerary_id, auth_user['uid'])
            ).fetchone()
            if not itinerary:
                conn.close()
                return jsonify({"error": "Forbidden: itinerary ownership mismatch."}), 403

        conn.execute(
            '''INSERT INTO packing_list_states (firebase_uid, trip_key, itinerary_id, packing_data, checked_state)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(firebase_uid, trip_key) DO UPDATE SET
                   itinerary_id = COALESCE(excluded.itinerary_id, packing_list_states.itinerary_id),
                   packing_data = COALESCE(excluded.packing_data, packing_list_states.packing_data),
                   checked_state = excluded.checked_state,
                   updated_at = CURRENT_TIMESTAMP''',
            (
                auth_user['uid'],
                trip_key,
                itinerary_id,
                json.dumps(packing_data) if packing_data is not None else None,
                json.dumps(checked_state),
            )
        )

        conn.commit()
        conn.close()
        return jsonify({"message": "Packing list state saved."})
    except Exception as e:
        logging.error(f"Error saving packing list state: {e}")
        return jsonify({"error": "Failed to save packing list state"}), 500


# ==================== PHASE 2 - BUDGET TRACKER ====================

@app.route('/api/expenses/<firebase_uid>', methods=['GET'])
@firebase_auth_required
def get_expenses(firebase_uid):
    """Get all expenses for a user, optionally filtered by itinerary."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    itinerary_id = request.args.get('itinerary_id')
    try:
        conn = get_db_connection()
        if itinerary_id:
            expenses = conn.execute(
                'SELECT * FROM trip_expenses WHERE firebase_uid = ? AND itinerary_id = ? ORDER BY date DESC',
                (firebase_uid, itinerary_id)
            ).fetchall()
        else:
            expenses = conn.execute(
                'SELECT * FROM trip_expenses WHERE firebase_uid = ? ORDER BY date DESC',
                (firebase_uid,)
            ).fetchall()
        conn.close()

        expenses_list = [dict(e) for e in expenses]
        total = sum(e['amount'] for e in expenses_list)
        by_category = {}
        for e in expenses_list:
            cat = e.get('category', 'other')
            by_category[cat] = by_category.get(cat, 0) + e['amount']

        return jsonify({
            "expenses": expenses_list,
            "total": round(total, 2),
            "by_category": by_category
        })
    except Exception as e:
        logging.error(f"Error getting expenses: {e}")
        return jsonify({"error": "Internal error"}), 500


@app.route('/api/expenses', methods=['POST'])
@firebase_auth_required
def add_expense():
    """Add a new expense."""
    data = request.json or {}
    auth_user = _get_authenticated_user(optional=False)

    description = str(data.get('description', '')).strip()
    category = str(data.get('category', 'other')).strip() or 'other'
    currency = str(data.get('currency', 'USD')).strip() or 'USD'

    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a valid number"}), 400

    if amount <= 0 or not description:
        return jsonify({"error": "description and a positive amount are required"}), 400

    try:
        conn = get_db_connection()

        itinerary_id = data.get('itinerary_id')
        if itinerary_id:
            itinerary = conn.execute(
                'SELECT id FROM saved_itineraries WHERE id = ? AND firebase_uid = ?',
                (itinerary_id, auth_user['uid'])
            ).fetchone()
            if not itinerary:
                conn.close()
                return jsonify({'error': 'Forbidden: itinerary ownership mismatch.'}), 403

        conn.execute(
            '''INSERT INTO trip_expenses (firebase_uid, itinerary_id, category, description, amount, currency, date)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (
                auth_user['uid'],
                itinerary_id,
                category,
                description,
                amount,
                currency,
                data.get('date', datetime.now().strftime('%Y-%m-%d'))
            )
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Expense added"}), 201
    except Exception as e:
        logging.error(f"Error adding expense: {e}")
        return jsonify({"error": "Failed to add expense"}), 500


@app.route('/api/expenses/<int:expense_id>', methods=['DELETE'])
@firebase_auth_required
def delete_expense(expense_id):
    """Delete an expense."""
    auth_user = _get_authenticated_user(optional=False)
    try:
        conn = get_db_connection()

        row = conn.execute(
            'SELECT id FROM trip_expenses WHERE id = ? AND firebase_uid = ?',
            (expense_id, auth_user['uid'])
        ).fetchone()

        if not row:
            conn.close()
            return jsonify({'error': 'Expense not found or not owned by user.'}), 404

        conn.execute(
            'DELETE FROM trip_expenses WHERE id = ? AND firebase_uid = ?',
            (expense_id, auth_user['uid'])
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Expense deleted"})
    except Exception as e:
        logging.error(f"Error deleting expense: {e}")
        return jsonify({"error": "Failed to delete expense"}), 500


# ==================== PHASE 2 - CURRENCY CONVERTER ====================

@app.route('/api/exchange-rates', methods=['GET'])
def get_exchange_rates():
    """Get live exchange rates using a free API."""
    base = request.args.get('base', 'USD')
    try:
        # Using exchangerate.host (free, no key required)
        url = f"https://api.exchangerate.host/latest?base={base}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return jsonify({
                "base": data.get("base", base),
                "rates": data.get("rates", {}),
                "date": data.get("date", "")
            })
        else:
            # Fallback: use static common rates
            return jsonify({
                "base": base,
                "rates": {
                    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 149.5,
                    "INR": 83.1, "AUD": 1.53, "CAD": 1.36, "CHF": 0.88,
                    "CNY": 7.24, "THB": 35.4, "AED": 3.67, "SGD": 1.34,
                    "MYR": 4.72, "IDR": 15600, "PHP": 56.2, "KRW": 1320
                },
                "date": datetime.now().strftime('%Y-%m-%d'),
                "note": "Using cached rates"
            })
    except Exception as e:
        logging.warning(f"Exchange rate API error: {e}")
        return jsonify({
            "base": "USD",
            "rates": {
                "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 149.5,
                "INR": 83.1, "AUD": 1.53, "CAD": 1.36, "CHF": 0.88
            },
            "date": datetime.now().strftime('%Y-%m-%d'),
            "note": "Using cached rates (API unavailable)"
        })


# ==================== PHASE 2 - DIGITAL PASSPORT ====================

@app.route('/api/passport/<firebase_uid>', methods=['GET'])
@firebase_auth_required
def get_passport(firebase_uid):
    """Get digital passport data for a user."""
    ownership_error = _enforce_uid_ownership(firebase_uid)
    if ownership_error:
        return ownership_error

    try:
        conn = get_db_connection()
        stamps = conn.execute(
            'SELECT * FROM digital_passport WHERE firebase_uid = ? ORDER BY visited_date DESC',
            (firebase_uid,)
        ).fetchall()
        conn.close()

        stamps_list = [dict(s) for s in stamps]
        unique_countries = list(set(s['country'] for s in stamps_list))

        return jsonify({
            "stamps": stamps_list,
            "countries_visited": len(unique_countries),
            "country_list": unique_countries,
            "level": get_traveler_level(len(unique_countries))
        })
    except Exception as e:
        logging.error(f"Error getting passport: {e}")
        return jsonify({"error": "Internal error"}), 500


@app.route('/api/passport/stamp', methods=['POST'])
@firebase_auth_required
def add_stamp():
    """Add a country stamp to the digital passport."""
    data = request.json or {}
    auth_user = _get_authenticated_user(optional=False)

    country = str(data.get('country', '')).strip()
    if not country:
        return jsonify({'error': 'country is required'}), 400

    if data.get('firebase_uid') and data.get('firebase_uid') != auth_user['uid']:
        return jsonify({'error': 'Forbidden: resource ownership mismatch.'}), 403

    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT OR IGNORE INTO digital_passport
               (firebase_uid, country, country_code, visited_date, trip_notes, stamp_type)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (
                auth_user['uid'],
                country,
                data.get('country_code', ''),
                data.get('visited_date', datetime.now().strftime('%Y-%m-%d')),
                data.get('trip_notes', ''),
                data.get('stamp_type', 'visited')
            )
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Stamp added!"}), 201
    except Exception as e:
        logging.error(f"Error adding stamp: {e}")
        return jsonify({"error": "Failed to add stamp"}), 500


def get_traveler_level(countries_count):
    """Determine traveler level based on countries visited."""
    if countries_count >= 50:
        return {"title": "🌍 Globe Trotter Legend", "level": 10, "badge": "🏆"}
    elif countries_count >= 30:
        return {"title": "🗺️ World Explorer", "level": 8, "badge": "🥇"}
    elif countries_count >= 20:
        return {"title": "✈️ Seasoned Voyager", "level": 6, "badge": "🥈"}
    elif countries_count >= 10:
        return {"title": "🧭 Rising Explorer", "level": 4, "badge": "🥉"}
    elif countries_count >= 5:
        return {"title": "🎒 Active Adventurer", "level": 3, "badge": "⭐"}
    elif countries_count >= 1:
        return {"title": "🌱 Budding Traveler", "level": 1, "badge": "🌟"}
    else:
        return {"title": "🏠 Armchair Explorer", "level": 0, "badge": "🔰"}

@app.route('/api/status', methods=['GET'])
def api_status():
    """Check API rate limit status."""
    can_proceed, error_message = check_rate_limit()
    current_time = datetime.now()

    # Count recent calls
    recent_calls = [call_time for call_time in API_CALL_HISTORY
                   if current_time - call_time < timedelta(minutes=1)]

    daily_calls = [call_time for call_time in API_CALL_HISTORY
                  if current_time - call_time < timedelta(days=1)]

    return jsonify({
        "can_generate": can_proceed,
        "error_message": error_message,
        "calls_this_minute": len(recent_calls),
        "calls_today": len(daily_calls),
        "max_per_minute": MAX_CALLS_PER_MINUTE,
        "max_per_day": MAX_CALLS_PER_DAY
    })

# -------------------- WEATHER API INTEGRATION --------------------

@app.route('/get-weather', methods=['GET'])
def get_weather():
    """Fetches weather data for a given destination."""
    city = request.args.get("city", "").strip()

    if not city:
        return jsonify({"error": "City parameter is required"}), 400

    # OpenWeatherMap API URL
    weather_url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"

    try:
        response = requests.get(weather_url)
        weather_data = response.json()

        if response.status_code != 200:
            return jsonify({"error": weather_data.get("message", "Failed to fetch weather data")}), response.status_code

        # Extract relevant weather details
        weather_info = {
            "city": weather_data["name"],
            "temperature": weather_data["main"]["temp"],
            "description": weather_data["weather"][0]["description"],
            "humidity": weather_data["main"]["humidity"],
            "wind_speed": weather_data["wind"]["speed"]
        }

        return jsonify(weather_info)

    except Exception as e:
        logging.error(f"Error fetching weather data: {str(e)}")
        return jsonify({"error": "Failed to fetch weather data"}), 500

@app.route('/blog')
def blog():
    conn = get_db_connection()
    posts = conn.execute('SELECT * FROM blog_posts ORDER BY date_posted DESC').fetchall()
    # Parse tags and set image fallback
    posts = [dict(row) for row in posts]
    for post in posts:
        post['tags'] = post.get('tags', '').split(',') if post.get('tags') else []
        if not post.get('image'):
            post['image'] = '/static/images/default_blog.jpg'
    countries = sorted(set(post.get('country', '') for post in posts if post.get('country')))
    states = sorted(set(post.get('state', '') for post in posts if post.get('state')))
    conn.close()
    return render_template('blog.html', posts=posts, countries=countries, states=states)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/post-blog', methods=['POST'])
def post_blog():
    title = request.form.get('title')
    content = request.form.get('content')
    author = request.form.get('author')
    location = request.form.get('location')
    country = request.form.get('country')
    state = request.form.get('state')
    category = request.form.get('category')
    tags = request.form.get('tags', '')
    image = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(file_path)
            image = '/' + file_path.replace('\\', '/')
    if not image:
        image = '/static/images/default_blog.jpg'
    date_posted = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO blog_posts (title, content, author, date_posted, location, country, state, category, tags, image) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (title, content, author, date_posted, location, country, state, category, tags, image)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('blog'))


@app.route('/api/publish-trip-journal', methods=['POST'])
@firebase_auth_required
def publish_trip_journal():
    """Publish a generated trip journal directly to the blog."""
    data = request.json or {}
    auth_user = _get_authenticated_user(optional=False)

    title = str(data.get('title', '')).strip()
    content = str(data.get('content') or data.get('recap') or '').strip()
    destination = str(data.get('destination', '')).strip()
    location = str(data.get('location', '')).strip() or destination
    country = str(data.get('country', '')).strip()
    state = str(data.get('state', '')).strip()
    category = str(data.get('category', 'travel-journal')).strip() or 'travel-journal'
    image = str(data.get('image', '')).strip()
    itinerary_id = _coerce_positive_int(data.get('itinerary_id'))
    media_urls = _normalize_string_list(data.get('media_urls'), max_items=12)

    if not title or not content:
        return jsonify({'error': 'title and content are required'}), 400

    if not image and media_urls:
        image = media_urls[0]
    if not image:
        image = '/static/images/default_blog.jpg'

    author = str(data.get('author', '')).strip()
    if not author:
        email = str(auth_user.get('email') or '').strip()
        author = email.split('@')[0] if email else f"user-{str(auth_user.get('uid', 'traveler'))[:8]}"

    tags_input = data.get('tags')
    if isinstance(tags_input, list):
        tag_values = [str(tag).strip() for tag in tags_input if str(tag).strip()]
    elif tags_input is not None:
        tag_values = [tag.strip() for tag in str(tags_input).split(',') if tag.strip()]
    else:
        tag_values = []

    if not tag_values:
        tag_values = ['trip-journal', 'ai-recap']
    tags = ','.join(tag_values[:10])

    try:
        conn = get_db_connection()

        if itinerary_id:
            itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])
            if not itinerary:
                conn.close()
                return jsonify({'error': 'Itinerary not found'}), 404
            if not has_access:
                conn.close()
                return jsonify({'error': 'Forbidden: you do not have access to this itinerary.'}), 403

            if not destination:
                destination = str(itinerary['destination'] or '').strip()
            if not location:
                location = destination

        if not location:
            location = destination or 'Travel'

        date_posted = datetime.now().strftime('%Y-%m-%d')
        cursor = conn.execute(
            '''INSERT INTO blog_posts
               (title, content, author, date_posted, location, country, state, category, tags, image)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (title, content, author, date_posted, location, country, state, category, tags, image)
        )
        post_id = cursor.lastrowid

        if itinerary_id:
            _log_itinerary_activity(
                conn,
                itinerary_id,
                auth_user['uid'],
                'publish_trip_journal',
                {
                    'post_id': post_id,
                    'title': title,
                    'media_count': len(media_urls),
                }
            )

            if str(itinerary['firebase_uid'] or '') != str(auth_user['uid']):
                _create_user_notification(
                    conn,
                    recipient_uid=itinerary['firebase_uid'],
                    actor_uid=auth_user['uid'],
                    itinerary_id=itinerary_id,
                    notification_type='journal_published',
                    message=f"A collaborator published a trip journal for {str(itinerary['destination'] or 'your itinerary')}.",
                    metadata={'post_id': post_id, 'title': title}
                )

        conn.commit()
        conn.close()

        blog_url = f"{request.host_url}blog/{post_id}"
        return jsonify({
            'message': 'Trip journal published successfully.',
            'post_id': post_id,
            'blog_url': blog_url,
        }), 201
    except Exception as e:
        logging.error(f"Error publishing trip journal: {e}")
        return jsonify({'error': 'Failed to publish trip journal'}), 500


@app.route('/api/journal-drafts', methods=['POST'])
@firebase_auth_required
def save_trip_journal_draft():
    """Autosave trip journal drafts and maintain lightweight version history."""
    auth_user = _get_authenticated_user(optional=False)
    data = request.json or {}

    itinerary_id = _coerce_positive_int(data.get('itinerary_id'))
    destination = str(data.get('destination', '')).strip()
    draft_key = str(data.get('draft_key', '')).strip()
    title = str(data.get('title', '')).strip()
    content = str(data.get('content', '')).strip()
    tags_list = _normalize_string_list(data.get('tags'), max_items=20)
    media_urls = _normalize_string_list(data.get('media_urls'), max_items=12)

    if not draft_key:
        draft_key = _build_journal_draft_key(itinerary_id, destination)

    if not draft_key:
        return jsonify({'error': 'draft_key could not be determined'}), 400

    try:
        conn = get_db_connection()

        if itinerary_id:
            itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])
            if not itinerary:
                conn.close()
                return jsonify({'error': 'Itinerary not found'}), 404
            if not has_access:
                conn.close()
                return jsonify({'error': 'Forbidden: you do not have access to this itinerary.'}), 403
            if not destination:
                destination = str(itinerary['destination'] or '').strip()

        tags_text = ','.join(tags_list)
        media_text = json.dumps(media_urls)

        existing_row = conn.execute(
            '''SELECT id, title, content, tags, media_urls
               FROM trip_journal_drafts
               WHERE firebase_uid = ? AND draft_key = ?
               LIMIT 1''',
            (auth_user['uid'], draft_key)
        ).fetchone()

        conn.execute(
            '''INSERT INTO trip_journal_drafts
               (firebase_uid, itinerary_id, draft_key, destination, title, content, tags, media_urls)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(firebase_uid, draft_key) DO UPDATE SET
                   itinerary_id = excluded.itinerary_id,
                   destination = excluded.destination,
                   title = excluded.title,
                   content = excluded.content,
                   tags = excluded.tags,
                   media_urls = excluded.media_urls,
                   updated_at = CURRENT_TIMESTAMP''',
            (
                auth_user['uid'],
                itinerary_id,
                draft_key,
                destination,
                title,
                content,
                tags_text,
                media_text,
            )
        )

        draft_row = conn.execute(
            '''SELECT *
               FROM trip_journal_drafts
               WHERE firebase_uid = ? AND draft_key = ?
               LIMIT 1''',
            (auth_user['uid'], draft_key)
        ).fetchone()

        if not draft_row:
            conn.close()
            return jsonify({'error': 'Failed to save draft'}), 500

        should_version = True
        if existing_row:
            existing_title = str(existing_row['title'] or '')
            existing_content = str(existing_row['content'] or '')
            existing_tags = str(existing_row['tags'] or '')
            existing_media = str(existing_row['media_urls'] or '')
            should_version = any([
                existing_title != title,
                existing_content != content,
                existing_tags != tags_text,
                existing_media != media_text,
            ])

        if should_version:
            conn.execute(
                '''INSERT INTO trip_journal_versions
                   (draft_id, firebase_uid, itinerary_id, title, content, tags, media_urls)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    draft_row['id'],
                    auth_user['uid'],
                    itinerary_id,
                    title,
                    content,
                    tags_text,
                    media_text,
                )
            )
            conn.execute(
                '''DELETE FROM trip_journal_versions
                   WHERE draft_id = ?
                     AND id NOT IN (
                       SELECT id FROM trip_journal_versions
                       WHERE draft_id = ?
                       ORDER BY created_at DESC, id DESC
                       LIMIT 30
                   )''',
                (draft_row['id'], draft_row['id'])
            )

        version_count = conn.execute(
            'SELECT COUNT(*) AS count FROM trip_journal_versions WHERE draft_id = ?',
            (draft_row['id'],)
        ).fetchone()['count']

        if itinerary_id:
            _log_itinerary_activity(
                conn,
                itinerary_id,
                auth_user['uid'],
                'save_journal_draft',
                {'draft_id': draft_row['id'], 'version_count': version_count}
            )

        conn.commit()
        conn.close()

        response_draft = dict(draft_row)
        response_draft['tags'] = tags_list
        response_draft['media_urls'] = media_urls

        return jsonify({
            'message': 'Draft saved',
            'draft': response_draft,
            'version_count': version_count,
        }), 200
    except Exception as e:
        logging.error(f"Error saving trip journal draft: {e}")
        return jsonify({'error': 'Failed to save trip journal draft'}), 500


@app.route('/api/journal-drafts/latest', methods=['GET'])
@firebase_auth_required
def get_latest_trip_journal_draft():
    """Return the latest draft for the user by draft key or itinerary."""
    auth_user = _get_authenticated_user(optional=False)
    itinerary_id = _coerce_positive_int(request.args.get('itinerary_id'))
    destination = str(request.args.get('destination', '')).strip()
    draft_key = str(request.args.get('draft_key', '')).strip()

    try:
        conn = get_db_connection()

        if itinerary_id:
            itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])
            if not itinerary:
                conn.close()
                return jsonify({'error': 'Itinerary not found'}), 404
            if not has_access:
                conn.close()
                return jsonify({'error': 'Forbidden: you do not have access to this itinerary.'}), 403

        query = '''SELECT *
                   FROM trip_journal_drafts
                   WHERE firebase_uid = ?'''
        params = [auth_user['uid']]

        if draft_key:
            query += ' AND draft_key = ?'
            params.append(draft_key)
        elif itinerary_id:
            query += ' AND itinerary_id = ?'
            params.append(itinerary_id)
        elif destination:
            generated_key = _build_journal_draft_key(None, destination)
            query += ' AND draft_key = ?'
            params.append(generated_key)

        query += ' ORDER BY updated_at DESC LIMIT 1'

        draft_row = conn.execute(query, tuple(params)).fetchone()
        conn.close()

        if not draft_row:
            return jsonify({'draft': None})

        draft = dict(draft_row)
        draft['tags'] = _normalize_string_list(draft.get('tags'), max_items=20)
        media_raw = draft.get('media_urls')
        try:
            draft['media_urls'] = json.loads(media_raw) if media_raw else []
        except (TypeError, json.JSONDecodeError):
            draft['media_urls'] = []

        return jsonify({'draft': draft})
    except Exception as e:
        logging.error(f"Error loading latest trip journal draft: {e}")
        return jsonify({'error': 'Failed to load trip journal draft'}), 500


@app.route('/api/journal-drafts/history', methods=['GET'])
@firebase_auth_required
def get_trip_journal_draft_history():
    """Return draft version history for the authenticated user."""
    auth_user = _get_authenticated_user(optional=False)
    itinerary_id = _coerce_positive_int(request.args.get('itinerary_id'))
    draft_key = str(request.args.get('draft_key', '')).strip()
    limit = _coerce_positive_int(request.args.get('limit')) or 15
    limit = max(1, min(limit, 50))

    if not draft_key and not itinerary_id:
        return jsonify({'error': 'draft_key or itinerary_id is required'}), 400

    try:
        conn = get_db_connection()

        if itinerary_id:
            itinerary, has_access, _is_owner = _resolve_itinerary_access(conn, itinerary_id, auth_user['uid'])
            if not itinerary:
                conn.close()
                return jsonify({'error': 'Itinerary not found'}), 404
            if not has_access:
                conn.close()
                return jsonify({'error': 'Forbidden: you do not have access to this itinerary.'}), 403

        if draft_key:
            draft_row = conn.execute(
                '''SELECT * FROM trip_journal_drafts
                   WHERE firebase_uid = ? AND draft_key = ?
                   ORDER BY updated_at DESC
                   LIMIT 1''',
                (auth_user['uid'], draft_key)
            ).fetchone()
        else:
            draft_row = conn.execute(
                '''SELECT * FROM trip_journal_drafts
                   WHERE firebase_uid = ? AND itinerary_id = ?
                   ORDER BY updated_at DESC
                   LIMIT 1''',
                (auth_user['uid'], itinerary_id)
            ).fetchone()

        if not draft_row:
            conn.close()
            return jsonify({'draft': None, 'versions': []})

        versions = conn.execute(
            '''SELECT id, title, content, tags, media_urls, created_at
               FROM trip_journal_versions
               WHERE draft_id = ?
               ORDER BY created_at DESC, id DESC
               LIMIT ?''',
            (draft_row['id'], limit)
        ).fetchall()
        conn.close()

        version_items = []
        for row in versions:
            item = dict(row)
            item['tags'] = _normalize_string_list(item.get('tags'), max_items=20)
            try:
                item['media_urls'] = json.loads(item.get('media_urls') or '[]')
            except (TypeError, json.JSONDecodeError):
                item['media_urls'] = []
            version_items.append(item)

        draft_payload = dict(draft_row)
        draft_payload['tags'] = _normalize_string_list(draft_payload.get('tags'), max_items=20)
        try:
            draft_payload['media_urls'] = json.loads(draft_payload.get('media_urls') or '[]')
        except (TypeError, json.JSONDecodeError):
            draft_payload['media_urls'] = []

        return jsonify({
            'draft': draft_payload,
            'versions': version_items,
        })
    except Exception as e:
        logging.error(f"Error loading trip journal history: {e}")
        return jsonify({'error': 'Failed to load trip journal history'}), 500


@app.route('/api/journal-media', methods=['POST'])
@firebase_auth_required
def upload_journal_media():
    """Upload a journal image attachment and return a static URL."""
    _auth_user = _get_authenticated_user(optional=False)

    if 'image' not in request.files:
        return jsonify({'error': 'image file is required'}), 400

    image_file = request.files['image']
    if not image_file or not image_file.filename:
        return jsonify({'error': 'image file is required'}), 400

    if not allowed_file(image_file.filename):
        return jsonify({'error': 'Unsupported file type'}), 400

    try:
        original_name = secure_filename(image_file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
        filename = f"journal_{timestamp}_{original_name}"
        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'journal')
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, filename)
        image_file.save(file_path)

        media_url = '/' + file_path.replace('\\', '/')
        return jsonify({
            'message': 'Journal media uploaded.',
            'media_url': media_url,
        }), 201
    except Exception as e:
        logging.error(f"Error uploading journal media: {e}")
        return jsonify({'error': 'Failed to upload journal media'}), 500

@app.route('/blog/<int:post_id>')
def blog_post(post_id):
    conn = get_db_connection()
    post = conn.execute('SELECT * FROM blog_posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        conn.close()
        return "Post not found", 404
    post = dict(post)
    post['tags'] = post.get('tags', '').split(',') if post.get('tags') else []
    if not post.get('image'):
        post['image'] = '/static/images/default_blog.jpg'
    comments = conn.execute('SELECT * FROM comments WHERE post_id = ? ORDER BY date_posted DESC', (post_id,)).fetchall()
    comments = [dict(row) for row in comments]
    conn.close()
    return render_template('blog_post.html', post=post, comments=comments)

@app.route('/blog/<int:post_id>/add_comment', methods=['POST'])
def add_comment(post_id):
    author = request.form.get('author')
    content = request.form.get('content')
    date_posted = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO comments (post_id, author, content, date_posted) VALUES (?, ?, ?, ?)',
        (post_id, author, content, date_posted)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('blog_post', post_id=post_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username in users and check_password_hash(users[username]['password'], password):
            session['user'] = username
            flash('Logged in successfully!', 'success')
            return redirect(url_for('profile'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('login'))

@app.route('/profile')
def profile():
    # For Firebase authentication, we'll let the frontend handle the auth check
    # The profile.html template has JavaScript that checks Firebase auth state
    return render_template('profile.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        if not username or not password or not email:
            flash('Please provide username, email, and password.', 'danger')
        elif username in users:
            flash('Username already exists. Please choose another.', 'danger')
        elif any(u['email'] == email for u in users.values()):
            flash('Email already registered. Please use another.', 'danger')
        else:
            users[username] = {
                'password': generate_password_hash(password),
                'email': email
            }
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    step = request.args.get('step', 'email')
    if request.method == 'POST':
        if step == 'email':
            email = request.form.get('email')
            user = next((u for u in users if users[u]['email'] == email), None)
            if not email or not user:
                flash('Email not found.', 'danger')
            else:
                otp = ''.join(random.choices(string.digits, k=6))
                session['reset_email'] = email
                session['reset_otp'] = otp
                # Send OTP via email
                try:
                    msg = Message('Your OTP for Password Reset', recipients=[email])
                    msg.body = f'Your OTP for password reset is: {otp}'
                    mail.send(msg)
                    flash('OTP sent to your email.', 'success')
                except Exception as e:
                    flash('Failed to send OTP email. Please try again later.', 'danger')
                return redirect(url_for('forgot_password', step='otp'))
        elif step == 'otp':
            otp = request.form.get('otp')
            new_password = request.form.get('new_password')
            email = session.get('reset_email')
            user = next((u for u in users if users[u]['email'] == email), None)
            if not otp or not new_password:
                flash('Please provide OTP and new password.', 'danger')
            elif otp != session.get('reset_otp'):
                flash('Invalid OTP.', 'danger')
            elif not user:
                flash('Session expired or invalid email.', 'danger')
            else:
                users[user]['password'] = generate_password_hash(new_password)
                session.pop('reset_email', None)
                session.pop('reset_otp', None)
                flash('Password reset successful! Please log in.', 'success')
                return redirect(url_for('login'))
    return render_template('forgot_password.html', step=step)

@app.route("/login/google")
def login_google():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    assert resp.ok, resp.text
    user_info = resp.json()
    session['user'] = user_info["email"]
    flash("Logged in with Google!", "success")
    return redirect(url_for("profile"))

# --- SITE-WIDE LIVE SEARCH API ---
@app.route('/api/search')
def api_search():
    query = request.args.get('query', '').strip().lower()
    results = []

    if not query:
        return jsonify(results)

    try:
        conn = get_db_connection()

        # Search destinations from database
        destinations = conn.execute(
            '''SELECT name, category
               FROM destinations
               WHERE LOWER(name) LIKE ? OR LOWER(country) LIKE ? OR LOWER(location) LIKE ?
               ORDER BY rating DESC, name ASC
               LIMIT 10''',
            (f"%{query}%", f"%{query}%", f"%{query}%")
        ).fetchall()

        for dest in destinations:
            anchor = dest['name'].replace(' ', '_')
            results.append({
                'type': 'Destination',
                'name': dest['name'],
                'url': f"/destinations#{anchor}"
            })

        # Search blog posts from the database
        posts = conn.execute('SELECT id, title FROM blog_posts').fetchall()
        for post in posts:
            if query in post['title'].lower():
                results.append({
                    'type': 'Blog',
                    'name': post['title'],
                    'url': f"/blog/{post['id']}"
                })
        conn.close()
    except Exception as e:
        # Log the error and continue
        logging.error(f"/api/search error: {e}")

    return jsonify(results)


@app.route('/api/render-itinerary', methods=['POST'])
def render_itinerary_from_data():
    """Render itinerary HTML from structured itinerary JSON."""
    data = request.json or {}
    itinerary_data = data.get('itinerary_data')

    if not isinstance(itinerary_data, dict) or not isinstance(itinerary_data.get('days'), list):
        return jsonify({"error": "itinerary_data with days list is required"}), 400

    try:
        itinerary_html = format_itinerary_response(json.dumps(itinerary_data))
        return jsonify({"itinerary": itinerary_html})
    except Exception as e:
        logging.error(f"Error rendering itinerary data: {e}")
        return jsonify({"error": "Failed to render itinerary"}), 500


@app.route('/api/generate-trip-journal', methods=['POST'])
def generate_trip_journal():
    """Generate an AI-powered trip recap journal from itinerary JSON."""
    data = request.json or {}
    itinerary_data = data.get('itinerary_data')

    if not isinstance(itinerary_data, dict) or not isinstance(itinerary_data.get('days'), list) or not itinerary_data.get('days'):
        return jsonify({"error": "itinerary_data must include a non-empty days list."}), 400

    destination = str(data.get('destination') or itinerary_data.get('destination') or '').strip() or 'Your trip'
    purpose = str(data.get('purpose') or '').strip()
    tone = str(data.get('tone') or 'vivid').strip().lower() or 'vivid'
    max_words = _coerce_positive_int(data.get('max_words')) or 280
    max_words = min(max_words, 700)

    fallback_journal = _build_fallback_trip_journal(destination, purpose, itinerary_data)

    can_proceed, rate_limit_error = check_rate_limit()
    if not can_proceed:
        return jsonify({"error": rate_limit_error}), 429

    try:
        record_api_call()
        prompt = generate_trip_journal_prompt(
            destination=destination,
            purpose=purpose,
            itinerary_data=itinerary_data,
            tone=tone,
            max_words=max_words,
        )
        response = model.generate_content(prompt)
        response_text = response.text.strip() if response and getattr(response, 'text', None) else ''
        parsed = parse_json_response(response_text)

        if isinstance(parsed, dict):
            title = str(parsed.get('title') or fallback_journal['title']).strip() or fallback_journal['title']
            recap = str(parsed.get('recap') or parsed.get('content') or '').strip() or fallback_journal['recap']

            raw_highlights = parsed.get('highlights')
            highlights = []
            if isinstance(raw_highlights, list):
                for item in raw_highlights:
                    text = str(item).strip()
                    if text:
                        highlights.append(text)
                    if len(highlights) >= 6:
                        break
            if not highlights:
                highlights = fallback_journal['highlights']

            takeaway = str(parsed.get('takeaway') or fallback_journal['takeaway']).strip()
            journal = {
                'title': title,
                'recap': recap,
                'highlights': highlights,
                'takeaway': takeaway,
                'tone': tone,
                'word_count': len(recap.split()),
            }
            return jsonify({'journal': journal, 'source': 'ai'})

        fallback_payload = {
            **fallback_journal,
            'tone': tone,
            'word_count': len(fallback_journal['recap'].split()),
        }
        return jsonify({
            'journal': fallback_payload,
            'source': 'fallback',
            'warning': 'AI response could not be parsed. Showing a local recap instead.',
        })
    except Exception as e:
        logging.warning(f"Trip journal generation failed; serving fallback recap: {e}")
        fallback_payload = {
            **fallback_journal,
            'tone': tone,
            'word_count': len(fallback_journal['recap'].split()),
        }
        return jsonify({
            'journal': fallback_payload,
            'source': 'fallback',
            'warning': 'AI recap unavailable. Showing a local recap instead.',
        })


@app.route('/api/travel-price-hints', methods=['GET'])
def travel_price_hints():
    """Return live provider-backed price hints with reliable fallback estimation."""
    destination = str(request.args.get('destination', '')).strip()
    duration_raw = request.args.get('duration', '3')
    currency = str(request.args.get('currency', 'USD')).strip().upper() or 'USD'

    if not destination:
        return jsonify({"error": "destination is required"}), 400

    duration_days = _coerce_positive_int(duration_raw) or 3
    estimate_hints = _estimate_price_hints(destination, duration_days, currency)
    live_hints = _fetch_live_provider_price_hints(destination, duration_days, currency)
    hints = _merge_price_hints(estimate_hints, live_hints)
    return jsonify(hints)


@app.route('/api/events-feed', methods=['GET'])
def events_feed():
    """Return destination event suggestions for map integration."""
    destination = str(request.args.get('destination', '')).strip()
    start_date = str(request.args.get('start_date', '')).strip() or None
    end_date = str(request.args.get('end_date', '')).strip() or None
    category_filter = str(request.args.get('category', '')).strip().lower() or None

    if not destination:
        return jsonify({"error": "destination is required"}), 400

    events = _fetch_ticketmaster_events(destination, start_date, end_date)
    source = 'ticketmaster' if events else 'fallback'

    if not events:
        events = _generate_fallback_events(destination, start_date, end_date)

    if category_filter and category_filter != 'all':
        events = [evt for evt in events if str(evt.get('category', '')).lower() == category_filter]

    return jsonify({
        "destination": destination,
        "source": source,
        "events": events,
    })

if __name__ == '__main__':
    # Run on localhost with specific port for Firebase
    app.run(host='localhost', port=5000, debug=True)
