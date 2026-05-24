FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY services ./services

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /data

EXPOSE 8000 8001

CMD ["uvicorn", "event_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
