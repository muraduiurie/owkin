import io
import json
import logging
import shutil
import tempfile
import time
import uuid
from enum import Enum
from pathlib import Path

import docker
import httpx
from prometheus_client import Histogram
from pydantic import BaseModel

from app.config import Settings

log = logging.getLogger(__name__)

# docker builds run from seconds to minutes, the client's default buckets stop at 10s
BUILD_DURATION = Histogram(
    "owkin_image_build_duration_seconds",
    "Time spent building a docker image",
    labelnames=("result",),
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
)
# TODO: scan/run durations, job counts by terminal status, http latency


class JobStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    SCANNING = "scanning"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    perf: float | None = None
    image: str | None = None
    error: str | None = None


# plain dict, so single process only and a restart drops in-flight jobs
jobs: dict[str, Job] = {}


class ScanRejected(Exception):
    pass


class RunFailed(Exception):
    pass


def create_job() -> Job:
    job = Job(job_id=str(uuid.uuid4()))
    jobs[job.job_id] = job
    return job


def run_pipeline(job: Job, dockerfile: str, cfg: Settings, client=None) -> None:
    client = client or docker.from_env()
    try:
        job.status = JobStatus.BUILDING
        job.image = f"{cfg.docker.repository}:{job.job_id}"
        _build(client, dockerfile, job.image)

        job.status = JobStatus.SCANNING
        _scan(cfg.scanner, job.image)

        job.status = JobStatus.RUNNING
        job.perf = _run(client, cfg.docker, job.image)

        job.status = JobStatus.SUCCEEDED
        log.debug("job %s succeeded with perf %s", job.job_id, job.perf)
    except Exception as exc:  # this runs on a worker thread, nothing may escape
        log.error("job %s failed: %s", job.job_id, exc)
        log.debug("job %s traceback", job.job_id, exc_info=True)
        job.status = JobStatus.FAILED
        job.error = str(exc)


def _build(client, dockerfile: str, ref: str) -> None:
    log.debug("building %s", ref)
    started, result = time.perf_counter(), "success"
    try:
        client.images.build(fileobj=io.BytesIO(dockerfile.encode()), tag=ref, rm=True)
    except Exception:
        result = "failure"
        raise
    finally:
        BUILD_DURATION.labels(result=result).observe(time.perf_counter() - started)


def _scan(cfg, image: str) -> None:
    log.debug("scanning %s via %s", image, cfg.url)
    resp = httpx.post(cfg.url, json={"image": image}, timeout=cfg.timeout)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("passed"):
        found = ", ".join(body.get("vulnerabilities", [])) or "no details"
        raise ScanRejected(f"image rejected by scanner: {found}")


def _run(client, cfg, image: str) -> float:
    """Runs the image with /data on a volume and returns what it wrote there."""
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="job-", dir=cfg.data_dir))
    container = None
    try:
        log.debug("running %s with /data -> %s", image, data_dir)
        container = client.containers.run(
            image, detach=True, volumes={str(data_dir): {"bind": "/data", "mode": "rw"}}
        )
        code = container.wait(timeout=cfg.run_timeout).get("StatusCode", -1)
        if code != 0:
            logs = container.logs(tail=20).decode(errors="replace").strip()
            raise RunFailed(f"container exited with {code}: {logs}")
        return _read_perf(data_dir / "perf.json")
    finally:
        if container is not None:
            container.remove(force=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def _read_perf(path: Path) -> float:
    if not path.exists():
        raise RunFailed("container did not write /data/perf.json")
    try:
        return float(json.loads(path.read_text())["perf"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RunFailed(f"bad perf.json: {exc!r}") from exc
