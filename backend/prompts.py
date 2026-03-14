# prompts.py
import json
import re


def generate_itinerary_prompt(destination, budget, duration, purpose, preferences):
    """
    Generates a detailed prompt for the Gemini API to create a travel itinerary.
    Requests structured JSON with coordinates for interactive mapping.
    """
    preferences_str = ", ".join(preferences)

    prompt = f"""Create a detailed {duration}-day travel itinerary for {destination}.
Budget: {budget}
Purpose: {purpose}
Preferences: {preferences_str}

IMPORTANT: You MUST respond with ONLY valid JSON (no markdown, no code fences, no extra text).
Use this exact JSON structure:

{{
  "destination": "{destination}",
  "summary": "A brief 2-3 sentence summary of the trip.",
  "weather_note": "Expected weather conditions during the trip.",
  "days": [
    {{
      "day": 1,
      "title": "Day 1 - Arrival & Exploration",
      "places": [
        {{
          "name": "Place Name",
          "lat": 48.8566,
          "lng": 2.3522,
          "time": "9:00 AM - 11:00 AM",
          "description": "What to do here and why it's great.",
          "cost_estimate": "$0 - $20"
        }}
      ],
      "food_recommendations": [
        {{
          "name": "Restaurant Name",
          "cuisine": "Type of cuisine",
          "price_range": "$10 - $30",
          "meal": "Lunch"
        }}
      ],
      "tips": "Helpful tips for the day."
    }}
  ],
  "budget_breakdown": {{
    "accommodation": "$X per night",
    "food": "$X per day",
    "transport": "$X per day",
    "activities": "$X total",
    "total_estimate": "$X total"
  }},
  "general_tips": ["Tip 1", "Tip 2"]
}}

Include realistic latitude and longitude coordinates for each place.
Make sure food_recommendations has at least 1-2 options per day.
Provide at least 3-4 places per day.
Return ONLY the JSON with no additional text."""

    return prompt


def generate_packing_list_prompt(destination, duration, purpose, preferences, weather_info=None):
    """
    Generates a prompt for the Gemini API to create a personalized packing checklist.
    """
    preferences_str = ", ".join(preferences) if preferences else "General"
    weather_str = ""
    if weather_info:
        weather_str = f"\nCurrent weather at destination: {weather_info.get('temperature', 'N/A')}°C, {weather_info.get('description', 'N/A')}, Humidity: {weather_info.get('humidity', 'N/A')}%"

    prompt = f"""Create a personalized packing checklist for a {duration}-day trip to {destination}.
Purpose: {purpose}
Activities planned: {preferences_str}{weather_str}

IMPORTANT: You MUST respond with ONLY valid JSON (no markdown, no code fences, no extra text).
Use this exact structure:

{{
  "destination": "{destination}",
  "categories": [
    {{
      "name": "Clothing",
      "icon": "👕",
      "items": [
        {{ "item": "T-shirts", "quantity": 4, "note": "Lightweight and breathable" }},
        {{ "item": "Jeans", "quantity": 2, "note": "" }}
      ]
    }},
    {{
      "name": "Toiletries",
      "icon": "🧴",
      "items": [
        {{ "item": "Sunscreen SPF 50", "quantity": 1, "note": "Essential for outdoor activities" }}
      ]
    }},
    {{
      "name": "Electronics",
      "icon": "📱",
      "items": [
        {{ "item": "Phone charger", "quantity": 1, "note": "" }}
      ]
    }},
    {{
      "name": "Documents",
      "icon": "📄",
      "items": [
        {{ "item": "Passport", "quantity": 1, "note": "Check expiry date" }}
      ]
    }},
    {{
      "name": "Health & Safety",
      "icon": "🏥",
      "items": [
        {{ "item": "First aid kit", "quantity": 1, "note": "" }}
      ]
    }},
    {{
      "name": "Activity-Specific Gear",
      "icon": "🎒",
      "items": [
        {{ "item": "Hiking boots", "quantity": 1, "note": "If hiking is planned" }}
      ]
    }}
  ],
  "pro_tips": ["Pack light - you can always buy essentials", "Roll clothes to save space"]
}}

Tailor the list to the destination's climate, culture, and planned activities.
Include 4-8 items per category. Be specific and practical.
Return ONLY the JSON with no additional text."""

    return prompt


