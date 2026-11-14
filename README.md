# Gate5-Travel-Agent

## Prototype city

**Rome** (one city, trips of 1–3 days in v1).

## Repository structure

```
src/
  models/       local SLM test script (Task 4)
  schemas/      shared data structures (Place, Trip, Day, Activity, golden test case)
  config.py     project settings (prototype city)
data/           place data (Task 1) and RAG sources (Task 2)
scripts/        data collection scripts
tests/          golden dataset
docs/           Milestone documents and data_structures.md
```

## Setup

```bash
pip install -r requirements.txt
```

## Shared data formats

See [`docs/data_structures.md`](docs/data_structures.md). Do not change a shared format without telling the team.