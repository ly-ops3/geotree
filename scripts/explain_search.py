"""Read-only EXPLAIN ANALYZE for the exact SQL emitted by geographic search."""
import json
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.database.pg import connect_pg
from app.geo.search_query import search
from app.geo.places import place_display_name


class EmptyCursor:
    def fetchall(self):
        return []


class ExplainConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=None):
        if sql.startswith('SELECT p.*, ('):
            result = self.db.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, params).fetchone()[0][0]
            def compact(node):
                keys = ('Node Type', 'Relation Name', 'Index Name', 'Actual Total Time', 'Actual Rows',
                        'Actual Loops', 'Rows Removed by Filter', 'Shared Hit Blocks', 'Shared Read Blocks')
                return {**{key: node[key] for key in keys if key in node},
                        'Plans': [compact(child) for child in node.get('Plans', [])]}
            print(json.dumps({'execution_ms': result['Execution Time'], 'plan': compact(result['Plan'])}, ensure_ascii=False, indent=2))
            return EmptyCursor()
        return self.db.execute(sql, params)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query', nargs='?', default='zhang jiang')
    parser.add_argument('--ancestor-id', type=int)
    parser.add_argument('--scope', choices=['cn', 'abroad', 'cn_gn'])
    args = parser.parse_args()
    db = connect_pg()
    try:
        db.execute('SET default_transaction_read_only = on')
        db.execute('SET statement_timeout = 30000')
        search(ExplainConnection(db), {'q': args.query, 'limit': 15,
                                     'ancestor_id': args.ancestor_id, 'scope': args.scope}, place_display_name)
    finally:
        db.rollback()
        db.close()
