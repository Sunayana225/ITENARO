import io
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
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            display_name TEXT,
            bio TEXT,
            profile_picture TEXT,
            travel_preferences TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        '''
    )
    conn.commit()
    conn.close()


@pytest.fixture
def profile_client(tmp_path, monkeypatch):
    db_path = tmp_path / "profile_features_test.db"
    _create_tables(str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO user_profiles
           (firebase_uid, email, display_name, bio, profile_picture, travel_preferences)
           VALUES (?, ?, ?, ?, ?, ?)''',
        ("user-1", "user1@example.com", "User One", "", None, "{}"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(app_module, "DATABASE", str(db_path))

    auth_context = {"uid": "user-1", "email": "user1@example.com", "provider": "test"}

    def _fake_auth(optional=False):
        return auth_context

    monkeypatch.setattr(app_module, "_get_authenticated_user", _fake_auth)

    upload_folder = tmp_path / "uploads"
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(upload_folder))

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client, auth_context, str(db_path)


def test_profile_picture_can_be_updated_and_cleared(profile_client):
    client, _auth, _db_path = profile_client

    update_response = client.put(
        "/api/profile/user-1",
        json={"profile_picture": "/static/uploads/profiles/new-avatar.png"},
    )
    assert update_response.status_code == 200
    updated = update_response.get_json()
    assert updated["profile_picture"] == "/static/uploads/profiles/new-avatar.png"

    clear_response = client.put(
        "/api/profile/user-1",
        json={"profile_picture": ""},
    )
    assert clear_response.status_code == 200
    cleared = clear_response.get_json()
    assert cleared["profile_picture"] is None


def test_upload_profile_picture_persists_file_and_url(profile_client):
    client, _auth, db_path = profile_client

    response = client.post(
        "/api/profile/user-1/picture",
        data={"image": (io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00"), "avatar.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["profile_picture"]
    assert "profile_user-1_" in body["profile_picture"]

    conn = sqlite3.connect(db_path)
    stored = conn.execute(
        "SELECT profile_picture FROM user_profiles WHERE firebase_uid = ?",
        ("user-1",),
    ).fetchone()
    conn.close()

    assert stored is not None
    assert stored[0] == body["profile_picture"]

    stored_path = Path(body["profile_picture"].lstrip("/"))
    assert stored_path.exists()


def test_upload_profile_picture_rejects_unsupported_type(profile_client):
    client, _auth, _db_path = profile_client

    response = client.post(
        "/api/profile/user-1/picture",
        data={"image": (io.BytesIO(b"not-an-image"), "avatar.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "unsupported" in response.get_json()["error"].lower()
