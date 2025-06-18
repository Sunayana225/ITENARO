import sqlite3
import os

# Ensure the Database directory exists
if not os.path.exists('Database'):
    os.makedirs('Database')

# Connect to the database (or create it if it doesn't exist)
db_path = 'Database/blog.db'
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create blog_posts table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS blog_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        author TEXT NOT NULL,
        date_posted DATETIME DEFAULT CURRENT_TIMESTAMP,
        likes INTEGER DEFAULT 0,
        dislikes INTEGER DEFAULT 0
    )
    ''')

    # Create comments table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        date_posted DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (post_id) REFERENCES blog_posts (id)
    )
    ''')

    # Commit changes and close the connection
    conn.commit()
    conn.close()

    print(f"Database initialized successfully at {db_path}!")
except sqlite3.Error as e:
    print(f"An error occurred: {e}")