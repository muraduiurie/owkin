# Owkin technical test

Service that recieves a Dockerfile through a REST API, builds the docker image, scans it
for vulnerabilities via an external scanner and, if the scan passes, runs the container
and reads the performance the container writes to `/data/perf.json`.

## Architecture

```
POST /api/v1/jobs        -> job id returned immediately (202)
   background task       -> build -> scan -> run -> read perf.json
GET /api/v1/jobs/{id}    -> status, perf, image, error
```

- `app/main.py`: HTTP layer. Submit endpoints, job status endpoint, mock scanner, `/metrics`.
- `app/pipeline.py`: job model, in memory job store, build/scan/run stages.
- `app/config.py`: settings from `config.yaml`, each value overridable via env var (`SERVER__PORT`, `SCANNER__URL`, `DOCKER__DATA_DIR`, etc.).

Job statuses: `pending` -> `building` -> `scanning` -> `running` -> `succeeded` / `failed`.
Failed jobs keep the reason in the `error` field.

Notes:

- Jobs are kept in memory, so single process only. Restart loses the jobs.
- The scan verdict comes from a mock endpoint in the same app (`POST /mock/scan`), pass/fail based on the image name hash. Point `SCANNER__URL` at a real scanner to replace it.
- The image tag is the job id, so images can be traced back to their job.

## Libraries

- `fastapi` + `uvicorn`: REST API.
- `docker`: official sdk, talks to the docker socket directly.
- `httpx`: HTTP client for the scanner call.
- `pydantic-settings`: config file loading + env overrides.
- `prometheus-client`: build duration histogram on `/metrics`.
- `python-multipart`: needed by FastAPI for file uploads.

## Usage

Submit a dockerfile as text:

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM alpine:3.20\nCMD echo '"'"'{\"perf\":0.99}'"'"' > /data/perf.json"}'
```

Submit as a file:

```bash
curl -X POST http://localhost:8000/api/v1/jobs/upload -F "dockerfile=@Dockerfile"
```

Both return a job id, then poll it:

```bash
curl http://localhost:8000/api/v1/jobs/<job_id>
```

```json
{"job_id": "...", "status": "succeeded", "perf": 0.99, "image": "owkin-job:...", "error": null}
```

Swagger UI available at `/docs`.

## Local development

Requirements:

- Python 3.12+
- running docker daemon

Steps:

- Create a venv and install the dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

- Run the service:

```bash
.venv/bin/python -m app.main
```

To run the service itself in docker:

```bash
docker build -t owkin-service .
docker run --rm -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/owkin:/tmp/owkin \
  owkin-service
```

Both mounts are needed. The socket to reach the host docker daemon, and `/tmp/owkin`
because the per job /data volumes are created there and the bind mount is resolved on the
host, without it the service cannot read the perf back. Path configurable via `DOCKER__DATA_DIR`.

## Tests

```bash
.venv/bin/python -m pytest
```

Docker sdk and the scanner are faked in the tests, no daemon or network needed.

## Improvements

- Persist jobs in Redis to survive restarts and allow more than one replica.
- Move builds to a task queue instead of in process background tasks.
- Push built images to a registry.
- Cleanup policy for built images and finished jobs.
- Metrics for scan and run durations, job counts by status.
- Helm chart.
