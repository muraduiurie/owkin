import httpx
import pytest

from app.config import Settings
from app.pipeline import Job, JobStatus, run_pipeline
from tests.conftest import FakeDocker

DF = 'FROM alpine:3.20\nCMD echo \'{"perf":0.5}\' > /data/perf.json\n'


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_FILE", "/nonexistent/config.yaml")
    return Settings(docker={"data_dir": str(tmp_path / "data")})


def _scan_reply(monkeypatch, passed, vulns=()):
    def fake_post(url, **kw):
        return httpx.Response(
            200,
            json={"passed": passed, "vulnerabilities": list(vulns)},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)


@pytest.fixture
def scan_passes(monkeypatch):
    _scan_reply(monkeypatch, True)


def test_happy_path(cfg, scan_passes):
    job, client = Job(job_id="j1"), FakeDocker(perf=0.99)

    run_pipeline(job, DF, cfg, client=client)

    assert job.status is JobStatus.SUCCEEDED
    assert job.perf == 0.99
    assert job.image == "owkin-job:j1"
    assert client.built == ["owkin-job:j1"]
    assert client.last_container.removed


def test_scan_rejection_fails_the_job_without_running_it(cfg, monkeypatch):
    _scan_reply(monkeypatch, False, ["CVE-1"])
    job, client = Job(job_id="j1"), FakeDocker(perf=0.99)

    run_pipeline(job, DF, cfg, client=client)

    assert job.status is JobStatus.FAILED
    assert "CVE-1" in job.error
    assert job.perf is None
    assert client.last_container is None  # never ran


def test_build_failure_fails_the_job(cfg, scan_passes):
    job = Job(job_id="j1")

    run_pipeline(job, "NOPE", cfg, client=FakeDocker(build_error=RuntimeError("unknown instruction: NOPE")))

    assert job.status is JobStatus.FAILED
    assert "unknown instruction" in job.error


def test_nonzero_exit_fails_the_job(cfg, scan_passes):
    job = Job(job_id="j1")

    run_pipeline(job, DF, cfg, client=FakeDocker(exit_code=3))

    assert job.status is JobStatus.FAILED
    assert "exited with 3" in job.error


def test_missing_perf_file_fails_the_job(cfg, scan_passes):
    job = Job(job_id="j1")

    run_pipeline(job, DF, cfg, client=FakeDocker(perf=None))

    assert job.status is JobStatus.FAILED
    assert "did not write" in job.error


@pytest.mark.parametrize("raw", ["not json", '{"score": 1}', '{"perf": "high"}'])
def test_bad_perf_payloads_fail_the_job(cfg, scan_passes, raw):
    job = Job(job_id="j1")

    run_pipeline(job, DF, cfg, client=FakeDocker(raw=raw))

    assert job.status is JobStatus.FAILED
    assert "perf.json" in job.error
