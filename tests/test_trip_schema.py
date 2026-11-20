from datetime import date

import pytest
from pydantic import ValidationError

from src.schemas import Activity, Day, Pace, Provider, Trip, TripRequest


@pytest.fixture
def activity_record():
    return {
        "provider": "openstreetmap",
        "provider_id": "relation/1834818",
        "name": "Colosseum",
        "start": "09:00",
        "end": "11:00",
    }


@pytest.mark.parametrize("day_count", [1, 3])
def test_trip_accepts_supported_day_counts(day_count, activity_record):
    trip = Trip.model_validate(
        {
            "city": "Rome",
            "days": [
                {
                    "day_number": day_number,
                    "date": f"2026-12-{day_number:02d}",
                    "activities": [activity_record],
                }
                for day_number in range(1, day_count + 1)
            ],
        }
    )

    assert len(trip.days) == day_count
    assert trip.days[0].date == date(2026, 12, 1)
    assert trip.days[0].activities[0].provider == Provider.OPENSTREETMAP
    assert trip.pace == Pace.BALANCED


@pytest.mark.parametrize("day_count", [0, 4])
def test_trip_rejects_unsupported_day_counts(day_count):
    days = [{"day_number": day_number} for day_number in range(1, day_count + 1)]

    with pytest.raises(ValidationError) as error:
        Trip.model_validate({"city": "Rome", "days": days})

    assert [detail["loc"] for detail in error.value.errors()] == [("days",)]


@pytest.mark.parametrize(
    ("schema", "record", "field"),
    [
        (Trip, {"days": [{"day_number": 1}]}, "city"),
        (Trip, {"city": "Rome"}, "days"),
        (Day, {}, "day_number"),
    ],
)
def test_itinerary_requires_field(schema, record, field):
    with pytest.raises(ValidationError) as error:
        schema.model_validate(record)

    assert [(detail["loc"], detail["type"]) for detail in error.value.errors()] == [
        ((field,), "missing")
    ]


@pytest.mark.parametrize("field", ["provider", "provider_id", "name", "start", "end"])
def test_activity_requires_field(activity_record, field):
    del activity_record[field]

    with pytest.raises(ValidationError) as error:
        Activity.model_validate(activity_record)

    assert [(detail["loc"], detail["type"]) for detail in error.value.errors()] == [
        ((field,), "missing")
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start", "9:00"),
        ("start", "24:00"),
        ("end", "11:60"),
        ("end", "11:00 AM"),
        ("provider", "unknown"),
        ("pinnned", True),
    ],
)
def test_activity_rejects_invalid_field(activity_record, field, value):
    with pytest.raises(ValidationError) as error:
        Activity.model_validate({**activity_record, field: value})

    assert [detail["loc"] for detail in error.value.errors()] == [(field,)]


def test_trip_request_accepts_missing_preferences():
    request = TripRequest()

    assert request.city is None
    assert request.days is None
    assert request.start_date is None
    assert request.interests == []
    assert request.pace == Pace.BALANCED
    assert request.budget is None
