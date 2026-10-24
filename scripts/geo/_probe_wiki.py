#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app import create_app
from app.db import get_db
from app.geo.geo_fixup_profiles import get_profile
from app.geo.geonames_zh_fixup import (
    _wiki_title_variants,
    check_wikipedia_langlinks,
    fetch_wikipedia_zh_batch,
    fetch_wikidata_zh_for_country,
)

app = create_app()
with app.app_context():
    db = get_db()
    for api in (
        'https://en.wikipedia.org/w/api.php',
        'https://id.wikipedia.org/w/api.php',
    ):
        ok, code, hint = check_wikipedia_langlinks(api)
        print(f'{api.split("/")[2]} langlinks: ok={ok} http={code} {hint}')

    for iso in ('ID', 'IN', 'IE'):
        profile = get_profile(iso)
        print(f'\n=== {iso} wiki={profile.wiki_api.split("/")[2]} ===')
        rows = db.execute(
            '''SELECT source_id, name_en, admin1_code FROM geo_places
               WHERE iso_country=? AND source='geonames' AND level=3
                 AND (name_zh IS NULL OR TRIM(name_zh)='') LIMIT 3''',
            (iso,),
        ).fetchall()
        for row in rows:
            a1 = db.execute(
                'SELECT name_en FROM geo_places WHERE iso_country=? AND level=2 AND admin1_code=? LIMIT 1',
                (iso, row['admin1_code']),
            ).fetchone()
            pe = a1['name_en'] if a1 else ''
            variants = _wiki_title_variants(profile, row['name_en'], pe)
            zh = None
            hit_title = None
            for title in variants:
                m = fetch_wikipedia_zh_batch([title], wiki_api=profile.wiki_api)
                if m.get(title):
                    zh = m[title]
                    hit_title = title
                    break
            print(f"  {row['name_en']!r}")
            print(f'    variants={variants!r}')
            print(f'    hit={hit_title!r} -> {zh!r}')

    wd = fetch_wikidata_zh_for_country('Q252')
    miss = db.execute(
        '''SELECT source_id FROM geo_places WHERE iso_country='ID' AND level IN (3,4)
           AND (name_zh IS NULL OR TRIM(name_zh)='')'''
    ).fetchall()
    overlap = sum(1 for r in miss if str(r['source_id']) in wd)
    print(f'\nID missing {len(miss)} wikidata overlap {overlap} (dict {len(wd)})')
