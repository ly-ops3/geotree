# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')
from app.database.pg import connect_pg

db = connect_pg()
for col, ddl in [('feature_class', 'ALTER TABLE geo_places ADD COLUMN feature_class CHAR(1)'),
                 ('feature_code', 'ALTER TABLE geo_places ADD COLUMN feature_code TEXT')]:
    r = db.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_schema='public' AND table_name='geo_places' AND column_name=?""",
        (col,)).fetchone()
    if r:
        print('exists', col)
    else:
        db.execute(ddl)
        print('added', col)
db.commit()
