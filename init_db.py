#!/usr/bin/env python3
"""Initialize the project database from the canonical schema file."""

import os
import sqlite3

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(ROOT_DIR, 'Database')
DB_PATH = os.path.join(DB_DIR, 'blog.db')
SCHEMA_PATH = os.path.join(ROOT_DIR, 'backend', 'schema.sql')


def main():
    os.makedirs(DB_DIR, exist_ok=True)

    if not os.path.exists(SCHEMA_PATH):
        print(f"Schema file not found: {SCHEMA_PATH}")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as schema_file:
            conn.executescript(schema_file.read())
        conn.commit()
        conn.close()
        print(f"Database initialized successfully at {DB_PATH}!")
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")


if __name__ == '__main__':
    main()