import os
import time

import pytest
import sqlalchemy
import db
import app as app_module
from app import app
from db import Alert, SessionLocal, init_db
import llm_service


@pytest.fixture(autouse=True)
def clean_database(monkeypatch, tmp_path):
    original_engine = db.engine
    db_path = tmp_path / "alerts.db"
    engine = sqlalchemy.create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    monkeypatch.setattr(db, "engine", engine)
    SessionLocal.configure(bind=engine)
    monkeypatch.setattr(app_module, "start_worker", lambda: None)
    init_db()
    monkeypatch.setattr(llm_service, "generate_analysis", lambda alert_data: {
        "risk_assessment": "LOW",
        "summary": "Generated test analysis.",
        "recommended_actions": ["Review manually."],
        "confidence": 0.7,
    })
    try:
        yield
    finally:
        SessionLocal.configure(bind=original_engine)
        engine.dispose()
        if db_path.exists():
            db_path.unlink(missing_ok=True)


def test_post_analyze_returns_id():
    client = app.test_client()
    payload = {
        "source": "SIEM",
        "severity": "HIGH",
        "description": "Test alert.",
        "artifacts": ["1.1.1.1", "hash123"],
    }

    response = client.post("/analyze", json=payload)
    assert response.status_code == 202
    data = response.json
    assert "id" in data
    assert isinstance(data["id"], int)


def test_get_analysis_by_id():
    client = app.test_client()
    res = client.post("/analyze", json={
        "source": "SIEM",
        "severity": "HIGH",
        "description": "Test alert.",
        "artifacts": [],
    })
    alert_pk = res.json["id"]

    response = client.get(f"/analysis/{alert_pk}")
    assert response.status_code == 200
    assert response.json["id"] == alert_pk
    assert response.json["status"] in {"PENDING", "PROCESSING", "COMPLETE", "ERROR"}


def test_each_post_creates_unique_id():
    client = app.test_client()
    payload = {
        "source": "API",
        "severity": "LOW",
        "description": "Sample alert.",
        "artifacts": [],
    }
    r1 = client.post("/analyze", json=payload)
    r2 = client.post("/analyze", json=payload)
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json["id"] != r2.json["id"]


def test_schema_endpoint_returns_json_schema():
    client = app.test_client()
    response = client.get("/schema/alert")
    assert response.status_code == 200
    schema = response.get_json()
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"source", "severity", "description"}
    assert schema["properties"]["source"]["enum"] == ["SIEM", "EDR", "API"]
    assert schema["properties"]["severity"]["enum"] == ["LOW", "MEDIUM", "HIGH"]
    assert schema["additionalProperties"] is False


def test_invalid_payload_returns_400_with_schema_url():
    client = app.test_client()
    response = client.post("/analyze", json={"source": "INVALID", "severity": "HIGH", "description": "x"})
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "validation failed"
    assert body["schema_url"] == "/schema/alert"
    assert isinstance(body["details"], list)


def test_extra_fields_are_rejected():
    client = app.test_client()
    response = client.post("/analyze", json={
        "source": "SIEM",
        "severity": "HIGH",
        "description": "Test alert.",
        "artifacts": [],
        "unexpected_field": "should fail",
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "validation failed"


def test_empty_description_rejected():
    client = app.test_client()
    response = client.post("/analyze", json={
        "source": "SIEM",
        "severity": "HIGH",
        "description": "",
        "artifacts": [],
    })
    assert response.status_code == 400


def test_non_object_body_rejected():
    client = app.test_client()
    response = client.post("/analyze", json=["not", "an", "object"])
    assert response.status_code == 400
    assert response.get_json()["schema_url"] == "/schema/alert"


def test_health_page_renders():
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Test Health" in body
    assert "Run Tests" in body
    assert "/static/health.js" in body


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_health_run_executes_real_subprocess(monkeypatch):
    """End-to-end: /health/run must spawn the real tests_runner.py subprocess,
    which runs the real pytest binary. We filter via -k to a small set of
    deterministic tests so the inner subprocess does not recurse into the
    health-run tests themselves."""
    import subprocess as _subprocess

    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    real_run = _subprocess.run

    def run_with_filter(cmd, **kwargs):
        # cmd is [python, tests_runner.py, output_path]. Append a -k filter so the
        # inner pytest only collects fast, side-effect-free unit tests (i.e. not
        # the /health/run tests, which would recurse).
        filtered_cmd = list(cmd) + ["-k", "test_parse_json_safe or test_normalize_response"]
        return real_run(filtered_cmd, **kwargs)

    monkeypatch.setattr(_subprocess, "run", run_with_filter)
    # Run subprocess from the project root so it finds the tests/ folder.
    monkeypatch.chdir(project_dir)

    client = app.test_client()
    response = client.get("/health/run")
    assert response.status_code == 200, response.get_json()
    data = response.get_json()

    # The real runner reports real pytest outcomes.
    assert data["exit_code"] == 0
    assert data["summary"]["total"] >= 4  # at least 4 parse_json + normalize tests
    assert data["summary"]["passed"] == data["summary"]["total"]
    assert data["summary"]["failed"] == 0
    assert data["summary"]["error"] == 0

    # Every test node came from a real pytest collection.
    nodeids = {t["nodeid"] for t in data["tests"]}
    assert any("test_parse_json_safe" in n for n in nodeids)
    assert any("test_normalize_response" in n for n in nodeids)

    assert "ran_at" in data
    assert "wall_duration" in data and data["wall_duration"] > 0


def test_health_run_handles_subprocess_exception(monkeypatch):
    import subprocess

    def boom(_cmd, **_kwargs):
        raise OSError("cannot spawn python")

    monkeypatch.setattr(subprocess, "run", boom)

    client = app.test_client()
    response = client.get("/health/run")
    assert response.status_code == 500
    data = response.get_json()
    assert data["exit_code"] == -1
    assert "cannot spawn python" in data["error"]


def test_health_run_handles_timeout(monkeypatch):
    import subprocess

    def slow(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=180)

    monkeypatch.setattr(subprocess, "run", slow)

    client = app.test_client()
    response = client.get("/health/run")
    assert response.status_code == 500
    data = response.get_json()
    assert data["exit_code"] == -1
    assert "timeout" in data["error"].lower()


def test_health_run_handles_invalid_json_output(monkeypatch):
    import subprocess

    def garbage(cmd, **_kwargs):
        # Runner crashed before writing the JSON report: leave the file empty.
        with open(cmd[2], "w", encoding="utf-8") as fh:
            fh.write("")
        return _FakeProc(stdout="boom on stdout", stderr="boom on stderr", returncode=2)

    monkeypatch.setattr(subprocess, "run", garbage)

    client = app.test_client()
    response = client.get("/health/run")
    assert response.status_code == 500
    data = response.get_json()
    assert data["exit_code"] == 2
    assert "valid JSON" in data["error"]
    assert "boom on stderr" in data["stderr_excerpt"]


def test_alerts_filtering():
    client = app.test_client()
    client.post("/analyze", json={
        "source": "SIEM",
        "severity": "LOW",
        "description": "First alert.",
        "artifacts": [],
    })
    client.post("/analyze", json={
        "source": "EDR",
        "severity": "HIGH",
        "description": "Second alert.",
        "artifacts": [],
    })

    response = client.get("/alerts?source=SIEM")
    assert response.status_code == 200
    alerts = response.get_json()
    assert all(alert["source"] == "SIEM" for alert in alerts)
