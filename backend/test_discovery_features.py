import os
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


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_render_itinerary_requires_days_list(client):
    response = client.post("/api/render-itinerary", json={"itinerary_data": {"summary": "x"}})

    assert response.status_code == 400
    assert "days list" in response.get_json()["error"].lower()


def test_render_itinerary_success(client):
    response = client.post(
        "/api/render-itinerary",
        json={
            "itinerary_data": {
                "days": [
                    {
                        "day": 1,
                        "title": "Day 1",
                        "places": [{"name": "Eiffel Tower", "time": "9 AM", "description": "Visit", "cost_estimate": "$20"}],
                        "food_recommendations": [],
                        "tips": "Book early",
                    }
                ]
            }
        },
    )

    assert response.status_code == 200
    assert "itinerary" in response.get_json()


def test_travel_price_hints_requires_destination(client):
    response = client.get("/api/travel-price-hints")

    assert response.status_code == 400
    assert "destination" in response.get_json()["error"].lower()


def test_travel_price_hints_success(client):
    response = client.get("/api/travel-price-hints?destination=Paris&duration=5")

    assert response.status_code == 200
    body = response.get_json()
    assert body["destination"] == "Paris"
    assert body["flight_from"] > 0
    assert body["hotel_from_per_night"] > 0


def test_events_feed_fallback_path(client, monkeypatch):
    monkeypatch.setattr(app_module, "_fetch_ticketmaster_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        app_module,
        "_generate_fallback_events",
        lambda destination, *_args, **_kwargs: [
            {
                "id": "fallback-1",
                "name": f"{destination} Night Market Walk",
                "category": "food",
                "lat": 12.97,
                "lng": 77.59,
                "day_suggestion": 1,
            }
        ],
    )

    response = client.get("/api/events-feed?destination=Bengaluru")

    assert response.status_code == 200
    body = response.get_json()
    assert body["source"] == "fallback"
    assert len(body["events"]) == 1
    assert body["events"][0]["category"] == "food"
