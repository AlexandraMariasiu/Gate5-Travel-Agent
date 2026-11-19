from src.models.slm_client import ask_model, DEFAULT_MODEL
from src.schemas.trip import TripRequest

# Remove markdown formatting from the model response
def clean_response(response):
    response = response.strip()

    if response.startswith("```json"):
        response = response[7:]
    elif response.startswith("```"):
        response = response[3:]

    if response.endswith("```"):
        response = response[:-3]

    return response.strip()

# Extract structured trip preferences from a user message
def extract_trip_request(user_message, model=DEFAULT_MODEL):
    prompt = f"""
You are a travel request extraction assistant.

Extract the travel preferences from the user message.
Return only a valid JSON object with the following fields:

{{
    "city": null,
    "days": null,
    "start_date": null,
    "interests": [],
    "pace": "balanced",
    "budget": null
}}

Rules:
- Do not invent missing information.
- Use null for unknown city, days, start_date and budget.
- Days must be an integer or null.
- Use YYYY-MM-DD for dates.
- Interests must be a list of strings.
- Pace must be relaxed, balanced or intensive.
- Use balanced if no pace is specified.
- Budget must be a string or null.
- Do not include explanations or markdown.

User message:
{user_message}
"""

    response = ask_model(prompt, model)

    if not response:
        raise ValueError("Empty response from the model")

    response = clean_response(response)

    return TripRequest.model_validate_json(response)