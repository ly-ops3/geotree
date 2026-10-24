FROM python:3.12-slim

WORKDIR /srv/geo-registry

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 容器内需监听 0.0.0.0；数据库连接用 GEO_DB_DSN 注入，不落盘
ENV BIND_MODE=network \
    GEO_DATA_DIR=/srv/geo-registry/database/geo \
    PYTHONUNBUFFERED=1

EXPOSE 5010

CMD ["python", "app.py", "--skip-db-check"]
