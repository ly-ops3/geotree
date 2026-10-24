# Geo Registry

**Self-hosted place-name registry service** (Flask + PostgreSQL): a single
`geo_places` tree combining the GeoNames global gazetteer, a China administrative
division dataset down to township/street level, and macro-region mappings —
exposed through one unified `place_id`, hierarchical browsing, bilingual
(EN/ZH) search, and free-text location resolution.

The goal: multiple applications share one geographic dataset and one
`place_id` semantic. Business databases store only `location_place_id`;
display and editing go through this service.

[中文文档](README.md)

## Highlights

- 873k+ places: GeoNames worldwide + China divisions down to street/town level
- Bilingual out of the box: 150k Chinese names, full English + local names
- `resolve_legacy_location_text`: parses dirty free-text locations
  ("Hubei Wuhan", "Inner Mongolia Tongliao") into a `place_id` + scope
- Read-only REST API with `place_id` validation for write paths
- Seed data ships in the repo — clone, restore, run

## Quick Start (Docker, recommended)

```bash
docker compose up --build
# PostgreSQL + one-shot seed loader + API at http://127.0.0.1:5010
```

## Quick Start (Bare Metal)

```bash
createdb -U postgres geo_registry
pip install -r requirements.txt
cp config.example.json config.json      # or use env vars below

psql -U postgres -d geo_registry -f database/seed/ok_zh_level4.pgdump.sql
pg_restore -U postgres -d geo_registry --clean --if-exists database/seed/geo_places.dump

python app.py   # http://127.0.0.1:5010 → GET /health {"geo_ready": true}
```

## Configuration

Priority: environment variables > `config.json` > built-in defaults.

| Key | Description |
|-----|-------------|
| `database.*` | PostgreSQL connection (host/port/name/user/password/pool_size) |
| `api.*` | listen host/port, debug, threaded |
| `bind_mode` | `local` = 127.0.0.1 only; otherwise binds `api.host` |
| `data_dir` | GeoNames/ZH-name source dir; empty = `./database/geo` |
| `cors_origins` | allowed CORS origins |

Env overrides: `GEO_DB_DSN` (`postgresql://user:pass@host:port/name`) or
individual `GEO_DB_HOST` / `GEO_DB_PORT` / `GEO_DB_NAME` / `GEO_DB_USER` /
`GEO_DB_PASSWORD`, plus `GEO_DATA_DIR` and `BIND_MODE`.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /health` | health check (incl. `geo_ready`) |
| `GET /api/geo/regions` | children of a node (`scope` / `parent_id`) |
| `GET /api/geo/regions/search` | search (legacy-compatible path) |
| `GET /api/places/search` | search by EN/ZH name |
| `GET /api/geo/regions/{id}/path` | breadcrumb |
| `GET /api/places/{id}` | single-place metadata |
| `GET /api/places/{id}/path` | breadcrumb (recommended) |
| `POST /api/places/validate` | validate `place_id` before writes |

## Data & Licensing

The repo ships third-party geographic data — please respect the source licenses:

| Data | Source | License |
|------|--------|---------|
| GeoNames gazetteer / alternateNames | [geonames.org](https://www.geonames.org) | [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) (attribution required) |
| CLDR subdivision zh names | [unicode-org/cldr-json](https://github.com/unicode-org/cldr-json) | Unicode License |
| ok_zh China divisions (to township) | open-source 4-level division dataset on GitHub | public statistical data |

Code: [MIT](LICENSE).

## Repository Layout

```
app.py                  API entrypoint (default :5010)
app/config.py           config loader (config.json + env vars)
app/db.py               PG connection + schema bootstrap
app/geo/                region queries, ZH-name resolution, macro regions,
                        free-text location resolution
app/handlers/geo.py     HTTP routes
scripts/geo/            import scripts (GeoNames, ok_zh)
database/               schema + geo source cache + seed dumps
Dockerfile / docker-compose.yml   one-command deployment
```
