-- Drop existing tables if they exist
DROP TABLE IF EXISTS wishlists;
DROP TABLE IF EXISTS user_profiles;
DROP TABLE IF EXISTS destinations;
DROP TABLE IF EXISTS blog_posts;
DROP TABLE IF EXISTS comments;

-- Create user_profiles table
CREATE TABLE user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firebase_uid TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    bio TEXT,
    profile_picture TEXT,
    travel_preferences TEXT, -- JSON string
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Create destinations table
CREATE TABLE destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    image_url TEXT,
    location TEXT,
    country TEXT,
    rating REAL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Create wishlists table
CREATE TABLE wishlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    destination_id INTEGER NOT NULL,
    notes TEXT,
    priority INTEGER DEFAULT 1, -- 1=low, 2=medium, 3=high
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_profiles (id),
    FOREIGN KEY (destination_id) REFERENCES destinations (id),
    UNIQUE(user_id, destination_id)
);

-- Create blog_posts table
CREATE TABLE blog_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author TEXT NOT NULL,
    date_posted TEXT NOT NULL,
    location TEXT,
    country TEXT,
    state TEXT,
    category TEXT,
    tags TEXT,
    image TEXT
);

-- Create comments table
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    date_posted TEXT NOT NULL,
    FOREIGN KEY (post_id) REFERENCES blog_posts (id)
);

-- ============================================
-- PHASE 2 TABLES
-- ============================================

-- Saved itineraries with shareable links
CREATE TABLE IF NOT EXISTS saved_itineraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firebase_uid TEXT,
    share_token TEXT UNIQUE NOT NULL,
    destination TEXT NOT NULL,
    duration TEXT,
    budget TEXT,
    purpose TEXT,
    preferences TEXT, -- JSON string
    itinerary_html TEXT NOT NULL,
    itinerary_data TEXT, -- JSON structured data
    revision INTEGER DEFAULT 1,
    last_editor_uid TEXT,
    is_public INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Trip expenses for budget tracking
CREATE TABLE IF NOT EXISTS trip_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firebase_uid TEXT NOT NULL,
    itinerary_id INTEGER,
    category TEXT NOT NULL, -- food, transport, accommodation, activities, shopping, other
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    date TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
);

-- Digital passport - country stamps
CREATE TABLE IF NOT EXISTS digital_passport (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firebase_uid TEXT NOT NULL,
    country TEXT NOT NULL,
    country_code TEXT, -- ISO 3166-1 alpha-2
    visited_date TEXT,
    trip_notes TEXT,
    stamp_type TEXT DEFAULT 'visited', -- visited, blogged, wishlisted
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(firebase_uid, country, stamp_type)
);

-- Saved packing list states for cross-device sync
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

-- Itinerary collaborators
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

-- Activity log for itinerary collaboration
CREATE TABLE IF NOT EXISTS itinerary_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    itinerary_id INTEGER NOT NULL,
    actor_uid TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (itinerary_id) REFERENCES saved_itineraries (id)
);

-- Real-time collaborator presence heartbeat
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

-- Insert sample destinations
INSERT INTO destinations (name, description, category, image_url, location, country, rating) VALUES
('Maldives', 'Relax on stunning white beaches and explore coral reefs.', 'beach', '/static/images/maldives.jpg', 'Maldives', 'Maldives', 4.8),
('Rome', 'Discover ancient history in the heart of Italy.', 'historical', '/static/images/rome.jpg', 'Rome', 'Italy', 4.7),
('Mount Everest', 'Experience the ultimate adventure in the Himalayas.', 'adventure', '/static/images/everest.jpg', 'Nepal', 'Nepal', 4.9),
('Dubai', 'Enjoy luxury shopping, skyscrapers, and desert adventures.', 'luxury', '/static/images/dubai.jpg', 'Dubai', 'UAE', 4.6),
('Paris', 'The city of love with iconic landmarks and cuisine.', 'cultural', '/static/images/paris.jpg', 'Paris', 'France', 4.7),
('Tokyo', 'Modern metropolis with traditional culture and amazing food.', 'cultural', '/static/images/tokyo.jpg', 'Tokyo', 'Japan', 4.8),
('Bali', 'Tropical paradise with beautiful temples and beaches.', 'beach', '/static/images/bali.jpg', 'Bali', 'Indonesia', 4.6),
('New York', 'The city that never sleeps with endless attractions.', 'urban', '/static/images/newyork.jpg', 'New York', 'USA', 4.5);
