import hashlib
import logging

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Response, UploadFile
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from app.config import get_settings
from app.pipeline import Job, create_job, jobs, run_pipeline

MAX_DOCKERFILE_BYTES = 64 * 1024

app = FastAPI(title="dockerfile-jobs")


class DockerfileRequest(BaseModel):
    dockerfile: str = Field(min_length=1, max_length=MAX_DOCKERFILE_BYTES)


def _submit(dockerfile: str, background: BackgroundTasks) -> Job:
    job = create_job()
    background.add_task(run_pipeline, job, dockerfile, get_settings())
    return job


@app.post("/api/v1/jobs", status_code=202)
async def submit_dockerfile(payload: DockerfileRequest, background: BackgroundTasks) -> Job:
    return _submit(payload.dockerfile, background)


@app.post("/api/v1/jobs/upload", status_code=202)
async def upload_dockerfile(background: BackgroundTasks, dockerfile: UploadFile = File(...)) -> Job:
    raw = await dockerfile.read()
    if len(raw) > MAX_DOCKERFILE_BYTES:
        raise HTTPException(413, f"dockerfile exceeds {MAX_DOCKERFILE_BYTES} bytes")
    try:
        content = raw.decode()
    except UnicodeDecodeError:
        raise HTTPException(422, "dockerfile must be utf-8")
    return _submit(content, background)


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str) -> Job:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


class ScanRequest(BaseModel):
    image: str


@app.post("/mock/scan")
async def mock_scan(payload: ScanRequest) -> dict:
    """Stand-in for the third-party scanner. Same image always gets the same verdict."""
    passed = hashlib.sha256(payload.image.encode()).digest()[0] % 2 == 0
    return {
        "image": payload.image,
        "passed": passed,
        "vulnerabilities": [] if passed else ["CVE-1234", "CVE-5678"],
    }


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def main():
    cfg = get_settings()
    # don't raise the root logger, docker/httpx are unreadable at DEBUG
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    logging.getLogger("app").setLevel(logging.DEBUG if cfg.debug else logging.ERROR)
    uvicorn.run("app.main:app", host=cfg.server.host, port=cfg.server.port)


if __name__ == "__main__":
    main()
