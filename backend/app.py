import sys
import os
import json
import logging
import requests  # Import requests for weather API
import random
import string
import sqlite3
import time
from datetime import datetime, timedelta  # Import datetime for blog post timestamps
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import google.generativeai as genai
from prompts import generate_itinerary_prompt, format_itinerary_response, generate_packing_list_prompt, parse_json_response  # Import the functions
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
    """Return lightweight auth status used by frontend compatibility checks."""
    firebase_uid = request.headers.get('X-Firebase-UID') or request.args.get('uid')
    if firebase_uid:
        return jsonify({
            'authenticated': True,
            'uid': firebase_uid,
            'provider': 'firebase-client'
        })

    if 'user' in session:
        return jsonify({
            'authenticated': True,
            'uid': session['user'],
            'provider': 'flask-session'
        })

    return jsonify({'authenticated': False}), 401

# Profile and Wishlist API Routes
@app.route('/api/profile/<firebase_uid>', methods=['GET'])
def get_profile(firebase_uid):
    """Get user profile by Firebase UID."""
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
def create_profile():
    """Create a new user profile."""
    try:
        data = request.json
        conn = get_db_connection()

        cursor = conn.execute(
            '''INSERT INTO user_profiles (firebase_uid, email, display_name, bio, travel_preferences)
               VALUES (?, ?, ?, ?, ?)''',
            (data.get('firebase_uid'), data.get('email'), data.get('display_name', ''),
             data.get('bio', ''), data.get('travel_preferences', '{}'))
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
def update_profile(firebase_uid):
    """Update user profile."""
    try:
        data = request.json
        conn = get_db_connection()

        conn.execute(
            '''UPDATE user_profiles
               SET display_name = ?, bio = ?, travel_preferences = ?, updated_at = CURRENT_TIMESTAMP
               WHERE firebase_uid = ?''',
            (data.get('display_name'), data.get('bio'),
             data.get('travel_preferences'), firebase_uid)
        )
        conn.commit()

        # Get the updated profile
        profile = conn.execute(
            'SELECT * FROM user_profiles WHERE firebase_uid = ?',
            (firebase_uid,)
        ).fetchone()
        conn.close()

        return jsonify(dict(profile))
    except Exception as e:
        logging.error(f"Error updating profile: {e}")
        return jsonify({'error': 'Internal server error'}), 500

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
def get_wishlist(firebase_uid):
    """Get user's wishlist."""
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
def add_to_wishlist():
    """Add destination to user's wishlist."""
    try:
        data = request.json
        conn = get_db_connection()

        # Get user profile
        user = conn.execute(
            'SELECT id FROM user_profiles WHERE firebase_uid = ?',
            (data.get('user_uid'),)
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
def remove_from_wishlist(firebase_uid, destination_id):
    """Remove destination from user's wishlist."""
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
    ''')
    conn.close()

# Auto-create Phase 2 tables on startup
ensure_phase2_tables()


def generate_share_token():
    """Generate a unique share token."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


@app.route('/api/save-itinerary', methods=['POST'])
def save_itinerary():
    """Save an itinerary and generate a shareable link."""
    data = request.json
    share_token = generate_share_token()

    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO saved_itineraries
               (firebase_uid, share_token, destination, duration, budget, purpose,
                preferences, itinerary_html, itinerary_data, is_public)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                data.get('firebase_uid', ''),
                share_token,
                data.get('destination', ''),
                data.get('duration', ''),
                data.get('budget', ''),
                data.get('purpose', ''),
                json.dumps(data.get('preferences', [])),
                data.get('itinerary_html', ''),
                json.dumps(data.get('itinerary_data', {})),
                1 if data.get('is_public', True) else 0
            )
        )
        conn.commit()
        conn.close()

        share_url = f"{request.host_url}shared/{share_token}"
        return jsonify({
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
def get_my_itineraries(firebase_uid):
    """Get all saved itineraries for a user."""
    try:
        conn = get_db_connection()
        itineraries = conn.execute(
            'SELECT id, share_token, destination, duration, budget, purpose, is_public, created_at FROM saved_itineraries WHERE firebase_uid = ? ORDER BY created_at DESC',
            (firebase_uid,)
        ).fetchall()
        conn.close()
        return jsonify([dict(row) for row in itineraries])
    except Exception as e:
        logging.error(f"Error getting user itineraries: {e}")
        return jsonify({"error": "Internal error"}), 500


# ==================== PHASE 2 - BUDGET TRACKER ====================

@app.route('/api/expenses/<firebase_uid>', methods=['GET'])
def get_expenses(firebase_uid):
    """Get all expenses for a user, optionally filtered by itinerary."""
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
def add_expense():
    """Add a new expense."""
    data = request.json
    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO trip_expenses (firebase_uid, itinerary_id, category, description, amount, currency, date)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (
                data.get('firebase_uid', ''),
                data.get('itinerary_id'),
                data.get('category', 'other'),
                data.get('description', ''),
                float(data.get('amount', 0)),
                data.get('currency', 'USD'),
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
def delete_expense(expense_id):
    """Delete an expense."""
    try:
        conn = get_db_connection()
        conn.execute('DELETE FROM trip_expenses WHERE id = ?', (expense_id,))
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
def get_passport(firebase_uid):
    """Get digital passport data for a user."""
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
def add_stamp():
    """Add a country stamp to the digital passport."""
    data = request.json
    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT OR IGNORE INTO digital_passport
               (firebase_uid, country, country_code, visited_date, trip_notes, stamp_type)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (
                data.get('firebase_uid', ''),
                data.get('country', ''),
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

if __name__ == '__main__':
    # Run on localhost with specific port for Firebase
    app.run(host='localhost', port=5000, debug=True)
