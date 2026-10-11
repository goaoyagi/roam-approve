FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY bridge/ ./bridge/
RUN pip install --no-cache-dir ./bridge \
    && useradd --create-home --uid 10001 bridge

USER bridge
EXPOSE 8000
CMD ["uvicorn", "roam_approve_bridge.main:app", "--host", "0.0.0.0", "--port", "8000"]
