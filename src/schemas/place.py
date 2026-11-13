from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Provider(str, Enum):
    OPENTRIPMAP = "opentripmap"
    OPENSTREETMAP = "openstreetmap"


class HoursStatus(str, Enum):
    KNOWN = "known"      
    UNKNOWN = "unknown"  


class Place(BaseModel):
    provider: Provider                    
    provider_id: str                      
    name: str
    city: str
    category: str                        
    interest_tags: list[str] = []         
    indoor: Optional[bool] = None        
    lat: float
    lon: float
    source_url: str                       
    opening_hours: Optional[str] = None   
    hours_status: HoursStatus = HoursStatus.UNKNOWN
    est_visit_minutes: int = 60          
    retrieved_at: date                    


class PlaceDataset(BaseModel):
    city: str
    version: str
    places: list[Place]
