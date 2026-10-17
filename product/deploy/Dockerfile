FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PRODUCT_DB=/data/product.sqlite3 PRODUCT_HOST=0.0.0.0 PRODUCT_OPEN_BROWSER=false
WORKDIR /app
COPY product/requirements.lock.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && useradd --uid 10001 --create-home appuser && mkdir /data && chown appuser:appuser /data
COPY product /app/product
USER appuser
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health',timeout=3)"
CMD ["python", "product/launch.py"]
