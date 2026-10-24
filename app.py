"""Geo Registry — 地理名称库 API 入口。

用法:
    python app.py              本机 (127.0.0.1)
    python app.py -n           局域网 (0.0.0.0)
    python app.py --skip-db-check
"""

import argparse
import os
import sys

from app import create_app
from app.config import get_database_config, load_config

_flask_app = None


def get_flask_app():
    global _flask_app
    if _flask_app is None:
        _flask_app = create_app()
    return _flask_app


def check_postgresql():
    cfg = get_database_config()
    label = f"{cfg['host']}:{cfg['port']}/{cfg['name']}"
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=cfg['host'],
            port=cfg['port'],
            dbname=cfg['name'],
            user=cfg['user'],
            password=cfg.get('password') or '',
            connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
    except Exception as exc:
        print('PostgreSQL 连接失败:', label)
        print(' ', exc)
        print()
        print('请确认:')
        print('  1. PostgreSQL 服务已启动')
        print('  2. 已创建数据库 geo_registry（见 README）')
        print('  3. config.json → database 段正确')
        return False
    print(f'PostgreSQL OK  {label}  (user={cfg["user"]})')
    return True


def _parse_args(argv):
    parser = argparse.ArgumentParser(description='Geo Registry API')
    parser.add_argument('-n', '--network', action='store_true', help='绑定 0.0.0.0')
    parser.add_argument('--local', action='store_true', help='绑定 127.0.0.1')
    parser.add_argument('--skip-db-check', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv or sys.argv[1:])
    run_cfg = load_config()
    api_cfg = run_cfg.get('api', {})
    bind_port = int(api_cfg.get('port') or 5010)
    use_threaded = bool(api_cfg.get('threaded', True))

    if args.network:
        bind_host = '0.0.0.0'
        mode_label = 'LAN'
    elif args.local:
        bind_host = '127.0.0.1'
        mode_label = 'Localhost'
    else:
        bind_mode = os.environ.get('BIND_MODE', run_cfg.get('bind_mode', 'local'))
        if str(bind_mode).strip().lower() == 'network':
            bind_host = '0.0.0.0'
            mode_label = 'LAN'
        else:
            bind_host = '127.0.0.1'
            mode_label = 'Localhost'

    is_flask_eval = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    is_debug_mode = api_cfg.get('debug', True)

    if not is_debug_mode or is_flask_eval:
        print('=' * 46)
        print(' Geo Registry — 地理名称库 API')
        print('=' * 46)
        if not args.skip_db_check and not check_postgresql():
            return 1
        print(f' Network Mode : {mode_label}')
        print(f' Local Access : http://127.0.0.1:{bind_port}')
        print(f' Health       : http://127.0.0.1:{bind_port}/health')
        print('=' * 46)

    get_flask_app().run(
        host=bind_host,
        debug=is_debug_mode,
        port=bind_port,
        threaded=use_threaded,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
