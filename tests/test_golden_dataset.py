from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas import GoldenDataset, GoldenTestCase, PlaceDataset


GOLDEN_PATH = Path(__file__).with_name("golden_dataset.json")
PLACES_PATH = Path(__file__).resolve().parents[1] / "data" / "places.json"


@pytest.fixture(scope="module")
def golden_dataset():
    return GoldenDataset.model_validate_json(GOLDEN_PATH.read_bytes())


@pytest.fixture
def golden_record():
    return {
        "test_id": "GD01",
        "category": "missing_information",
        "user_request": "Can you plan a trip for me?",
        "expected_behavior": "Ask for the destination.",
        "checks": ["information_reliability"],
        "validation_criteria": ["The answer asks for the destination."],
    }


def test_golden_dataset_has_unique_case_ids(golden_dataset):
    assert golden_dataset.cases, "golden_dataset.json must contain test cases"

    seen_ids = set()
    for case in golden_dataset.cases:
        assert case.test_id not in seen_ids, f"Duplicate golden case ID {case.test_id}"
        seen_ids.add(case.test_id)


def test_golden_cases_reference_places_in_declared_dataset(golden_dataset):
    places = PlaceDataset.model_validate_json(PLACES_PATH.read_bytes())
    assert golden_dataset.city == places.city
    assert golden_dataset.place_dataset_version == places.version

    place_keys = {(place.provider, place.provider_id) for place in places.places}
    for case in golden_dataset.cases:
        for index, place in enumerate(case.context.places):
            key = (place.provider, place.provider_id)
            assert key in place_keys, (
                f"{case.test_id} context.places[{index}] references unknown place {key}"
            )

        if case.context.existing_trip is not None:
            for day in case.context.existing_trip.days:
                for index, activity in enumerate(day.activities):
                    key = (activity.provider, activity.provider_id)
                    assert key in place_keys, (
                        f"{case.test_id} context.existing_trip day {day.day_number} "
                        f"activities[{index}] references unknown place {key}"
                    )


def test_golden_case_accepts_omitted_context(golden_record):
    case = GoldenTestCase.model_validate(golden_record)

    assert case.context.places == []
    assert case.context.existing_trip is None


@pytest.mark.parametrize(
    "field",
    ["test_id", "category", "user_request", "expected_behavior", "checks", "validation_criteria"],
)
def test_golden_case_requires_field(golden_record, field):
    del golden_record[field]

    with pytest.raises(ValidationError) as error:
        GoldenTestCase.model_validate(golden_record)

    assert [(detail["loc"], detail["type"]) for detail in error.value.errors()] == [
        ((field,), "missing")
    ]


@pytest.mark.parametrize(
    ("field", "value", "location"),
    [
        ("test_id", "GD1", ("test_id",)),
        ("category", "unknown", ("category",)),
        ("checks", ["unknown"], ("checks", 0)),
        ("expected_behaviour", "Ask for the destination.", ("expected_behaviour",)),
    ],
)
def test_golden_case_rejects_invalid_field(golden_record, field, value, location):
    with pytest.raises(ValidationError) as error:
        GoldenTestCase.model_validate({**golden_record, field: value})

    assert [detail["loc"] for detail in error.value.errors()] == [location]
