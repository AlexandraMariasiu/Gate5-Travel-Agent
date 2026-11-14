from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Provider(str, Enum):
    OPENTRIPMAP = "opentripmap"
    OPENSTREETMAP = "openstreetmap"


class HoursStatus(str, Enum):
    KNOWN = "known"      
    UNKNOWN = "unknown"  


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider
    provider_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    city: str
    category: str
    interest_tags: list[str] = []
    indoor: Optional[bool] = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    source_url: str
    opening_hours: Optional[str] = None
    hours_status: HoursStatus = HoursStatus.UNKNOWN
    est_visit_minutes: int = Field(default=60, gt=0)
    retrieved_at: date

    @model_validator(mode="after")
    def check_hours(self):
        if self.hours_status == HoursStatus.KNOWN and not self.opening_hours:
            raise ValueError("hours_status is 'known' but opening_hours is empty")
        return self                  


class PlaceDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str
    version: str
    places: list[Place]

    @model_validator(mode="after")
    def check_places(self):
        seen = set()
        for p in self.places:
            key = (p.provider, p.provider_id)
            if key in seen:
                raise ValueError(f"duplicate place {key}")
            seen.add(key)
            if p.city != self.city:
                raise ValueError(f"place {p.provider_id} has city {p.city}, dataset city is {self.city}")
        return self