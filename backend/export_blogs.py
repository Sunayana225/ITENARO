import sqlite3
import os
import csv

DB_PATH = os.path.join(os.path.dirname(__file__), '../Database/blog.db')
EXPORT_PATH = os.path.join(os.path.dirname(__file__), 'blog_posts_backup.csv')

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('SELECT * FROM blog_posts')
rows = cursor.fetchall()
columns = [desc[0] for desc in cursor.description]

with open(EXPORT_PATH, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(columns)
    writer.writerows(rows)

conn.close()
print(f'Exported {len(rows)} blog posts to {EXPORT_PATH}') 