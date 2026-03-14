import os
import sqlite3
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("WEATHER_API_KEY", "test-weather-key")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app as app_module


def _create_test_tables(db_path):
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
        '''
    )
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "packing_state_test.db"
    _create_test_tables(str(db_path))

    monkeypatch.setattr(app_module, "DATABASE", str(db_path))
    monkeypatch.setattr(
        app_module,
        "_get_authenticated_user",
        lambda optional=False: {"uid": "user-1", "email": "user1@example.com", "provider": "test"},
    )

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_save_packing_state_requires_trip_key(client):
    response = client.post("/api/packing-list-state", json={"checked_state": {"0_0": True}})

    assert response.status_code == 400
    assert "trip_key" in response.get_json()["error"]


def test_save_and_get_packing_state_success(client):
    payload = {
        "trip_key": "paris|5|leisure",
        "checked_state": {"0_0": True, "1_2": False},
        "packing_data": {
            "categories": [
                {"name": "Clothing", "items": [{"item": "Jacket", "quantity": 1}]}
            ],
            "pro_tips": ["Pack layers"],
        },
    }

    save_response = client.post("/api/packing-list-state", json=payload)
    assert save_response.status_code == 200

    get_response = client.get("/api/packing-list-state/user-1?trip_key=paris|5|leisure")
    assert get_response.status_code == 200

    body = get_response.get_json()
    assert body["trip_key"] == "paris|5|leisure"
    assert body["checked_state"]["0_0"] is True
    assert body["packing_data"]["categories"][0]["name"] == "Clothing"


def test_get_packing_state_other_user_forbidden(client):
    response = client.get("/api/packing-list-state/user-2?trip_key=rome|3|adventure")

    assert response.status_code == 403
    assert "ownership mismatch" in response.get_json()["error"].lower()


def test_save_packing_state_rejects_foreign_itinerary(client):
    conn = sqlite3.connect(app_module.DATABASE)
    conn.execute(
        '''INSERT INTO saved_itineraries
           (firebase_uid, share_token, destination, itinerary_html)
           VALUES (?, ?, ?, ?)''',
        ("user-2", "token-foreign", "Rome", "<div>itinerary</div>"),
    )
    conn.commit()
    conn.close()

    response = client.post(
        "/api/packing-list-state",
        json={
            "trip_key": "rome|3|adventure",
            "itinerary_id": 1,
            "checked_state": {},
        },
    )

    assert response.status_code == 403
    assert "ownership mismatch" in response.get_json()["error"].lower()
