"""配置管理"""

import json
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

_CONFIG_DEFAULTS = {
    'bind_mode': 'local',
    'api': {
        'port': 5010,
        'host': '0.0.0.0',
        'threaded': True,
        'debug': True,
    },
    'database': {
        'host': '127.0.0.1',
        'port': 5432,
        'name': 'geo_registry',
        'user': 'postgres',
        'password': '',
        'pool_size': 5,
    },
    # GeoNames/中文名源数据目录；空串 = <repo>/database/geo
    'data_dir': '',
    'cors_origins': [
        'http://localhost:5002',
        'http://127.0.0.1:5002',
    ],
}

_BIND_HOST_LITERAL_OK = frozenset({'0.0.0.0', '127.0.0.1', '::', '::1'})


def _normalize_bind_host(value):
    if not isinstance(value, str):
        return _CONFIG_DEFAULTS['api']['host']
    v = value.strip()
    if not v or len(v) > 253:
        return _CONFIG_DEFAULTS['api']['host']
    if v in _BIND_HOST_LITERAL_OK:
        return v
    if re.fullmatch(r'(?i)[a-z0-9.\-]+', v) and '..' not in v:
        return v
    return _CONFIG_DEFAULTS['api']['host']


def _apply_env_overrides(raw):
    """环境变量覆盖（优先级高于 config.json）：GEO_DATA_DIR、
    GEO_DB_DSN（postgresql://user:pass@host:port/name）或 GEO_DB_HOST 等单项。"""
    if not isinstance(raw, dict):
        return raw
    env_dir = os.environ.get('GEO_DATA_DIR')
    if env_dir and env_dir.strip():
        raw['data_dir'] = env_dir.strip()
    dsn = (os.environ.get('GEO_DB_DSN') or '').strip()
    if dsn:
        m = re.fullmatch(r'postgres(?:ql)?://([^:@/]+)(?::([^@]*))?@([^:/]+)(?::(\d+))?/([^?/]+)', dsn)
        if m:
            raw.setdefault('database', {})
            if isinstance(raw['database'], dict):
                raw['database'].update({
                    'user': m.group(1), 'password': m.group(2) or '',
                    'host': m.group(3), 'port': int(m.group(4) or 5432), 'name': m.group(5),
                })
    for env_key, cfg_key, cast in (
        ('GEO_DB_HOST', 'host', str), ('GEO_DB_PORT', 'port', int),
        ('GEO_DB_NAME', 'name', str), ('GEO_DB_USER', 'user', str),
        ('GEO_DB_PASSWORD', 'password', str),
    ):
        v = os.environ.get(env_key)
        if v:
            raw.setdefault('database', {})
            if isinstance(raw['database'], dict):
                raw['database'][cfg_key] = cast(v)
    return raw


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w', encoding='utf-8') as fh:
            json.dump(_CONFIG_DEFAULTS, fh, indent=2)
        return _apply_env_overrides(dict(_CONFIG_DEFAULTS))

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
    except Exception:
        raw = dict(_CONFIG_DEFAULTS)

    raw = _apply_env_overrides(raw)

    merged = {}
    for key, default_value in _CONFIG_DEFAULTS.items():
        if key in raw:
            if isinstance(default_value, dict) and isinstance(raw[key], dict):
                merged[key] = {**default_value, **raw[key]}
            else:
                merged[key] = raw[key]
        else:
            merged[key] = default_value

    api_cfg = merged.get('api', _CONFIG_DEFAULTS['api'])
    api_cfg['port'] = int(api_cfg.get('port') or 5010)
    api_cfg['debug'] = bool(api_cfg.get('debug', True))
    api_cfg['host'] = _normalize_bind_host(api_cfg.get('host', _CONFIG_DEFAULTS['api']['host']))
    api_cfg['threaded'] = bool(api_cfg.get('threaded', _CONFIG_DEFAULTS['api']['threaded']))
    merged['api'] = api_cfg

    db_cfg = merged.get('database', _CONFIG_DEFAULTS['database'])
    if not isinstance(db_cfg, dict):
        db_cfg = dict(_CONFIG_DEFAULTS['database'])
    db_cfg['host'] = str(db_cfg.get('host') or '127.0.0.1')
    db_cfg['port'] = int(db_cfg.get('port') or 5432)
    db_cfg['name'] = str(db_cfg.get('name') or 'geo_registry')
    db_cfg['user'] = str(db_cfg.get('user') or 'postgres')
    db_cfg['password'] = str(db_cfg.get('password') or '')
    db_cfg['pool_size'] = int(db_cfg.get('pool_size') or 5)
    merged['database'] = db_cfg

    origins = merged.get('cors_origins')
    if not isinstance(origins, list):
        merged['cors_origins'] = list(_CONFIG_DEFAULTS['cors_origins'])
    else:
        merged['cors_origins'] = [str(x).strip() for x in origins if str(x).strip()]

    return merged


def get_database_config():
    return load_config().get('database', _CONFIG_DEFAULTS['database'])


def get_geo_dir():
    """GeoNames/中文名源数据目录。优先级：GEO_DATA_DIR > config.json data_dir > 默认。"""
    configured = str(load_config().get('data_dir') or '').strip()
    if configured:
        return configured if os.path.isabs(configured) else os.path.join(BASE_DIR, configured)
    return os.path.join(BASE_DIR, 'database', 'geo')
