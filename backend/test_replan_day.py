import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = PROJECT_ROOT / "Database"
DATABASE_DIR.mkdir(exist_ok=True)

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("WEATHER_API_KEY", "test-weather-key")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app as app_module


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, text="{}"):
        self._text = text

    def generate_content(self, _prompt):
        return _FakeResponse(self._text)


def _base_itinerary():
    return {
        "destination": "Paris",
        "days": [
            {
                "day": 1,
                "title": "Day 1 - City Icons",
                "places": [
                    {
                        "name": "Eiffel Tower",
                        "lat": 48.8584,
                        "lng": 2.2945,
                        "time": "9:00 AM - 11:00 AM",
                        "description": "Morning visit",
                        "cost_estimate": "$35",
                    }
                ],
                "food_recommendations": [
                    {
                        "name": "Cafe Lumiere",
                        "cuisine": "French",
                        "price_range": "$15-$30",
                        "meal": "Lunch",
                    }
                ],
                "tips": "Book museum slots early.",
            },
            {
                "day": 2,
                "title": "Day 2 - Art and River",
                "places": [
                    {
                        "name": "Louvre Museum",
                        "lat": 48.8606,
                        "lng": 2.3376,
                        "time": "10:00 AM - 1:00 PM",
                        "description": "Main galleries",
                        "cost_estimate": "$20",
                    }
                ],
                "food_recommendations": [
                    {
                        "name": "Bistro Seine",
                        "cuisine": "French",
                        "price_range": "$20-$40",
                        "meal": "Dinner",
                    }
                ],
                "tips": "Use metro pass.",
            },
        ],
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "check_rate_limit", lambda: (True, None))
    monkeypatch.setattr(app_module, "record_api_call", lambda: None)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_replan_day_requires_required_fields(client):
    response = client.post("/api/replan-day", json={})

    assert response.status_code == 400
    assert "required" in response.get_json()["error"].lower()


def test_replan_day_rejects_invalid_day_number(client):
    payload = {
        "itinerary_data": _base_itinerary(),
        "day_number": "abc",
        "instruction": "Make this day easier.",
    }

    response = client.post("/api/replan-day", json=payload)

    assert response.status_code == 400
    assert "day_number" in response.get_json()["error"]


def test_replan_day_returns_not_found_for_missing_day(client):
    payload = {
        "itinerary_data": _base_itinerary(),
        "day_number": 5,
        "instruction": "Shift this day to indoor attractions.",
    }

    response = client.post("/api/replan-day", json=payload)

    assert response.status_code == 404
    assert "not found" in response.get_json()["error"].lower()


def test_replan_day_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(app_module, "check_rate_limit", lambda: (False, "Rate limit hit"))

    payload = {
        "itinerary_data": _base_itinerary(),
        "day_number": 1,
        "instruction": "Make this day budget-friendly.",
    }
    response = client.post("/api/replan-day", json=payload)

    assert response.status_code == 429
    assert response.get_json()["error"] == "Rate limit hit"


def test_replan_day_invalid_ai_response_returns_500(client, monkeypatch):
    monkeypatch.setattr(app_module, "model", _FakeModel(text="not valid json"))
    monkeypatch.setattr(app_module, "parse_json_response", lambda _text: None)

    payload = {
        "itinerary_data": _base_itinerary(),
        "day_number": 1,
        "instruction": "Add fewer crowded locations.",
    }
    response = client.post("/api/replan-day", json=payload)

    assert response.status_code == 500
    assert "invalid day format" in response.get_json()["error"].lower()


def test_replan_day_success_replaces_only_target_day(client, monkeypatch):
    monkeypatch.setattr(app_module, "model", _FakeModel(text="{}"))
    monkeypatch.setattr(
        app_module,
        "parse_json_response",
        lambda _text: {
            "day": 2,
            "title": "Day 2 - Food Streets and Galleries",
            "places": [
                {
                    "name": "Le Marais",
                    "lat": 48.8579,
                    "lng": 2.3622,
                    "time": "11:00 AM - 2:00 PM",
                    "description": "Walk and shop",
                    "cost_estimate": "$0 - $25",
                },
                {
                    "name": "Musee d'Orsay",
                    "lat": 48.8600,
                    "lng": 2.3266,
                    "time": "3:00 PM - 5:00 PM",
                    "description": "Impressionist art",
                    "cost_estimate": "$18",
                },
            ],
            "tips": "Reserve tickets in advance.",
        },
    )
    monkeypatch.setattr(app_module, "format_itinerary_response", lambda _text: "<div>ok</div>")

    original = _base_itinerary()
    payload = {
        "itinerary_data": deepcopy(original),
        "day_number": 2,
        "instruction": "Focus on food neighborhoods and lighter museum time.",
    }
    response = client.post("/api/replan-day", json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["day_number"] == 2

    updated_days = body["itinerary_data"]["days"]
    assert updated_days[0] == original["days"][0]
    assert updated_days[1]["title"] == "Day 2 - Food Streets and Galleries"
    assert len(updated_days[1]["places"]) == 2
    assert updated_days[1]["food_recommendations"] == original["days"][1]["food_recommendations"]
