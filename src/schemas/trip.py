import datetime as dt
from enum import Enum
from typing import Optional

from pydantic import BaseModel

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
    provider: str
    provider_id: str
    name: str
    start: str             
    end: str               
    pinned: bool = False   
    note: Optional[str] = None  


class ValidationIssue(BaseModel):
    code: str
    severity: str
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
    days:list[Day]
    history: list[str]=[]