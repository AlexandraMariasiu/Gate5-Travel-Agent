import pytest
from unittest.mock import patch
from pydantic import ValidationError

from src.models.request_extractor import extract_trip_request


# Test a complete travel request
@patch("src.models.request_extractor.ask_model")
def test_complete_request(mock_model):
    mock_model.return_value = """
    {
        "city": "Rome",
        "days": 2,
        "start_date": "2026-12-10",
        "interests": ["history", "museums"],
        "pace": "relaxed",
        "budget": "300 EUR"
    }
    """

    result = extract_trip_request("Plan my trip to Rome.")

    assert result.city == "Rome"
    assert result.days == 2
    assert str(result.start_date) == "2026-12-10"
    assert result.interests == ["history", "museums"]
    assert result.pace == "relaxed"
    assert result.budget == "300 EUR"


# Test missing information
@patch("src.models.request_extractor.ask_model")
def test_missing_information(mock_model):
    mock_model.return_value = '{"city": "Rome"}'

    result = extract_trip_request("I want to visit Rome.")

    assert result.city == "Rome"
    assert result.days is None
    assert result.start_date is None
    assert result.interests == []
    assert result.pace == "balanced"
    assert result.budget is None


# Test JSON wrapped in markdown
@patch("src.models.request_extractor.ask_model")
def test_markdown_response(mock_model):
    mock_model.return_value = """
    ```json
    {"city": "Rome", "days": 2}
    ```
    """

    result = extract_trip_request("Two days in Rome.")

    assert result.city == "Rome"
    assert result.days == 2


# Test invalid JSON
@patch("src.models.request_extractor.ask_model")
def test_invalid_json(mock_model):
    mock_model.return_value = "Invalid JSON"

    with pytest.raises(ValidationError):
        extract_trip_request("Plan a trip.")


# Test invalid field values
@patch("src.models.request_extractor.ask_model")
def test_invalid_pace(mock_model):
    mock_model.return_value = '{"city": "Rome", "pace": "fast"}'

    with pytest.raises(ValidationError):
        extract_trip_request("Plan a trip.")


# Test an empty model response
@patch("src.models.request_extractor.ask_model")
def test_empty_response(mock_model):
    mock_model.return_value = ""

    with pytest.raises(ValueError):
        extract_trip_request("Plan a trip.")