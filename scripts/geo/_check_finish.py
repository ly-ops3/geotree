import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app import create_app
from app.db import get_db

app = create_app()
with app.app_context():
    db = get_db()
    total = db.execute('SELECT COUNT(*) AS c FROM geo_places').fetchone()['c']
    print('total', total)
    print('by source', [dict(r) for r in db.execute(
        'SELECT source, COUNT(*) c FROM geo_places GROUP BY source ORDER BY source'
    ).fetchall()])
    idx = db.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename='geo_places' ORDER BY indexname"
    ).fetchall()
    print('indexes', [r['indexname'] for r in idx])
    dup = db.execute(
        '''SELECT source, source_id, COUNT(*) n FROM geo_places
           GROUP BY source, source_id HAVING COUNT(*) > 1 LIMIT 3'''
    ).fetchall()
    print('duplicates', [dict(r) for r in dup])
    l8 = db.execute('SELECT COUNT(*) c FROM geo_places WHERE level=8').fetchone()['c']
    print('level8', l8)
    s_empty = db.execute(
        """SELECT COUNT(*) c FROM geo_places
           WHERE source='geonames' AND (name_zh IS NULL OR name_zh='' OR name_zh=name_en)"""
    ).fetchone()['c']
    gn = db.execute("SELECT COUNT(*) c FROM geo_places WHERE source='geonames'").fetchone()['c']
    print('geonames missing/same zh', s_empty, '/', gn)
    good_zh = db.execute(
        """SELECT COUNT(*) AS c FROM geo_places
           WHERE source='geonames'
             AND name_zh IS NOT NULL AND name_zh <> '' AND name_zh <> name_en"""
    ).fetchone()['c']
    print('geonames good_zh (zh!=en)', good_zh)
    cjk = db.execute(
        r"""SELECT COUNT(*) AS c FROM geo_places
            WHERE source='geonames' AND name_zh ~ '[\u4e00-\u9fff]'"""
    ).fetchone()['c']
    print('geonames name_zh with CJK', cjk)
    lock = os.path.join(os.path.dirname(__file__), '..', 'database', 'geo', '.geo_import.lock')
    print('lock exists', os.path.isfile(lock))
    fk = db.execute(
        """SELECT 1 FROM pg_constraint
           WHERE conname='geo_places_parent_id_fkey' AND conrelid='geo_places'::regclass"""
    ).fetchone()
    print('parent_id FK', bool(fk))
    sync = db.execute('SHOW synchronous_commit').fetchone()
    print('synchronous_commit', list(sync.values())[0] if sync else '?')
