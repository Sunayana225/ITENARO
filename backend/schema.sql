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