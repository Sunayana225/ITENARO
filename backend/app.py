import sys
import os
import logging
import requests  # Import requests for weather API
import random
import string
import sqlite3
import time
from datetime import datetime, timedelta  # Import datetime for blog post timestamps
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import google.generativeai as genai
from prompts import generate_itinerary_prompt, format_itinerary_response  # Import the functions
from werkzeug.security import check_password_hash, generate_password_hash
from flask_mail import Mail, Message
from flask_dance.contrib.google import make_google_blueprint, google

# Add the project root directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

    try:
        # Record the API call for rate limiting
        record_api_call()

        # Generate the prompt using the function from prompts.py
        prompt = generate_itinerary_prompt(destination, budget, duration, purpose, preferences)
        logging.info(f"Generated prompt: {prompt}")

        # Get the response from the Gemini API with retry logic
        max_retries = 3
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

    return jsonify({"itinerary": formatted_itinerary})

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

    # Hardcoded destinations (should match those in destinations.html)
    destinations = [
        {'name': 'Maldives', 'category': 'beach', 'url': '/destinations#Maldives'},
        {'name': 'Rome', 'category': 'historical', 'url': '/destinations#Rome'},
        {'name': 'Mount Everest', 'category': 'adventure', 'url': '/destinations#Mount_Everest'},
        {'name': 'Dubai', 'category': 'luxury', 'url': '/destinations#Dubai'},
    ]

    # Search destinations
    for dest in destinations:
        if query in dest['name'].lower():
            results.append({
                'type': 'Destination',
                'name': dest['name'],
                'url': dest['url']
            })

    # Search blog posts from the database
    try:
        conn = get_db_connection()
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
