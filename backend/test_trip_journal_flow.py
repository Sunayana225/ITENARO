import os
import sqlite3
import sys
from pathlib import Path

import pytest


os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("WEATHER_API_KEY", "test-weather-key")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app as app_module


def _create_tables(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        '''
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
        CREATE TABLE IF NOT EXISTS itinerary_collaborators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            itinerary_id INTEGER NOT NULL,
            collaborator_uid TEXT,
            invited_email TEXT,
            invited_by_uid TEXT NOT NULL,
            status TEXT DEFAULT 'accepted',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(itinerary_id, collaborator_uid),
            UNIQUE(itinerary_id, invited_email)
        );
        CREATE TABLE IF NOT EXISTS itinerary_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            itinerary_id INTEGER NOT NULL,
            actor_uid TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS blog_posts (
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
        '''
    )
    conn.commit()
    conn.close()


@pytest.fixture
def client_with_auth(tmp_path, monkeypatch):
    db_path = tmp_path / "trip_journal_test.db"
    _create_tables(str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO saved_itineraries
           (firebase_uid, share_token, destination, itinerary_html, itinerary_data)
           VALUES (?, ?, ?, ?, ?)''',
        ("user-1", "journal-token-1", "Paris", "<div>itinerary</div>", '{"days": []}'),
    )
    conn.commit()
    conn.close()

    auth_context = {"uid": "user-1", "email": "owner@example.com", "provider": "test"}

    monkeypatch.setattr(app_module, "DATABASE", str(db_path))
    monkeypatch.setattr(app_module, "_get_authenticated_user", lambda optional=False: auth_context)
    monkeypatch.setattr(app_module, "check_rate_limit", lambda: (True, None))
    monkeypatch.setattr(app_module, "record_api_call", lambda: None)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client, auth_context, str(db_path)


def _sample_itinerary():
    return {
        "destination": "Paris",
        "summary": "A culture-first weekend with museum mornings and riverside evenings.",
        "days": [
            {
                "day": 1,
                "title": "Day 1 - Arrival and Icons",
                "places": [
                    {
                        "name": "Eiffel Tower",
                        "time": "9 AM",
                        "description": "Start with skyline views.",
                        "cost_estimate": "$25",
                    },
                    {
                        "name": "Louvre Museum",
                        "time": "12 PM",
                        "description": "Explore classic art.",
                        "cost_estimate": "$30",
                    },
                ],
                "food_recommendations": [],
                "tips": "Book timed entries early.",
            }
        ],
    }


def test_generate_trip_journal_requires_days_list(client_with_auth):
    client, _auth, _db_path = client_with_auth

    response = client.post("/api/generate-trip-journal", json={"itinerary_data": {"summary": "x"}})

    assert response.status_code == 400
    assert "days list" in response.get_json()["error"].lower()


def test_generate_trip_journal_ai_success(client_with_auth, monkeypatch):
    client, _auth, _db_path = client_with_auth

    class StubModel:
        @staticmethod
        def generate_content(_prompt):
            class StubResponse:
                text = (
                    '{"title": "Paris Afterglow", '
                    '"recap": "I spent the trip balancing iconic landmarks with slower neighborhood walks.", '
                    '"highlights": ["Sunrise at Eiffel Tower", "Louvre deep dive", "Seine evening stroll"], '
                    '"takeaway": "Start early and leave room for unplanned discoveries."}'
                )

            return StubResponse()

    monkeypatch.setattr(app_module, "model", StubModel())

    response = client.post(
        "/api/generate-trip-journal",
        json={
            "itinerary_data": _sample_itinerary(),
            "destination": "Paris",
            "purpose": "Leisure",
            "tone": "reflective",
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["source"] == "ai"
    assert body["journal"]["title"] == "Paris Afterglow"
    assert len(body["journal"]["highlights"]) >= 1


def test_generate_trip_journal_fallback_when_ai_fails(client_with_auth, monkeypatch):
    client, _auth, _db_path = client_with_auth

    class BrokenModel:
        @staticmethod
        def generate_content(_prompt):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(app_module, "model", BrokenModel())

    response = client.post(
        "/api/generate-trip-journal",
        json={"itinerary_data": _sample_itinerary(), "destination": "Paris"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["source"] == "fallback"
    assert "journal" in body


def test_publish_trip_journal_requires_title_and_content(client_with_auth):
    client, _auth, _db_path = client_with_auth

    response = client.post("/api/publish-trip-journal", json={"title": "Missing content"})

    assert response.status_code == 400
    assert "title and content" in response.get_json()["error"].lower()


def test_publish_trip_journal_success(client_with_auth):
    client, _auth, db_path = client_with_auth

    response = client.post(
        "/api/publish-trip-journal",
        json={
            "title": "My Paris Journal",
            "content": "A wonderful trip with cafes, art, and evening walks.",
            "destination": "Paris",
            "tags": ["paris", "journal"],
            "itinerary_id": 1,
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["post_id"] >= 1
    assert "/blog/" in body["blog_url"]

    conn = sqlite3.connect(db_path)
    post = conn.execute("SELECT title, author, tags FROM blog_posts WHERE id = ?", (body["post_id"],)).fetchone()
    activity = conn.execute(
        "SELECT action FROM itinerary_activity_log WHERE itinerary_id = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert post is not None
    assert post[0] == "My Paris Journal"
    assert post[1] == "owner"
    assert "paris" in post[2]
    assert activity is not None
    assert activity[0] == "publish_trip_journal"


def test_publish_trip_journal_forbidden_for_outsider(client_with_auth):
    client, auth, _db_path = client_with_auth
    auth["uid"] = "outsider-user"

    response = client.post(
        "/api/publish-trip-journal",
        json={
            "title": "Unauthorized",
            "content": "Should not publish",
            "itinerary_id": 1,
        },
    )

    assert response.status_code == 403
    assert "forbidden" in response.get_json()["error"].lower()
