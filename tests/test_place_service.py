from src.places.place_service import get_place_details, search_places
from src.schemas import Provider


def test_search_places_filters_by_interest_tag():
    places = search_places("Rome", ["history"])

    assert places
    assert all(
        place.category == "historic"
        or "history" in place.interest_tags
        for place in places
    )
    assert any(place.name == "Colosseum" for place in places)


def test_search_places_matches_categories_case_insensitively():
    places = search_places("rome", ["MUSEUMS"])

    assert places
    assert all(place.category == "museums" for place in places)


def test_search_places_without_interests_returns_city_dataset():
    places = search_places("Rome", [])

    assert len(places) == 35
    assert all(place.city == "Rome" for place in places)


def test_search_places_returns_empty_for_unknown_city_or_interest():
    assert search_places("Paris", ["history"]) == []
    assert search_places("Rome", ["space travel"]) == []


def test_get_place_details_returns_matching_provider_record():
    place = get_place_details(Provider.OPENSTREETMAP, "relation/1834818")

    assert place is not None
    assert place.name == "Colosseum"
    assert place.provider == Provider.OPENSTREETMAP


def test_get_place_details_returns_none_for_unknown_provider_or_id():
    assert get_place_details("unknown-provider", "relation/1834818") is None
    assert get_place_details("openstreetmap", "does-not-exist") is None
