# Backend

FastAPI backend — serves flight scenarios, sector data, arrival-frequency DB,
and the reroute recommendation engine.

Requires **Python 3.8+**.

## First-time setup

```bash
# Mac / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
.\venv\Scripts\activate

pip install -r requirements.txt
```

## Run the dev server

```bash
uvicorn main:app --reload
```

API at `http://localhost:8000` · Swagger docs at `/docs`.

## Database (`arrivals.db`)

`arrivals.db` is committed — it contains pre-seeded arrival/departure frequency
for 6 days (5 ASI dataset days + Christmas 2025 from BTS) and the VMC AAR
capacity table. No seeding step needed after a fresh clone.

To re-seed a day from the ASI dataset (e.g. after changing the data bundle):

```bash
curl -X POST http://localhost:8000/refresh -H 'Content-Type: application/json' \
     -d '{"day": "2025-08-21"}'
```

To re-seed Christmas 2025 from the BTS On-Time Performance ZIP:

```bash
python seed_bts.py /path/to/bts_2025_12.zip
```

(ZIP available free from BTS Transtats — search "On-Time Performance 2025 12".)
