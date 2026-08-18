import io
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.pipeline import Job, JobStatus, jobs

client = TestClient(main.app)

# same dockerfile as the readme example
DF = 'FROM alpine:3.20\nCMD echo \'{"perf":0.5}\' > /data/perf.json\n'


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs.clear()
    yield
    jobs.clear()


@pytest.fixture
def no_pipeline(monkeypatch):
    submitted = []
    monkeypatch.setattr(main, "run_pipeline", lambda job, dockerfile, cfg: submitted.append(dockerfile))
    return submitted


def test_submit(no_pipeline):
    resp = client.post("/api/v1/jobs", json={"dockerfile": DF})

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["job_id"] in jobs
    assert no_pipeline == [DF]


def test_uploading_a_file_works_too(no_pipeline):
    files = {"dockerfile": ("Dockerfile", io.BytesIO(DF.encode()), "text/plain")}

    resp = client.post("/api/v1/jobs/upload", files=files)

    assert resp.status_code == 202
    assert no_pipeline == [DF]


def test_bad_submissions_are_rejected(no_pipeline):
    assert client.post("/api/v1/jobs", json={"dockerfile": ""}).status_code == 422
    assert client.post("/api/v1/jobs", json={}).status_code == 422

    files = {"dockerfile": ("Dockerfile", io.BytesIO(b"\xff\xfe\x00"), "application/octet-stream")}
    assert client.post("/api/v1/jobs/upload", files=files).status_code == 422

    assert no_pipeline == []


def test_status_reports_the_finished_job():
    jobs["abc"] = Job(job_id="abc", status=JobStatus.SUCCEEDED, perf=0.99, image="owkin-job:abc")

    body = client.get("/api/v1/jobs/abc").json()

    assert body["status"] == "succeeded"
    assert body["perf"] == 0.99


def test_unknown_job_is_404():
    assert client.get("/api/v1/jobs/nope").status_code == 404


def test_mock_scan_verdict_is_stable_and_split():
    first = client.post("/mock/scan", json={"image": "owkin-job:x"}).json()
    assert first == client.post("/mock/scan", json={"image": "owkin-job:x"}).json()

    scans = [client.post("/mock/scan", json={"image": f"owkin-job:{i}"}).json() for i in range(20)]
    assert {s["passed"] for s in scans} == {True, False}
    assert all(bool(s["vulnerabilities"]) is not s["passed"] for s in scans)


def test_metrics_are_exposed():
    resp = client.get("/metrics")

    assert resp.status_code == 200
    assert "owkin_image_build_duration_seconds" in resp.text
