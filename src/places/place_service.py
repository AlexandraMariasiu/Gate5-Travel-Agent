import json
from pathlib import Path
from typing import Iterable

from src.schemas import Place, PlaceDataset, Provider


ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "data" / "places.json"


def load_place_dataset(path: Path = DATASET_PATH) -> PlaceDataset:
    with path.open(encoding="utf-8") as file:
        return PlaceDataset.model_validate(json.load(file))


def search_places(city: str, interests: Iterable[str] | None = None) -> list[Place]:
    dataset = load_place_dataset()
    requested_interests = {
        interest.strip().casefold()
        for interest in (interests or [])
        if interest and interest.strip()
    }
    requested_city = city.strip().casefold()

    if requested_city != dataset.city.casefold():
        return []

    if not requested_interests:
        return list(dataset.places)

    return [
        place
        for place in dataset.places
        if (
            place.category.casefold() in requested_interests
            or any(tag.casefold() in requested_interests for tag in place.interest_tags)
        )
    ]


def get_place_details(provider: Provider | str, provider_id: str) -> Place | None:
    try:
        requested_provider = Provider(provider)
    except ValueError:
        return None

    return next(
        (
            place
            for place in load_place_dataset().places
            if place.provider == requested_provider
            and place.provider_id == provider_id
        ),
        None,
    )
