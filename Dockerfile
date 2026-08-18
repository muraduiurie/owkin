FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_FILE=/app/config.yaml

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config.yaml .

EXPOSE 8000

# root because of the docker socket; a non-root user would need the host's
# docker gid passed in via --group-add and that differs per machine
CMD ["python", "-m", "app.main"]
