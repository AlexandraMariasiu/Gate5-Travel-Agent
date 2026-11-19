from datetime import timedelta
from src.schemas import Activity, Day, Pace, Place, Trip, TripRequest

STOPS_PER_DAY = {
    Pace.RELAXED: 3,
    Pace.BALANCED: 4,
    Pace.INTENSIVE: 5,
}

DAY_START = 9 * 60      
DAY_END = 19 * 60       
BREAK_MINUTES = 30

# Convert minutes from midnight to HH:MM (for example 570->09:30)
def _to_hhmm(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def _score(place: Place, interests: list[str]) -> int:
    place_tags = [tag.lower() for tag in place.interest_tags]
    place_tags.append(place.category.lower())

    score = 0
    for interest in interests:
        if interest.lower() in place_tags:
            score += 1
    return score


def _rank_places(places: list[Place], request: TripRequest) -> list[Place]:
    rows = []
    for index, place in enumerate(places):
        if place.city.lower() == request.city.lower():
            score = _score(place, request.interests)
            rows.append((-score, place.name, place.provider_id, index, place))

    rows.sort()

    ranked = []
    for row in rows:
        ranked.append(row[-1])  
    return ranked


def _build_day(day_number: int, places: list[Place], request: TripRequest) -> Day:
    activities = []
    current = DAY_START
    for place in places:
        end = current + place.est_visit_minutes
        if end > DAY_END:
            break
        note = None
        if place.hours_status.value == "unknown":
            note = "hours not verified"
        activities.append(
            Activity(
                provider=place.provider,
                provider_id=place.provider_id,
                name=place.name,
                start=_to_hhmm(current),
                end=_to_hhmm(end),
                note=note,
            )
        )
        current = end + BREAK_MINUTES

    date = None
    if request.start_date:
        date = request.start_date + timedelta(days=day_number - 1)
    return Day(day_number=day_number, date=date, activities=activities)


def generate_itinerary(request: TripRequest, places:list[Place])->Trip:
    if not request.city:
        raise ValueError("Missing city: ask the user where they want to go.")

    if not request.days:
        raise ValueError("Missing number of days: ask the user how long the trip is.")

    if not 1<=request.days<=3:
        raise ValueError("Only trips of 1-3 days are supported.")

    ranked = _rank_places(places, request)
    if not ranked:
        raise ValueError(f"No places available for {request.city}.")

    per_day = STOPS_PER_DAY[request.pace]
    days = []
    for i in range(request.days):
        chunk = ranked[i * per_day:(i + 1) * per_day]
        days.append(_build_day(i + 1, chunk, request))

    return Trip(
        city=request.city,
        pace=request.pace,
        request=request,
        days=days,
        history=["plan_created"],
    )