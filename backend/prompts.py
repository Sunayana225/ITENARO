# prompts.py

def generate_itinerary_prompt(destination, budget, duration, purpose, preferences):
    """
    Generates a detailed prompt for the Gemini API to create a travel itinerary.
    
    Args:
        destination (str): The travel destination.
        budget (str): The budget for the trip.
        duration (str): The duration of the trip in days.
        purpose (str): The purpose of the trip (e.g., Leisure, Business).
        preferences (list): A list of user preferences (e.g., Hiking, Museums).

    Returns:
        str: A formatted prompt for the Gemini API.
    """
    preferences_str = ", ".join(preferences)  # Convert list to a comma-separated string

    prompt = f"""
    Create a detailed {duration}-day travel itinerary for {destination}.
    Budget: {budget}
    Purpose: {purpose}
    Preferences: {preferences_str}

    Include:
    - Best places to visit
    - Weather forecast
    - Local food recommendations
    - Activities and experiences
    - A day-by-day itinerary plan
    """

    return prompt


def format_itinerary_response(response_text):
    """
    Formats the raw response from the Gemini API into a clean and readable itinerary.

    Args:
        response_text (str): The raw response text from the Gemini API.

    Returns:
        str: A formatted itinerary with HTML tags for display.
    """
    # Remove unwanted characters like stars (*)
    response_text = response_text.replace("*", "")

    # Replace newlines with HTML line breaks
    formatted_itinerary = response_text.replace("\n", "<br>")

    # Wrap the itinerary in HTML tags for better display
    formatted_itinerary = f"<div class='itinerary-content'>{formatted_itinerary}</div>"

    return formatted_itinerary