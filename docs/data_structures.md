# Gate5 Shared Data Structures

These structures are shared by the whole team. They are defined as Python (Pydantic) classes in `src/schemas/`.

**Prototype city: Rome** (set in `src/config.py`).

Do not change a shared format silently. Propose the change in a PR or in the team chat first.

| Structure | Python class | Used by | File |
|---|---|---|---|
| Place | `Place`, `PlaceDataset` | Task 1, tools, validator | `data/places.json` |
| Trip / Day / Activity | `Trip`, `Day`, `Activity` | agent (Trip State), validator | saved per session |
| Trip request | `TripRequest` | SLM output | – |
| Golden test case | `GoldenTestCase`, `GoldenDataset` | Task 3, evaluation | `tests/golden_dataset.json` |

---

## 1. Place

One real attraction or restaurant (Milestone 2, sections 1.3–1.4). A place is identified by **`provider` + `provider_id`**.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `provider` | `"opentripmap"` or `"openstreetmap"` | yes | Where the record comes from |
| `provider_id` | text | yes | ID from the provider (e.g. OpenTripMap `xid`) |
| `name` | text | yes | Place name |
| `city` | text | yes | City name |
| `category` | text | yes | e.g. `museums`, `churches`, `foods` |
| `interest_tags` | list of text | no | e.g. `["history", "art"]` |
| `indoor` | true / false / null | no | null = unknown |
| `lat`, `lon` | number | yes | Coordinates |
| `source_url` | text | yes | Link to the provider record |
| `opening_hours` | text or null | no | Raw OSM string, e.g. `"Tu-Su 09:00-19:00"` |
| `hours_status` | `"known"` / `"unknown"` | no (default `unknown`) | `unknown` → "hours not verified" |
| `est_visit_minutes` | number | no (default 60) | Estimated visit time |
| `retrieved_at` | date `YYYY-MM-DD` | yes | When the record was collected |

**Missing data:** leave it `null` (or `hours_status: "unknown"`). Never invent a value.

**Rules checked automatically:**
- `hours_status: "known"` requires a non-empty `opening_hours`.
- `(provider, provider_id)` must be unique in `places.json`, and every place's `city` must match the dataset `city`.
- `lat` must be between -90 and 90, `lon` between -180 and 180, and `est_visit_minutes` must be greater than 0.
- Unknown or misspelled field names in places, activities and golden test cases are rejected (e.g. `hours_staus`).
- `provider` must be `"opentripmap"` or `"openstreetmap"`.
- A `Trip` has 1–3 days; activity `start`/`end` must be `HH:MM` (24-hour); `test_id` must look like `GD01`.

`data/places.json` format:

```json
{
  "city": "Rome",
  "version": "v1",
  "places": [
    {
      "provider": "opentripmap",
      "provider_id": "EXAMPLE_ID_1",
      "name": "Example Museum",
      "city": "Rome",
      "category": "museums",
      "interest_tags": ["history", "art"],
      "indoor": true,
      "lat": 41.9,
      "lon": 12.48,
      "source_url": "https://opentripmap.com/en/card/EXAMPLE_ID_1",
      "opening_hours": "Tu-Su 09:00-19:00",
      "hours_status": "known",
      "est_visit_minutes": 90,
      "retrieved_at": "2026-11-13"
    }
  ]
}
```

---

## 2. Trip, Day, Activity

The itinerary the agent builds and edits (Trip State, Milestone 2 section 4).

**Trip:** `city`, `pace` (`relaxed` / `balanced` / `intensive`), `request` (a `TripRequest`, optional), `days` (list of `Day`), `history` (e.g. `["plan_created"]`).

**Day:** `day_number` (1, 2, 3), `date` (`YYYY-MM-DD` or null), `activities` (list of `Activity`, in order), `issues` (problems found by `validate_day`).

**Activity** (one stop):

| Field | Meaning |
|---|---|
| `provider`, `provider_id` | Points to a `Place` in `data/places.json` |
| `name` | Place name |
| `start`, `end` | `"HH:MM"`, 24-hour clock |
| `pinned` | `true` = the user wants to keep it; edits must not change it |
| `note` | Why it was chosen, or a warning |

**ValidationIssue:** `code` (e.g. `OVERLAP`, `HOURS_NOT_VERIFIED`), `severity` (`"error"` or `"warning"`), `activity_index`, `message`.

**TripRequest** (what the SLM extracts from the user message): `city`, `days`, `start_date`, `interests`, `pace`, `budget`. Missing values are `null`.

---

## 3. Golden test case

One evaluation case (Milestone 2, sections 2.2 and 2.4).

| Field | Meaning |
|---|---|
| `test_id` | `GD01`, `GD02`, … |
| `category` | `itinerary_generation`, `schedule_realism`, `itinerary_modification`, `missing_information`, `rag_advice` |
| `user_request` | The message sent to the chatbot |
| `context.existing_trip` | Original itinerary (a `Trip`), for modification tests |
| `context.places` | Places the test uses (`provider`, `provider_id`, `name`); must exist in `data/places.json` |
| `context.notes` | Extra info, e.g. dates or known hours |
| `expected_behavior` | What the chatbot should do |
| `checks` | Automatic checks that apply: `place_grounding`, `schedule_validity`, `opening_hours`, `modification_correctness`, `information_reliability`, `rag_grounding` |
| `validation_criteria` | Pass conditions in plain words |

`tests/golden_dataset.json` format:

```json
{
  "city": "Rome",
  "place_dataset_version": "v1",
  "cases": [
    {
      "test_id": "GD08",
      "category": "missing_information",
      "user_request": "Can you plan a trip for me?",
      "context": {},
      "expected_behavior": "Ask for the destination and trip duration before generating an itinerary.",
      "checks": ["information_reliability"],
      "validation_criteria": ["No itinerary is generated", "The answer asks for the city and/or number of days"]
    }
  ]
}
```

---

## How to check your file

```python
import json
from src.schemas import PlaceDataset, GoldenDataset

PlaceDataset.model_validate(json.load(open("data/places.json", encoding="utf-8")))
GoldenDataset.model_validate(json.load(open("tests/golden_dataset.json", encoding="utf-8")))
```

If something is wrong, Pydantic prints which field and why.