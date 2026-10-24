#!/usr/bin/env python3
"""打印 geo_places 库概览（含中国 GeoNames 全量样本）。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import create_app
from app.db import get_db
from app.geo.places import get_geo_stats


def main():
    app = create_app()
    with app.app_context():
        stats = get_geo_stats(get_db())
        print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
