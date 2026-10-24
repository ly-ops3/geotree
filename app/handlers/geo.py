"""地理区划只读 API（多应用共用）。"""

from flask import Blueprint, request

from app.db import get_db
from app.geo.places import (
    SCOPE_ABROAD,
    SCOPE_CN,
    SCOPE_CN_GN,
    geo_tables_ready,
    get_breadcrumb,
    get_children,
    get_geo_stats,
    get_place,
    place_scope,
    search_places,
    validate_place_for_profile,
)
from app.utils import api_error, api_success
from app.geo.search_query import search, SearchError
from app.geo.places import place_display_name

geo_bp = Blueprint('geo', __name__, url_prefix='/api/geo')
places_bp = Blueprint('places', __name__, url_prefix='/api/places')

_VALID_SCOPES = frozenset({SCOPE_CN, SCOPE_ABROAD, SCOPE_CN_GN, ''})


def _geo_not_ready():
    return api_error('地理数据尚未导入，请运行 scripts/geo/import_all.py', status=503, code='ERR_GEO_NOT_READY')


def _parse_search_request():
    q = request.args.get('q', '')
    scope = (request.args.get('scope') or '').strip().lower() or None
    if scope and scope not in (SCOPE_CN, SCOPE_ABROAD, SCOPE_CN_GN):
        return None, api_error('scope 须为 cn、abroad 或 cn_gn', code='ERR_INVALID_PARAM')
    try:
        limit = min(int(request.args.get('limit', 20)), 50)
    except (TypeError, ValueError):
        limit = 20
    return (q, scope, limit), None


def _places_search_response(db):
    try:
        result = search(db, request.args, place_display_name)
    except SearchError as exc:
        return api_error(str(exc), status=400, code='ERR_GEO_QUERY')
    return api_success(result, legacy=result)


@geo_bp.route('/stats', methods=['GET'])
def geo_stats():
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()
    data = get_geo_stats(db)
    return api_success(data, legacy=data)


@geo_bp.route('/regions', methods=['GET'])
def list_regions():
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()

    scope = (request.args.get('scope') or '').strip().lower()
    if scope not in _VALID_SCOPES:
        return api_error('scope 须为 cn、abroad 或 cn_gn', code='ERR_INVALID_PARAM')

    parent_raw = request.args.get('parent_id')
    parent_id = None
    if parent_raw not in (None, ''):
        try:
            parent_id = int(parent_raw)
        except (TypeError, ValueError):
            return api_error('parent_id 非法', code='ERR_INVALID_PARAM')
        scope = None
    elif not scope:
        return api_error('根节点须指定 scope=cn、abroad 或 cn_gn', code='ERR_INVALID_PARAM')

    items = get_children(db, parent_id=parent_id, scope=scope or None)
    return api_success({'items': items}, legacy={'items': items})


@geo_bp.route('/regions/<int:place_id>/path', methods=['GET'])
def region_path(place_id):
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()
    path = get_breadcrumb(db, place_id)
    if not path:
        return api_error('地区不存在', status=404, code='ERR_NOT_FOUND')
    return api_success({'path': path}, legacy={'path': path})


@geo_bp.route('/regions/search', methods=['GET'])
def region_search():
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()
    return _places_search_response(db)


@places_bp.route('/search', methods=['GET'])
def places_search():
    """按中英文名称搜索 geo_places（资料栏地名输入联想）。"""
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()
    return _places_search_response(db)


@places_bp.route('/<int:place_id>', methods=['GET'])
def place_detail(place_id):
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()
    item = get_place(db, place_id)
    if not item:
        return api_error('地区不存在', status=404, code='ERR_NOT_FOUND')
    return api_success({'place': item}, legacy={'place': item})


@places_bp.route('/<int:place_id>/path', methods=['GET'])
def place_path(place_id):
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()
    path = get_breadcrumb(db, place_id)
    if not path:
        return api_error('地区不存在', status=404, code='ERR_NOT_FOUND')
    return api_success({'path': path}, legacy={'path': path})


@places_bp.route('/validate', methods=['POST'])
def place_validate():
    db = get_db()
    if not geo_tables_ready(db):
        return _geo_not_ready()
    data = request.json or {}
    place_id = data.get('place_id')
    if place_id is None:
        return api_error('缺少 place_id', code='ERR_INVALID_PARAM')
    try:
        place_id = int(place_id)
    except (TypeError, ValueError):
        return api_error('place_id 非法', code='ERR_INVALID_PARAM')
    try:
        row = validate_place_for_profile(db, place_id)
    except ValueError as exc:
        return api_error(str(exc), status=400, code='ERR_INVALID_PARAM')
    item = get_place(db, place_id)
    scope = place_scope(row)
    payload = {
        'ok': True,
        'place_id': place_id,
        'scope': scope,
        'display_name': item.get('display_name') if item else None,
        'place': item,
    }
    return api_success(payload, legacy=payload)