def generate_day_replan_prompt(destination, day_number, current_day, instruction, budget="", purpose="", preferences=None):
    """Builds a focused prompt to regenerate a single itinerary day only."""
    preferences = preferences or []
    preferences_str = ", ".join(preferences) if preferences else "None specified"
    current_day_json = json.dumps(current_day, ensure_ascii=False, indent=2)

    prompt = f"""You are an expert travel planner. Re-plan only Day {day_number} for a trip to {destination}.
Budget context: {budget or 'Not specified'}
Purpose context: {purpose or 'Not specified'}
Preferences context: {preferences_str}

User instruction for changes:
"{instruction}"

Current Day {day_number} JSON:
{current_day_json}

IMPORTANT RULES:
1. Re-plan only this single day.
2. Keep realistic activity flow for one day.
3. Return ONLY valid JSON (no markdown, no extra text).
4. Use this exact structure:

{{
  "day": {day_number},
  "title": "Day {day_number} - Updated title",
  "places": [
    {{
      "name": "Place Name",
      "lat": 48.8566,
      "lng": 2.3522,
      "time": "9:00 AM - 11:00 AM",
      "description": "What to do and why",
      "cost_estimate": "$10 - $25"
    }}
  ],
  "food_recommendations": [
    {{
      "name": "Restaurant Name",
      "cuisine": "Cuisine",
      "price_range": "$12 - $30",
      "meal": "Lunch"
    }}
  ],
  "tips": "Helpful practical tip for this day"
}}

5. Include 3-6 places and at least 1 food recommendation.
6. Keep JSON fields complete and consistent.
"""

    return prompt


def parse_json_response(response_text):
    """
    Attempts to parse JSON from the Gemini response, handling markdown code fences.
    Returns parsed dict or None.
    """
    # Strip whitespace
    text = response_text.strip()

    # Remove markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def format_itinerary_response(response_text):
    """
    Formats the raw response from the Gemini API into HTML.
    Tries to parse structured JSON first, falls back to plain text formatting.
    """
    parsed = parse_json_response(response_text)
    if parsed and 'days' in parsed:
        return format_structured_itinerary(parsed)

    # Fallback: plain text formatting
    response_text = response_text.replace("*", "")
    formatted_itinerary = response_text.replace("\n", "<br>")
    formatted_itinerary = f"<div class='itinerary-content'>{formatted_itinerary}</div>"
    return formatted_itinerary


def format_structured_itinerary(data):
    """
    Converts structured JSON itinerary into beautiful HTML.
    """
    html = "<div class='itinerary-content itinerary-structured'>"

    # Summary
    if data.get('summary'):
        html += f"<div class='itin-summary'><p>{data['summary']}</p></div>"

    # Weather note
    if data.get('weather_note'):
        html += f"<div class='itin-weather-note'>🌤️ {data['weather_note']}</div>"

    # Days
    for day in data.get('days', []):
        html += f"<div class='itin-day'>"
        day_title = day.get('title', f"Day {day.get('day', '')}")
        html += f"<h3 class='itin-day-title'>{day_title}</h3>"

        # Places
        for place in day.get('places', []):
            html += f"""<div class='itin-place'>
                <div class='itin-place-header'>
                    <span class='itin-place-name'>📍 {place.get('name', '')}</span>
                    <span class='itin-place-time'>{place.get('time', '')}</span>
                </div>
                <p class='itin-place-desc'>{place.get('description', '')}</p>
                {f"<span class='itin-place-cost'>💰 {place['cost_estimate']}</span>" if place.get('cost_estimate') else ''}
            </div>"""

        # Food
        foods = day.get('food_recommendations', [])
        if foods:
            html += "<div class='itin-food-section'><h4>🍽️ Where to Eat</h4>"
            for food in foods:
                html += f"""<div class='itin-food'>
                    <span class='itin-food-name'>{food.get('name', '')}</span>
                    <span class='itin-food-meta'>{food.get('cuisine', '')} · {food.get('price_range', '')} · {food.get('meal', '')}</span>
                </div>"""
            html += "</div>"

        # Tips
        if day.get('tips'):
            html += f"<div class='itin-day-tips'>💡 {day['tips']}</div>"

        html += "</div>"

    # Budget breakdown
    budget = data.get('budget_breakdown', {})
    if budget:
        html += "<div class='itin-budget'><h3>💰 Budget Breakdown</h3><div class='itin-budget-grid'>"
        for key, val in budget.items():
            label = key.replace('_', ' ').title()
            html += f"<div class='itin-budget-item'><span class='itin-budget-label'>{label}</span><span class='itin-budget-value'>{val}</span></div>"
        html += "</div></div>"

    # General tips
    tips = data.get('general_tips', [])
    if tips:
        html += "<div class='itin-general-tips'><h3>📝 General Tips</h3><ul>"
        for tip in tips:
            html += f"<li>{tip}</li>"
        html += "</ul></div>"

    html += "</div>"
    return html