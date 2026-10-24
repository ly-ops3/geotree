"""Run parser tests and optional read-only PostgreSQL smoke queries."""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('search_query', ROOT / 'app/geo/search_query.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class QueryTests(unittest.TestCase):
    def test_quotes_and_filters(self):
        q = module.parse_query('country = "United States" deep=1 "New York"')
        self.assertEqual(q, dict(country='united states', deep=1, exact='new york', words=[]))
        self.assertEqual(module.parse_query('country=美国 New York')['words'], ['new', 'york'])
        self.assertEqual(module.parse_query('"松江新城"')['exact'], '松江新城')

    def test_invalid_inputs(self):
        for q in ['deep=6', 'deep=-2', 'country=', 'deep=1 deep=2', 'x=US', '"abc', '""',
                  'country=US;deep=1', '"a" "b"', 'country= deep=1', '"a\\q"', 'a' * 257]:
            with self.subTest(q=q), self.assertRaises(module.SearchError):
                module.parse_query(q)

    def test_depth(self):
        self.assertEqual(module.depth(dict(source='ok_zh', deep_legacy=3)), 4)
        self.assertEqual(module.depth(dict(source='geonames', level=5)), 4)
        self.assertEqual(module.depth(dict(source='macro', level=15)), 0)
        self.assertEqual(module.depth(dict(source='geonames', level=1)), -1)
        self.assertIsNone(module.depth(dict(source='geonames', level=7)))

    def test_literal_wildcards(self):
        self.assertEqual(module.pattern('a%b_c!'), 'a!%b!_c!!')

    def test_backend_parity(self):
        self.assertEqual((ROOT / 'app/geo/search_query.py').read_bytes(),
                         (ROOT.parent / 'backend/app/geo/search_query.py').read_bytes())


def integration_tests():
    """Isolated connection-local fixture, never writes the real geographic table."""
    sys.path.insert(0, str(ROOT))
    from app.database.pg import connect_pg
    from app.geo.places import place_display_name
    db = connect_pg()
    try:
        db.execute('CREATE TEMP TABLE geo_places (LIKE public.geo_places INCLUDING DEFAULTS) ON COMMIT DROP')
        rows = [
            (1,None,1,'geonames','CN','中国','China',None,None,True),
            (2,1,15,'macro','CN','华东地区','East China',None,None,False),
            (3,2,2,'ok_zh','CN','上海市','上海市','shang hai',0,True),
            (4,3,3,'ok_zh','CN','上海城区','上海城区','shang hai',1,True),
            (5,4,4,'ok_zh','CN','浦东新区','浦东新区','pu dong',2,True),
            (6,5,5,'ok_zh','CN','张江镇','张江镇','zhang jiang',3,True),
            (7,None,1,'geonames','US','美国','United States',None,None,True),
            (8,7,2,'geonames','US','纽约州','New York',None,None,True),
            (9,7,2,'geonames','US','其他','New York City',None,None,True),
            (10,7,7,'geonames','US','聚落','New York',None,None,True),
            (11,7,2,'geonames','US','百分号','A%_Town',None,None,True),
        ]
        db.executemany('''INSERT INTO geo_places
          (id,parent_id,level,source,iso_country,name_zh,name_en,pinyin,deep_legacy,is_selectable,source_id)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)''', [r+(str(r[0]),) for r in rows])
        def run(q, **kwargs):
            return module.search(db, dict(q=q, **kwargs), place_display_name)
        assert [x['id'] for x in run('country=中国 deep=4 张江')['items']] == [6]
        assert [x['id'] for x in run('上海 张江')['items']] == [6]
        assert [x['id'] for x in run('浦东新区张江镇')['items']] == [6]
        assert not run('浦东新区张江镇未知地址')['items']
        assert [x['id'] for x in run('zhang jiang')['items']] == [6]
        assert {x['id'] for x in run('country="United States" "new york"')['items']} == {8,10}
        assert [x['id'] for x in run('country=US deep=1 "New York"')['items']] == [8]
        assert [x['id'] for x in run('country=US deep=1 "New York"', country='美国')['items']] == [8]
        assert [x['id'] for x in run('A%_')['items']] == [11]
        assert not run('deep=0')['items']
        assert run('deep=0', selectable_only='false')['items'][0]['selectable'] is False
        assert not run('country=US', ancestor_id=1)['items']
        assert {x['id'] for x in run('', ancestor_id=2)['items']} == {3,4,5,6}
        assert [x['id'] for x in run('张江', ancestor_id=2)['items']] == [6]
        assert not run('', ancestor_id=999)['items']
        assert [x['id'] for x in run('', ancestor_id=6)['items']] == [6]
        result = run('country=US', limit=2)
        second = run('country=US', limit=2, cursor=result['next_cursor'])
        assert not ({x['id'] for x in result['items']} & {x['id'] for x in second['items']})
        for q, kwargs in [('deep=8', {}), ('country=US', {'scope':'cn'}), ('country=United States', {}),
                          ('country=中国', {'cursor':result['next_cursor'], 'limit':2}), ('张江', {'limit':-1})]:
            try:
                run(q, **kwargs)
                raise AssertionError('Expected query error: ' + q)
            except module.SearchError:
                pass
        print('PASS: isolated PostgreSQL search, names, filters, scopes, wildcard escaping, navigation, pagination')
    finally:
        db.rollback()
        db.close()


if __name__ == '__main__':
    if '--http' in sys.argv:
        import requests
        base = 'http://localhost:5002/api/geo'
        root_response = requests.get(base + '/regions', params={'scope':'cn'}, timeout=20)
        root_response.raise_for_status()
        body = root_response.json()
        roots = body.get('data', body)['items']
        assert any(r['level'] == 1 and r['iso_country'] == 'CN' for r in roots)
        for q, scope, expected in [('country=中国 deep=4 张江','cn',200),
                                    ('country="United States" "New York"','abroad',200),
                                    ('deep=9','cn',400), ('country=United States','abroad',400),
                                    ('country=US','cn',400)]:
            response = requests.get(base + '/regions/search', params={'q':q, 'scope':scope}, timeout=20)
            assert response.status_code == expected, (q,response.status_code,response.text[:200])
            data = response.json()
            if expected == 200:
                assert data.get('data',data)['items'], q
            print('HTTP', expected, q)
        print('PASS: real frontend proxy, backend proxy, registry search and country root')
    elif '--integration' in sys.argv:
        integration_tests()
    elif '--live' not in sys.argv:
        unittest.main()
    else:
        sys.path.insert(0, str(ROOT))
        from app.database.pg import connect_pg
        from app.geo.places import place_display_name
        import time
        db = connect_pg()
        try:
            db.execute('SET default_transaction_read_only = on')
            db.execute('SET statement_timeout = 15000')
            for q in ['country=US deep=0', 'country=美国 deep=1', 'country="United States" "New York"',
                      'country=中国 deep=4 张江', '上海 张江', 'zhang jiang', '"松江新城"']:
                start = time.monotonic()
                result = module.search(db, dict(q=q, limit=5, selectable_only='false'), place_display_name)
                print(q, round(time.monotonic()-start, 3),
                      [(x['display_name'], x['admin_depth']) for x in result['items']], flush=True)
                if result['next_cursor']:
                    second = module.search(db, dict(q=q, limit=5, selectable_only='false', cursor=result['next_cursor']), place_display_name)
                    assert not ({x['id'] for x in result['items']} & {x['id'] for x in second['items']})
            print('Live read-only queries passed')
        finally:
            db.rollback()
            db.close()
