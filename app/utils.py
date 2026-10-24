"""API 响应工具。"""

import datetime
import uuid
from zoneinfo import ZoneInfo

from flask import jsonify, request

_CST = ZoneInfo('Asia/Shanghai')


def get_now_str():
    return datetime.datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')


def wants_api_envelope():
    raw = request.args.get('envelope')
    if raw is None:
        raw = request.headers.get('X-API-Envelope')
    if raw is None and request.form:
        raw = request.form.get('envelope')
    if raw is None:
        return False
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on', 'envelope')


def api_success(data=None, message='', meta=None, status=200, legacy=None):
    if wants_api_envelope():
        envelope_data = legacy if legacy is not None else data
        payload = {'success': True, 'message': message, 'data': envelope_data}
        payload['meta'] = meta or {
            'timestamp': get_now_str(),
            'request_id': str(uuid.uuid4()),
        }
        return jsonify(payload), status
    if legacy is not None:
        return jsonify(legacy), status
    return jsonify(data), status


def api_error(message, status=400, code='ERROR', legacy=None, extra=None):
    extra = extra or {}
    if wants_api_envelope():
        payload = {
            'success': False,
            'message': message,
            'code': code,
            'data': None,
            'meta': {
                'timestamp': get_now_str(),
                'request_id': str(uuid.uuid4()),
            },
        }
        payload.update(extra)
        return jsonify(payload), status
    if legacy is None:
        legacy = {'success': False, 'msg': message}
    else:
        legacy = dict(legacy)
    legacy.update(extra)
    return jsonify(legacy), status
