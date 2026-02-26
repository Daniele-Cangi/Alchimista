FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY services/requirements-common.txt /app/services/requirements-common.txt
COPY services/dashboard_service/requirements.txt /app/services/dashboard_service/requirements.txt
RUN pip install --no-cache-dir -r /app/services/requirements-common.txt -r /app/services/dashboard_service/requirements.txt

COPY services /app/services

CMD ["uvicorn", "services.dashboard_service.app:app", "--host", "0.0.0.0", "--port", "8080"]
