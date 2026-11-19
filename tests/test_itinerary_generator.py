from datetime import date

import pytest

from src.planner.itinerary_generator import generate_itinerary
from src.schemas import Place, TripRequest

def make_place(pid, name, category, tags, minutes=60, city="Rome", hours="unknown"):
    return Place(
        provider="opentripmap",
        provider_id=pid,
        name=name,
        city=city,
        category=category,
        interest_tags=tags,
        lat=41.9,
        lon=12.5,
        source_url=f"https://opentripmap.com/en/card/{pid}",
        opening_hours="Tu-Su 09:00-19:00" if hours == "known" else None,
        hours_status=hours,
        est_visit_minutes=minutes,
        retrieved_at=date(2026, 11, 19),
    )


@pytest.fixture
def places():
    return [
        make_place("P1", "Colosseum", "historic", ["history"], 120, hours="known"),
        make_place("P2", "Roman Forum", "historic", ["history"], 90),
        make_place("P3", "Vatican Museums", "museums", ["art", "history"], 180),
        make_place("P4", "Trevi Fountain", "monuments", ["architecture"], 30),
        make_place("P5", "Campo de' Fiori", "foods", ["food"], 60),
        make_place("P6", "Villa Borghese", "parks", ["nature"], 90),
        make_place("X1", "Eiffel Tower", "monuments", ["architecture"], 60, city="Paris"),
    ]


def all_activities(trip):
    return [a for day in trip.days for a in day.activities]


def test_creates_requested_number_of_days(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=2), places)
    assert len(trip.days) == 2
    assert [d.day_number for d in trip.days] == [1, 2]


def test_uses_only_supplied_places(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=3), places)
    supplied = {(p.provider, p.provider_id) for p in places}
    for a in all_activities(trip):
        assert (a.provider, a.provider_id) in supplied


def test_ignores_places_from_other_cities(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=3), places)
    assert "X1" not in [a.provider_id for a in all_activities(trip)]


def test_interests_come_first(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=1, interests=["food"]), places)
    assert trip.days[0].activities[0].name == "Campo de' Fiori"


def test_no_place_is_used_twice(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=3, pace="intensive"), places)
    ids = [a.provider_id for a in all_activities(trip)]
    assert len(ids) == len(set(ids))


def test_pace_limits_stops_per_day(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=1, pace="relaxed"), places)
    assert len(trip.days[0].activities) <= 3


def test_activities_do_not_overlap(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=2), places)
    for day in trip.days:
        for prev, nxt in zip(day.activities, day.activities[1:]):
            assert prev.end <= nxt.start


def test_unknown_hours_are_marked(places):
    trip = generate_itinerary(TripRequest(city="Rome", days=3), places)
    for a in all_activities(trip):
        if a.provider_id == "P1":
            assert a.note is None
        else:
            assert a.note == "hours not verified"


def test_dates_follow_start_date(places):
    req = TripRequest(city="Rome", days=2, start_date=date(2026, 12, 1))
    trip = generate_itinerary(req, places)
    assert [d.date for d in trip.days] == [date(2026, 12, 1), date(2026, 12, 2)]


def test_same_input_gives_same_output(places):
    req = TripRequest(city="Rome", days=2, interests=["history"])
    assert generate_itinerary(req, places) == generate_itinerary(req, places)


@pytest.mark.parametrize("req", [
    TripRequest(days=2),
    TripRequest(city="Rome"),
    TripRequest(city="Rome", days=5),
    TripRequest(city="Milan", days=1),
])
def test_invalid_requests_raise_clear_errors(req, places):
    with pytest.raises(ValueError):
        generate_itinerary(req, places)