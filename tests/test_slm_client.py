import pytest
from unittest.mock import patch

from src.models.slm_client import ask_model


# Test a successful model response
@patch("src.models.slm_client.client.chat.completions.create")
def test_ask_model(mock_create):
    mock_create.return_value.choices[0].message.content = "Rome"

    result = ask_model("What is the capital of Italy?")

    assert result == "Rome"
    mock_create.assert_called_once()


# Test an unsupported model
def test_invalid_model():
    with pytest.raises(ValueError):
        ask_model("Hello", "unknown-model")


# Test a connection failure
@patch("src.models.slm_client.client.chat.completions.create")
def test_connection_failure(mock_create):
    mock_create.side_effect = ConnectionError("Server unavailable")

    with pytest.raises(ConnectionError):
        ask_model("Hello")