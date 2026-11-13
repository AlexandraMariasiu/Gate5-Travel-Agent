from enum import Enum
from typing import Optional
from pydantic import BaseModel

from .trip import Trip


class GoldenCategory(str, Enum):
    ITINERARY_GENERATION = "itinerary_generation"
    SCHEDULE_REALISM = "schedule_realism"
    ITINERARY_MODIFICATION = "itinerary_modification"
    MISSING_INFORMATION = "missing_information"
    RAG_ADVICE = "rag_advice"


class Check(str, Enum):
    PLACE_GROUNDING = "place_grounding"
    SCHEDULE_VALIDITY = "schedule_validity"
    OPENING_HOURS = "opening_hours"
    MODIFICATION_CORRECTNESS = "modification_correctness"
    INFORMATION_RELIABILITY = "information_reliability"
    RAG_GROUNDING = "rag_grounding"


class PlaceRef(BaseModel):
    provider:str
    provider_id:str
    name:Optional[str]=None

class GoldenContext(BaseModel):
    existing_trip: Optional[Trip]=None
    places: list[PlaceRef]=[]
    notes: Optional[str]= None

class GoldenTestCase(BaseModel):
    test_id: str
    category: GoldenCategory
    user_request: str
    context: GoldenContext = GoldenContext()
    expected_behavior: str
    checks: list[Check]
    validation_criteria: list[str]


class GoldenDataset(BaseModel):
    city: str
    place_dataset_version: str
    cases: list[GoldenTestCase]

