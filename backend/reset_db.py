import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '../Database/blog.db')
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')

conn = sqlite3.connect(DB_PATH)
with open(SCHEMA_PATH, 'r') as f:
    conn.executescript(f.read())
conn.close()
print('Database has been reset!') 