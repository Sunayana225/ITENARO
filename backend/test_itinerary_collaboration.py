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
        '''
    )
    conn.commit()
    conn.close()


@pytest.fixture
def client_with_auth(tmp_path, monkeypatch):
    db_path = tmp_path / "itinerary_collab_test.db"
    _create_tables(str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO saved_itineraries
           (firebase_uid, share_token, destination, itinerary_html)
           VALUES (?, ?, ?, ?)''',
        ("user-1", "share-token-1", "Paris", "<div>itinerary</div>")
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(app_module, "DATABASE", str(db_path))

    auth_context = {"uid": "user-1", "email": "user1@example.com", "provider": "test"}

    def _fake_auth(optional=False):
        return auth_context

    monkeypatch.setattr(app_module, "_get_authenticated_user", _fake_auth)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client, auth_context


def test_owner_can_invite_collaborator(client_with_auth):
    client, _auth = client_with_auth

    response = client.post(
        "/api/itineraries/1/invite",
        json={"collaborator_uid": "user-2"},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["collaborator_uid"] == "user-2"


def test_non_owner_cannot_invite(client_with_auth):
    client, auth = client_with_auth
    auth["uid"] = "user-3"

    response = client.post(
        "/api/itineraries/1/invite",
        json={"collaborator_uid": "user-4"},
    )

    assert response.status_code == 403
    assert "owner" in response.get_json()["error"].lower()


def test_collaborator_can_update_itinerary(client_with_auth):
    client, auth = client_with_auth

    invite_response = client.post(
        "/api/itineraries/1/invite",
        json={"collaborator_uid": "user-2"},
    )
    assert invite_response.status_code == 201

    auth["uid"] = "user-2"
    update_response = client.put(
        "/api/itineraries/1",
        json={"budget": "$1900", "purpose": "Adventure"},
    )

    assert update_response.status_code == 200
    assert "updated" in update_response.get_json()["message"].lower()


def test_outsider_cannot_view_activity(client_with_auth):
    client, auth = client_with_auth

    invite_response = client.post(
        "/api/itineraries/1/invite",
        json={"collaborator_uid": "user-2"},
    )
    assert invite_response.status_code == 201

    auth["uid"] = "user-4"
    activity_response = client.get("/api/itineraries/1/activity")

    assert activity_response.status_code == 403
    assert "forbidden" in activity_response.get_json()["error"].lower()
