#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用通名规范层。--dry-run 只统计不写。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database.pg import connect_pg
from app.geo.admin_terms import apply_admin_terms, KNOWN_TERMS


def main():
    dry = '--dry-run' in sys.argv
    db = connect_pg()
    res = apply_admin_terms(db, dry_run=dry)
    print(res)
    pattern = '|'.join(KNOWN_TERMS)
    out = io.open('scripts/geo/_terms_sample.txt', 'w', encoding='utf-8')
    for r in db.execute(
        "SELECT iso_country, level, name_en, name_zh FROM geo_places "
        "WHERE source='geonames' AND level BETWEEN 2 AND 5 "
        f"AND name_zh ~ '({pattern})$' ORDER BY RANDOM() LIMIT 25"
    ).fetchall():
        out.write(f"{r['iso_country']} L{r['level']} {r['name_en']} -> {r['name_zh']}\n")
    out.close()
    print('sample -> scripts/geo/_terms_sample.txt')


if __name__ == '__main__':
    main()
