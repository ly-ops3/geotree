import os

from flask import Flask, g, request

from app.config import load_config
from app.db import apply_schema, ensure_geo_places_schema, get_db
from app.handlers.geo import geo_bp, places_bp


def _close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def _add_cors_headers(response):
    cfg = load_config()
    allowed = set(cfg.get('cors_origins') or [])
    origin = request.headers.get('Origin', '')
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-API-Envelope'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response


def create_app():
    app = Flask(__name__)

    app.teardown_appcontext(_close_connection)
    app.after_request(_add_cors_headers)
    app.register_blueprint(geo_bp)
    app.register_blueprint(places_bp)

    with app.app_context():
        db = get_db()
        apply_schema(db)
        ensure_geo_places_schema(db)

    @app.route('/health', methods=['GET'])
    def health():
        from app.geo.places import geo_tables_ready

        db = get_db()
        ready = geo_tables_ready(db)
        return {'ok': True, 'service': 'geotree', 'geo_ready': ready}

    return app
