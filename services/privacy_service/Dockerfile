FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY services/requirements-common.txt /app/services/requirements-common.txt
COPY services/privacy_service/requirements.txt /app/services/privacy_service/requirements.txt
RUN pip install --no-cache-dir -r /app/services/requirements-common.txt -r /app/services/privacy_service/requirements.txt

COPY services /app/services
COPY third_party /app/third_party

CMD ["uvicorn", "services.privacy_service.main:app", "--host", "0.0.0.0", "--port", "8080"]
