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
    assert "source" in body
    assert "quoted_at" in body


def test_travel_price_hints_live_provider_path(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_fetch_live_provider_price_hints",
        lambda *_args, **_kwargs: {
            "destination": "Paris",
            "currency": "USD",
            "flight_from": 488.0,
            "hotel_from_per_night": 142.5,
            "hotel_estimated_total": 712.5,
            "flight_link": "https://example.com/flights",
            "hotel_link": "https://example.com/hotels",
            "source": "live-amadeus",
            "quoted_at": "2026-03-15T00:00:00Z",
            "note": "Live quote",
        },
    )

    response = client.get("/api/travel-price-hints?destination=Paris&duration=5")

    assert response.status_code == 200
    body = response.get_json()
    assert body["source"] == "live-amadeus"
    assert body["is_live"] is True
    assert body["flight_from"] == 488.0
    assert body["hotel_from_per_night"] == 142.5


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


def test_nearby_feed_requires_coordinates(client):
    response = client.get("/api/nearby-feed")

    assert response.status_code == 400
    assert "lat" in response.get_json()["error"].lower()


def test_nearby_feed_returns_places(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_fetch_nearby_places",
        lambda *_args, **_kwargs: (
            [
                {
                    "id": "osm-node-1",
                    "name": "Riverside Cafe",
                    "type": "cafe",
                    "lat": 12.9716,
                    "lng": 77.5946,
                    "distance_m": 420,
                    "source": "overpass",
                    "url": "https://www.openstreetmap.org/node/1",
                }
            ],
            "overpass",
        ),
    )

    response = client.get(
        "/api/nearby-feed?lat=12.9716&lng=77.5946&types=restaurants,cafe&radius=1200&limit=5"
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["source"] == "overpass"
    assert body["types"] == ["restaurant", "cafe"]
    assert len(body["places"]) == 1
    assert body["places"][0]["name"] == "Riverside Cafe"
