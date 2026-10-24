"""Structured geographic search. Mirrored in the backend fallback; parity is tested."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata


class SearchError(ValueError):
    pass


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value)).split()).lower()


def parse_query(text):
    if len(text or '') > 256:
        raise SearchError('查询最长 256 个字符')
    text = unicodedata.normalize('NFKC', text or '')
    tokens = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] == ';':
            raise SearchError('条件请用空格分隔，不支持分号')
        if text[i] == '=':
            tokens.append(('=', '='))
            i += 1
            continue
        if text[i] == '"':
            i += 1
            value = ''
            while i < len(text) and text[i] != '"':
                if text[i] == '\\':
                    i += 1
                    if i >= len(text) or text[i] not in ('"', '\\'):
                        raise SearchError('引号内仅支持转义双引号和反斜杠')
                value += text[i]
                i += 1
            if i == len(text):
                raise SearchError('双引号未闭合')
            i += 1
            if not value.strip():
                raise SearchError('引号内不能为空')
            if i < len(text) and not text[i].isspace() and text[i] != '=':
                raise SearchError('引号后请使用空格分隔')
            tokens.append(('quoted', value))
            continue
        start = i
        while i < len(text) and not text[i].isspace() and text[i] not in '=;"':
            i += 1
        tokens.append(('word', text[start:i]))
    if len(tokens) > 48:
        raise SearchError('查询条件过多')
    result = {'words': [], 'exact': None, 'country': None, 'deep': None}
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if i + 1 < len(tokens) and tokens[i + 1][0] == '=':
            key = value.lower()
            if kind != 'word' or key not in ('country', 'deep'):
                raise SearchError('仅支持 country= 和 deep=')
            if i + 2 >= len(tokens) or tokens[i + 2][0] == '=':
                raise SearchError(key + ' 缺少值')
            val = normalize(tokens[i + 2][1])
            if i + 3 < len(tokens) and tokens[i + 3][0] == '=':
                raise SearchError(key + ' 缺少有效值')
            if key == 'deep':
                if not re.fullmatch(r'-?\d+', val) or not -1 <= int(val) <= 5:
                    raise SearchError('deep 须为 -1 至 5 的整数')
                val = int(val)
            if result[key] is not None and result[key] != val:
                raise SearchError(key + ' 条件冲突')
            result[key] = val
            i += 3
        elif kind == '=':
            raise SearchError('等号前缺少字段名')
        else:
            val = normalize(value)
            if kind == 'quoted':
                if result['exact'] is not None and result['exact'] != val:
                    raise SearchError('多个精确名称冲突')
                result['exact'] = val
            else:
                result['words'].append(val)
            i += 1
    if len(result['words']) > 12:
        raise SearchError('关键词最多 12 个')
    return result


DEPTH_SQL = """CASE
 WHEN p.source='macro' AND p.level=15 THEN 0
 WHEN p.source='ok_zh' AND p.deep_legacy BETWEEN 0 AND 4 THEN p.deep_legacy+1
 WHEN p.source='geonames' AND p.level=1 THEN -1
 WHEN p.source='geonames' AND p.level BETWEEN 2 AND 6 THEN p.level-1
 ELSE NULL END"""


def depth(row):
    if row.get('source') == 'macro' and row.get('level') == 15:
        return 0
    if row.get('source') == 'ok_zh' and row.get('deep_legacy') in range(5):
        return row['deep_legacy'] + 1
    if row.get('source') == 'geonames' and row.get('level') in range(1, 7):
        return -1 if row['level'] == 1 else row['level'] - 1
    return None


def name_expression(alias, column):
    # Normalize only populated names, but return a non-NULL predicate operand:
    # NULL OR/AND can otherwise trigger ancestor traversal for nonmatches.
    return f"COALESCE(lower(regexp_replace(btrim(normalize({alias}.{column}, NFKC)), '\\s+', ' ', 'g')), '')"


def names(alias, op):
    return '(' + ' OR '.join(name_expression(alias, col) + ' ' + op
                             for col in ('name_zh', 'name_en', 'name_local')) + ')'


def pattern(value):
    return value.replace('!', '!!').replace('%', '!%').replace('_', '!_')


def country_code(db, value):
    code = value.upper()
    if re.fullmatch('[A-Z]{2}', code):
        rows = db.execute("SELECT DISTINCT iso_country FROM geo_places WHERE iso_country=? LIMIT 2", (code,)).fetchall()
    else:
        rows = db.execute("SELECT DISTINCT iso_country FROM geo_places p WHERE source='geonames' AND level=1 AND " +
                          names('p', '= ?'), (value,) * 3).fetchall()
    codes = {r['iso_country'].strip() for r in rows if r['iso_country']}
    if len(codes) != 1:
        raise SearchError('国家名称无法识别或存在歧义；含空格的名称请用双引号，例如 country="United States"')
    return codes.pop()


def bounded_int(value, label, low, high):
    try:
        if not re.fullmatch(r'-?\d+', str(value)):
            raise ValueError()
        n = int(value)
        if low <= n <= high:
            return n
    except (ValueError, TypeError):
        pass
    raise SearchError(f'{label} 须为 {low} 至 {high} 的整数')


def search(db, args, display_name):
    query = parse_query(args.get('q', ''))
    for key in ('country', 'deep'):
        if args.get(key) not in (None, ''):
            val = normalize(args[key]) if key == 'country' else bounded_int(args[key], key, -1, 5)
            if query[key] is not None and query[key] != val and key != 'country':
                raise SearchError(key + ' 控件与语法条件冲突')
            if query[key] is None:
                query[key] = val
    scope = args.get('scope') or None
    if scope not in (None, 'cn', 'abroad', 'cn_gn'):
        raise SearchError('scope 非法')
    limit = bounded_int(args.get('limit', 20), 'limit', 1, 50)
    selectable = str(args.get('selectable_only', 'true')).lower()
    if selectable not in ('true', 'false'):
        raise SearchError('selectable_only 须为 true 或 false')
    code = country_code(db, query['country']) if query['country'] else None
    if args.get('country') and country_code(db, normalize(args['country'])) != code:
        raise SearchError('country 控件与语法条件冲突')
    if code and ((scope in ('cn', 'cn_gn') and code not in ('CN', 'HK', 'MO', 'TW')) or
                 (scope == 'abroad' and code in ('CN', 'HK', 'MO', 'TW'))):
        raise SearchError('country 与当前地区范围冲突，请切换范围')
    ancestor = bounded_int(args['ancestor_id'], 'ancestor_id', 1, 2**63-1) if args.get('ancestor_id') else None
    signature = hashlib.sha256(json.dumps([query, scope, selectable, ancestor, limit], sort_keys=True).encode()).hexdigest()[:20]
    offset = 0
    if args.get('cursor'):
        try:
            if len(args['cursor']) > 512:
                raise ValueError()
            cursor = json.loads(base64.urlsafe_b64decode(args['cursor']))
            if cursor['key'] != signature:
                raise ValueError()
            offset = bounded_int(cursor['offset'], 'cursor', 0, 10000)
        except Exception:
            raise SearchError('分页游标无效或查询条件已改变')
    filters = {k: v for k, v in {'country_code': code, 'deep': query['deep'], 'ancestor_id': ancestor}.items() if v is not None}
    if not (query['words'] or query['exact'] or filters):
        return {'items': [], 'has_more': False, 'next_cursor': None, 'filters': filters}
    clauses, params = [], []
    clauses.append("(p.is_selectable=TRUE AND p.source<>'macro')" if selectable == 'true'
                   else "(p.is_selectable=TRUE OR p.source='macro')")
    if scope == 'cn':
        clauses.append("(p.source='ok_zh' OR (p.source='macro' AND p.iso_country IN ('CN','HK','MO','TW')) OR (p.level=1 AND p.iso_country IN ('CN','HK','MO','TW')))")
    elif scope == 'abroad':
        clauses.append("(p.source IN ('geonames','macro') AND p.iso_country NOT IN ('CN','HK','MO','TW'))")
    elif scope == 'cn_gn':
        clauses.append("p.source='geonames' AND p.iso_country='CN'")
    if code:
        clauses.append('p.iso_country=?')
        params.append(code)
    if query['deep'] is not None:
        clauses.append('(' + DEPTH_SQL + ')=?')
        params.append(query['deep'])

    def ancestors(condition, values):
        # Bounded, cycle-safe parent traversal. Includes target for ancestor_id filters.
        return """EXISTS (WITH RECURSIVE chain AS (
          SELECT a.*, ARRAY[a.id] AS visited FROM geo_places a WHERE a.id=p.id
          UNION ALL SELECT a.*, chain.visited || a.id FROM geo_places a
          JOIN chain ON a.id=chain.parent_id
          WHERE NOT a.id=ANY(chain.visited) AND cardinality(chain.visited)<32
        ) SELECT 1 FROM chain a WHERE """ + condition + ')', values

    if ancestor:
        # Expand the selected subtree once, not the ancestry of every place.
        clauses.append("""p.id IN (WITH RECURSIVE subtree AS (
          SELECT id, ARRAY[id] AS visited FROM geo_places WHERE id=?
          UNION ALL SELECT child.id, subtree.visited || child.id
          FROM geo_places child JOIN subtree ON child.parent_id=subtree.id
          WHERE NOT child.id=ANY(subtree.visited) AND cardinality(subtree.visited)<32
        ) SELECT id FROM subtree)""")
        params.append(ancestor)
    exact = query['exact']
    words = query['words']
    joined = ' '.join(words)
    if exact:
        clauses.append(names('p', '= ?'))
        params.extend([exact] * 3)
        for word in words:
            clause, values = ancestors("a.id<>p.id AND " + names('a', "LIKE ? ESCAPE '!'"), ['%' + pattern(word) + '%'] * 3)
            clauses.append(clause)
            params.extend(values)
    elif words:
        full_clause = names('p', "LIKE ? ESCAPE '!'")
        full_params = ['%' + pattern(joined) + '%'] * 3
        compact = ''.join(words)
        pin_clause = "replace(lower(COALESCE(p.pinyin,'')), ' ', '') LIKE ? ESCAPE '!'"
        alternatives = [full_clause, pin_clause]
        match_params = full_params + ['%' + pattern(compact) + '%']
        if len(words) > 1:
            target = names('p', "LIKE ? ESCAPE '!'")
            values = ['%' + pattern(words[-1]) + '%'] * 3
            for word in words[:-1]:
                clause, extra = ancestors("a.id<>p.id AND " + names('a', "LIKE ? ESCAPE '!'"), ['%' + pattern(word) + '%'] * 3)
                target += ' AND ' + clause
                values.extend(extra)
            alternatives.append('(' + target + ')')
            match_params.extend(values)
        if len(words) == 1 and re.fullmatch(r'[\u3400-\u9fff]{4,80}', joined):
            # Continuous Chinese address: consume complete dictionary names from
            # leaf to root; skipped ancestors are allowed, unmatched text is not.
            n = name_expression('p', 'name_zh')
            an = name_expression('a', 'name_zh')
            alternatives.append(f"""(
              {n}<>'' AND char_length(?)>char_length({n})
              AND right(?, char_length({n}))={n}
              AND EXISTS (WITH RECURSIVE address AS (
                SELECT p.id, p.parent_id, left(?, -char_length({n})) AS rest, ARRAY[p.id] AS seen
                UNION ALL
                SELECT a.id, a.parent_id,
                  CASE WHEN {an}<>'' AND right(t.rest,char_length({an}))={an}
                       THEN left(t.rest,-char_length({an})) ELSE t.rest END,
                  t.seen || a.id
                FROM address t JOIN geo_places a ON a.id=t.parent_id
                WHERE t.rest<>'' AND NOT a.id=ANY(t.seen) AND cardinality(t.seen)<32
              ) SELECT 1 FROM address WHERE rest='')
            )""")
            match_params.extend([joined] * 3)
        clauses.append('(' + ' OR '.join(alternatives) + ')')
        params.extend(match_params)
    target = exact or joined
    rank = ('CASE WHEN ' + names('p', '= ?') + ' THEN 0 WHEN ' +
            names('p', "LIKE ? ESCAPE '!'") + ' THEN 1 WHEN ' +
            names('p', "LIKE ? ESCAPE '!'") + ' THEN 2 WHEN ' +
            "replace(lower(COALESCE(p.pinyin,'')), ' ', '') LIKE ? ESCAPE '!' THEN 4 ELSE 3 END")
    rank_params = ([target] * 3 + [pattern(target) + '%'] * 3 +
                   ['%' + pattern(target) + '%'] * 3 + ['%' + pattern(''.join(words)) + '%'])
    rows = db.execute('SELECT p.*, (' + DEPTH_SQL + ') AS admin_depth, ' + rank +
                      ' AS search_rank FROM geo_places p WHERE ' + ' AND '.join(clauses) +
                      ' ORDER BY search_rank, p.population DESC NULLS LAST, p.id LIMIT ? OFFSET ?',
                      rank_params + params + [limit + 1, offset]).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    # One recursive query for all result paths, then two set-based existence checks per node.
    all_nodes = {}
    if rows:
        ids = [r['id'] for r in rows]
        marks = ','.join('?' for _ in ids)
        path_rows = db.execute(f"""WITH RECURSIVE tree AS (
          SELECT p.* FROM geo_places p WHERE id IN ({marks})
          UNION SELECT p.* FROM geo_places p JOIN tree t ON p.id=t.parent_id
        ) SELECT t.*,
          EXISTS(SELECT 1 FROM geo_places s WHERE s.parent_id=t.parent_id AND s.id<>t.id) AS has_siblings,
          EXISTS(SELECT 1 FROM geo_places c WHERE c.parent_id=t.id) AS has_children
        FROM tree t""", ids).fetchall()
        for node in path_rows:
            node = dict(node)
            node['display_name'] = display_name(node)
            node['admin_depth'] = depth(node)
            node['is_administrative'] = node['admin_depth'] not in (None, -1, 0)
            if node['parent_id'] is None:
                node['has_siblings'] = True
            all_nodes[node['id']] = node
    items = []
    for row in rows:
        node = all_nodes[row['id']]
        path, seen, cur = [], set(), node
        while cur and cur['id'] not in seen:
            seen.add(cur['id'])
            path.append(cur)
            cur = all_nodes.get(cur['parent_id'])
        path.reverse()
        item = dict(node)
        item['path'] = path
        item['path_label'] = ' · '.join(n['display_name'] for n in path[:-1] if n['source'] != 'macro' and not (n['is_administrative'] and n['has_siblings'] is False))
        item['selectable'] = bool(node['is_selectable']) and node['source'] != 'macro'
        item['match_type'] = ['name_exact', 'name_prefix', 'name_contains', 'path', 'pinyin'][row['search_rank']]
        # Path nodes are separate dictionaries; no recursive item references.
        items.append(item)
    next_cursor = base64.urlsafe_b64encode(json.dumps({'key': signature, 'offset': offset+limit}).encode()).decode() if more and offset+limit <= 10000 else None
    return {'items': items, 'has_more': more, 'next_cursor': next_cursor, 'filters': filters,
            'pagination_limit_reached': more and next_cursor is None,
            'exact': exact, 'keywords': words}
