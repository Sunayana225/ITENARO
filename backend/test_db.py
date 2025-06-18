#!/usr/bin/env python3
"""
Test script to verify database setup and show sample data
"""

import sqlite3
import os

def test_database():
    DB_PATH = os.path.join('..', 'Database', 'blog.db')
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        print("🔍 Testing Database Setup...")
        print("=" * 50)
        
        # Test destinations table
        print("\n📍 Destinations:")
        destinations = cursor.execute('SELECT * FROM destinations').fetchall()
        for dest in destinations:
            print(f"  • {dest['name']} ({dest['category']}) - {dest['location']}, {dest['country']} - ⭐{dest['rating']}")
        
        # Test user_profiles table structure
        print(f"\n👥 User Profiles Table Structure:")
        cursor.execute("PRAGMA table_info(user_profiles)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  • {col['name']} ({col['type']})")
        
        # Test wishlists table structure
        print(f"\n❤️ Wishlists Table Structure:")
        cursor.execute("PRAGMA table_info(wishlists)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  • {col['name']} ({col['type']})")
        
        # Test blog_posts table
        print(f"\n📝 Blog Posts:")
        posts = cursor.execute('SELECT COUNT(*) as count FROM blog_posts').fetchone()
        print(f"  • Total blog posts: {posts['count']}")
        
        conn.close()
        print("\n✅ Database setup successful!")
        print("\n🚀 Ready to test profile and wishlist features!")
        
    except Exception as e:
        print(f"❌ Database error: {e}")

if __name__ == "__main__":
    test_database()
