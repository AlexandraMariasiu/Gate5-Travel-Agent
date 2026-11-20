from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas import HoursStatus, Place, PlaceDataset, Provider


PLACES_PATH = Path(__file__).resolve().parents[1] / "data" / "places.json"


@pytest.fixture
def place_record():
    return {
        "provider": "openstreetmap",
        "provider_id": "node/123",
        "name": "Example Museum",
        "city": "Rome",
        "category": "museums",
        "lat": 41.9,
        "lon": 12.5,
        "source_url": "https://www.openstreetmap.org/node/123",
        "retrieved_at": "2026-11-15",
    }


def test_place_dataset_file_is_valid():
    dataset = PlaceDataset.model_validate_json(PLACES_PATH.read_bytes())

    assert dataset.places, "data/places.json must contain places"


def test_place_with_required_fields_uses_defaults(place_record):
    place = Place.model_validate(place_record)

    assert place.provider == Provider.OPENSTREETMAP
    assert place.retrieved_at == date(2026, 11, 15)
    assert place.opening_hours is None
    assert place.hours_status == HoursStatus.UNKNOWN
    assert place.est_visit_minutes == 60


@pytest.mark.parametrize(
    "field",
    ["provider", "provider_id", "name", "city", "category", "lat", "lon", "source_url", "retrieved_at"],
)
def test_place_requires_field(place_record, field):
    del place_record[field]

    with pytest.raises(ValidationError) as error:
        Place.model_validate(place_record)

    assert [(detail["loc"], detail["type"]) for detail in error.value.errors()] == [
        ((field,), "missing")
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "unknown"),
        ("provider_id", ""),
        ("name", ""),
        ("lat", -90.1),
        ("lat", 90.1),
        ("lon", -180.1),
        ("lon", 180.1),
        ("est_visit_minutes", 0),
        ("retrieved_at", "2026-02-30"),
        ("hours_staus", "known"),
    ],
)
def test_place_rejects_invalid_field(place_record, field, value):
    with pytest.raises(ValidationError) as error:
        Place.model_validate({**place_record, field: value})

    assert [detail["loc"] for detail in error.value.errors()] == [(field,)]


def test_place_accepts_known_opening_hours(place_record):
    place = Place.model_validate(
        {**place_record, "hours_status": "known", "opening_hours": "Tu-Su 09:00-19:00"}
    )

    assert place.hours_status == HoursStatus.KNOWN
    assert place.opening_hours == "Tu-Su 09:00-19:00"


@pytest.mark.parametrize("opening_hours", [None, ""])
def test_known_hours_require_opening_hours(place_record, opening_hours):
    with pytest.raises(ValidationError, match="opening_hours is empty"):
        Place.model_validate(
            {**place_record, "hours_status": "known", "opening_hours": opening_hours}
        )


def test_place_dataset_rejects_duplicate_provider_and_id(place_record):
    duplicate = {**place_record, "name": "Alternate Museum Name"}

    with pytest.raises(ValidationError, match="duplicate place"):
        PlaceDataset(city="Rome", version="example", places=[place_record, duplicate])


def test_place_dataset_allows_same_id_from_different_providers(place_record):
    other_provider = {
        **place_record,
        "provider": "opentripmap",
        "source_url": "https://opentripmap.com/en/card/node/123",
    }

    dataset = PlaceDataset(city="Rome", version="example", places=[place_record, other_provider])

    assert [place.provider for place in dataset.places] == [
        Provider.OPENSTREETMAP,
        Provider.OPENTRIPMAP,
    ]


def test_place_dataset_rejects_place_from_another_city(place_record):
    with pytest.raises(ValidationError, match="dataset city is Rome"):
        PlaceDataset(city="Rome", version="example", places=[{**place_record, "city": "Milan"}])
