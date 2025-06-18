#!/usr/bin/env python3
"""
Localhost Runner for ITENARO Firebase Authentication
This script starts the Flask app on localhost:5000 for Firebase testing
"""

import os
import sys
import webbrowser
import time
from threading import Timer

def open_browser():
    """Open browser to the test page after a short delay"""
    time.sleep(2)  # Wait for Flask to start
    webbrowser.open('http://localhost:5000/localhost-test')

def main():
    print("🔥 Starting ITENARO with Firebase Authentication on Localhost")
    print("=" * 60)
    print("📍 Server will run on: http://localhost:5000")
    print("🧪 Test page will open at: http://localhost:5000/localhost-test")
    print("🌐 Main app available at: http://localhost:5000")
    print("=" * 60)
    
    # Change to backend directory
    backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
    if os.path.exists(backend_dir):
        os.chdir(backend_dir)
        print(f"📁 Changed to directory: {os.getcwd()}")
    else:
        print("❌ Backend directory not found!")
        sys.exit(1)
    
    # Open browser after delay
    Timer(2.0, open_browser).start()
    
    # Import and run Flask app
    try:
        from app import app
        print("🚀 Starting Flask server...")
        app.run(host='localhost', port=5000, debug=True)
    except ImportError as e:
        print(f"❌ Error importing Flask app: {e}")
        print("Make sure you're in the correct directory and have Flask installed")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
