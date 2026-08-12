FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    HF_HOME=/models/.cache

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/rizzo_model_service/requirements.lock /app/services/rizzo_model_service/requirements.lock
# Install only the fully resolved and hashed Linux/Python 3.11 CPU environment.
RUN pip install "pip==26.2.1" \
 && pip install \
      --require-hashes \
      --index-url https://pypi.org/simple \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -r /app/services/rizzo_model_service/requirements.lock

COPY services /app/services
COPY third_party /app/third_party

RUN useradd --create-home --uid 10001 app \
 && mkdir -p /models \
 && chown -R app:app /app /models
USER app

CMD ["uvicorn", "services.rizzo_model_service.main:app", "--host", "0.0.0.0", "--port", "8080"]
