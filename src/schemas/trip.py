import datetime as dt
from enum import Enum
from typing import Literal,Optional

from pydantic import BaseModel, ConfigDict, Field

from .place import Provider

TIME = r"^([01]\d|2[0-3]):[0-5]\d$"

class Pace(str,Enum):
    RELAXED = "relaxed"
    BALANCED = "balanced"
    INTENSIVE = "intensive"

 
class TripRequest(BaseModel):
    city: Optional[str] = None
    days: Optional[int] = None
    start_date: Optional[dt.date] = None
    interests: list[str] = []
    pace: Pace = Pace.BALANCED
    budget: Optional[str] = None 


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider
    provider_id: str
    name: str
    start: str = Field(pattern=TIME)
    end: str = Field(pattern=TIME)              
    pinned: bool = False   
    note: Optional[str] = None  


class ValidationIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    activity_index: Optional[int]=None
    message: str

class Day(BaseModel):
    day_number: int
    date: Optional[dt.date]=None
    activities: list[Activity] = []
    issues: list[ValidationIssue] = []


class Trip(BaseModel):
    city:str
    pace:Pace=Pace.BALANCED
    request: Optional[TripRequest]=None
    days:list[Day] = Field(min_length=1, max_length=3)
    history: list[str]=[]