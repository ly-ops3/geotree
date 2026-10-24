#!/usr/bin/env python3
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app import create_app
from app.db import get_db

app = create_app()
with app.app_context():
    db = get_db()
    t = time.time()
    total = db.execute('SELECT COUNT(*) AS c FROM geo_places').fetchone()['c']
    print(f'total geo_places: {total} ({time.time()-t:.2f}s)', flush=True)
    t = time.time()
    bad = db.execute(
        """SELECT COUNT(*) AS c FROM geo_places g
           INNER JOIN geo_places a1
             ON a1.source='geonames' AND a1.level=2
            AND a1.iso_country=g.iso_country AND a1.admin1_code=g.admin1_code
           WHERE g.source='geonames' AND g.level>2 AND g.name_zh IS NOT NULL
             AND TRIM(g.name_zh)<>'' AND g.name_zh=a1.name_zh
             AND COALESCE(TRIM(g.name_en),'')<>g.name_zh"""
    ).fetchone()['c']
    print(f'bad admin1 fallback: {bad} ({time.time()-t:.2f}s)', flush=True)
    missing = db.execute(
        """SELECT COUNT(*) AS c FROM geo_places
           WHERE iso_country='US' AND level=3 AND source='geonames'
             AND (name_zh IS NULL OR TRIM(name_zh)='')"""
    ).fetchone()['c']
    print(f'US counties missing zh: {missing}', flush=True)
    rows = db.execute(
        """SELECT name_en, name_zh FROM geo_places
           WHERE iso_country='US' AND level=3 AND admin1_code='US.OR'
           ORDER BY name_en LIMIT 8"""
    ).fetchall()
    print('Oregon sample:', flush=True)
    for r in rows:
        print(f"  {r['name_en']} -> {r['name_zh']}", flush=True)
