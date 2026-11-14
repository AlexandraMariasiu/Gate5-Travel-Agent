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

## Collecting RAG sources

Collect clean, traceable Markdown travel documents for the prototype city (`Rome`) into `data/rag_sources/`:

```bash
# Collect all sources (skips existing files by default)
python scripts/collect_guides.py --city Rome --sources all

# Preview without writing files
python scripts/collect_guides.py --sources all --dry-run

# Refresh specific sources and overwrite existing Markdown files
python scripts/collect_guides.py --sources wikivoyage blogs reddit --overwrite
```

- **Sources**:
  - `wikivoyage` (`official_guide`) — Rome main guide and district pages via the MediaWiki API
  - `blogs` (`travel_blog`) — curated Rome neighborhood, food, transit, and rainy-day articles via `trafilatura` / `BeautifulSoup`
  - `reddit` (`community_forum`) — `r/ItalyTravel` and `r/rome` discussions (uses official Reddit OAuth when `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are set, otherwise falls back to the public Arctic Shift archive API)
- **Outputs**: Markdown files with YAML frontmatter (`document_id`, `title`, `city`, `topic`, `source_type`, `source_url`, `updated_at`, `retrieved_at`, `license`) grouped under `data/rag_sources/<source_type>/`, indexed in `data/rag_sources/manifest.json`.
- **Options**: see `python scripts/collect_guides.py --help` (`--city`, `--output-dir`, `--sources`, `--min-reddit-score`, `--overwrite`, `--dry-run`).

## Shared data formats

See [`docs/data_structures.md`](docs/data_structures.md). Do not change a shared format without telling the team.