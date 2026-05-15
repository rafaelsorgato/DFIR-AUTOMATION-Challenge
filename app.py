import json
import queue
import threading
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template, Response
from flasgger import Swagger
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from db import Alert, SessionLocal, init_db
from llm_service import generate_analysis
from models import AlertCreate, AlertResponse
from security import validate_no_sensitive_data

app = Flask(__name__, template_folder="templates", static_folder="static")

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [{"endpoint": "apispec", "route": "/apispec.json"}],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
}
SWAGGER_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "Alert Analyzer API",
        "description": "API for submitting and analyzing security alerts with an LLM.",
        "version": "1.0.0",
    },
    "tags": [
        {"name": "Alerts", "description": "Alert creation, listing, and reanalysis"},
        {"name": "Schema", "description": "JSON Schema definitions for request/response payloads"},
        {"name": "Stream", "description": "Real-time notifications (SSE)"},
    ],
    "consumes": ["application/json"],
    "produces": ["application/json"],
}
Swagger(app, config=SWAGGER_CONFIG, template=SWAGGER_TEMPLATE)

init_db()
_event_subscribers: list[queue.Queue] = []
_pending_queue: queue.Queue = queue.Queue()
_db_lock = threading.Lock()


def publish_event(payload: dict):
    message = f"data: {json.dumps(payload, default=str)}\n\n"
    for subscriber in list(_event_subscribers):
        try:
            subscriber.put_nowait(message)
        except queue.Full:
            continue


def get_alert(db, pk: int) -> Alert | None:
    return db.query(Alert).filter(Alert.id == pk).first()


def commit_with_retry(db):
    for attempt in range(3):
        try:
            db.commit()
            return
        except SQLAlchemyError:
            db.rollback()
            if attempt == 2:
                raise
            time.sleep(0.2)


def enqueue_pending_alerts():
    db = SessionLocal()
    try:
        pending = db.query(Alert).filter(Alert.status == "PENDING").order_by(Alert.created_at).all()
        for alert in pending:
            _pending_queue.put(alert.id)
    finally:
        db.close()


def worker_loop():
    while True:
        try:
            pk = _pending_queue.get(timeout=1)
        except queue.Empty:
            continue

        db = SessionLocal()
        alert = None
        try:
            alert = get_alert(db, pk)
            if not alert or alert.status != "PENDING":
                continue
            alert.status = "PROCESSING"
            alert.updated_at = datetime.now(timezone.utc)
            commit_with_retry(db)
            publish_event({"type": "status", "id": pk, "status": alert.status})

            alert_payload = {
                "alert_id": str(pk),
                "source": alert.source,
                "severity": alert.severity,
                "description": alert.description,
                "artifacts": json.loads(alert.artifacts),
            }
            analysis = generate_analysis(alert_payload)
            alert.analysis_result = json.dumps(analysis, ensure_ascii=False)
            alert.status = "ERROR" if analysis.get("_failed") else "COMPLETE"
            alert.updated_at = datetime.now(timezone.utc)
            commit_with_retry(db)
            publish_event({"type": "analysis", "id": pk, "analysis": analysis})
        except Exception:
            if alert:
                alert.status = "ERROR"
                alert.updated_at = datetime.now(timezone.utc)
                db.add(alert)
                commit_with_retry(db)
        finally:
            db.close()
            _pending_queue.task_done()


_worker_started = False


def start_worker():
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    enqueue_pending_alerts()
    thread = threading.Thread(target=worker_loop, daemon=True)
    thread.start()


@app.before_request
def maybe_start_worker():
    start_worker()


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health_page():
    return render_template("health.html")


@app.route("/health/run", methods=["GET"])
def health_run():
    """
    Run the project's pytest suite in an isolated subprocess and return a JSON report.

    Why a subprocess: tests rebind SessionLocal and mock module-level callables.
    Running them in-process would corrupt the live app's globals while the suite is
    executing and leak state on teardown.
    ---
    tags: [Stream]
    responses:
      200:
        description: Aggregate suite result + per-test outcomes.
    """
    import os
    import pathlib
    import subprocess
    import sys
    import tempfile

    project_dir = pathlib.Path(__file__).parent
    runner_path = project_dir / "tests_runner.py"

    fd, output_path = tempfile.mkstemp(suffix=".json", prefix="health_run_")
    os.close(fd)

    started = time.time()
    try:
        try:
            proc = subprocess.run(
                [sys.executable, str(runner_path), output_path],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return jsonify({
                "exit_code": -1,
                "error": "test run exceeded 180s timeout",
                "ran_at": datetime.now(timezone.utc).isoformat(),
            }), 500
        except Exception as exc:
            return jsonify({
                "exit_code": -1,
                "error": f"failed to spawn pytest subprocess: {exc}",
                "ran_at": datetime.now(timezone.utc).isoformat(),
            }), 500

        wall = round(time.time() - started, 4)
        try:
            with open(output_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            return jsonify({
                "exit_code": proc.returncode,
                "error": f"test runner did not produce a valid JSON report: {exc}",
                "stdout_excerpt": (proc.stdout or "")[-500:],
                "stderr_excerpt": (proc.stderr or "")[-500:],
                "ran_at": datetime.now(timezone.utc).isoformat(),
            }), 500

        data["ran_at"] = datetime.now(timezone.utc).isoformat()
        data["wall_duration"] = wall
        return jsonify(data)
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Create a new alert for LLM analysis.
    ---
    tags: [Alerts]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [source, severity, description, artifacts]
          properties:
            source:
              type: string
              enum: [SIEM, EDR, API]
              example: SIEM
            severity:
              type: string
              enum: [LOW, MEDIUM, HIGH]
              example: HIGH
            description:
              type: string
              example: "Suspicious login detected from external IP"
            artifacts:
              type: array
              items: {type: string}
              example: ["1.2.3.4", "user@example.com"]
    responses:
      202:
        description: Alert accepted and queued for analysis
        schema:
          type: object
          properties:
            message: {type: string, example: "alert received"}
            id: {type: integer, example: 42}
      400:
        description: Invalid JSON or Pydantic validation failure
        schema:
          type: object
          properties:
            error: {type: string, example: "validation failed"}
            details:
              type: array
              items: {type: object}
              description: List of Pydantic validation errors
            schema_url:
              type: string
              example: "/schema/alert"
              description: Endpoint that returns the expected JSON Schema
      500:
        description: Failed to insert alert into the database
    """
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({
            "error": "invalid JSON",
            "schema_url": "/schema/alert",
        }), 400

    if not isinstance(payload, dict):
        return jsonify({
            "error": "request body must be a JSON object",
            "schema_url": "/schema/alert",
        }), 400

    try:
        alert_data = AlertCreate(**payload)
    except ValidationError as validation_error:
        return jsonify({
            "error": "validation failed",
            "details": validation_error.errors(),
            "schema_url": "/schema/alert",
        }), 400

    sensitive = validate_no_sensitive_data(alert_data.description, alert_data.artifacts)
    if sensitive:
        return jsonify({
            "error": "sensitive data detected",
            "details": [
                {"field": m.field, "category": m.category, "hint": m.hint}
                for m in sensitive
            ],
            "message": (
                "The payload appears to contain credentials or private keys. "
                "Remove sensitive values before submitting. "
                "Describe the attack behaviour without including the actual secret."
            ),
            "schema_url": "/schema/alert",
        }), 400

    db = SessionLocal()
    try:
        alert = Alert(
            source=alert_data.source,
            severity=alert_data.severity,
            description=alert_data.description,
            artifacts=json.dumps(alert_data.artifacts, ensure_ascii=False),
            status="PENDING",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(alert)
        commit_with_retry(db)
        _pending_queue.put(alert.id)
        publish_event({"type": "new_alert", "alert": alert.to_dict()})
        return jsonify({"message": "alert received", "id": alert.id}), 202
    except SQLAlchemyError as exc:
        db.rollback()
        return jsonify({"error": "failed to insert alert", "detail": str(exc)}), 500
    finally:
        db.close()


@app.route("/analysis/<int:pk>", methods=["GET"])
def get_analysis(pk: int):
    """
    Return an alert together with its analysis result.
    ---
    tags: [Alerts]
    parameters:
      - in: path
        name: pk
        type: integer
        required: true
        description: Auto-incremented alert ID
    responses:
      200:
        description: Alert found
        schema:
          type: object
          properties:
            id: {type: integer}
            source: {type: string}
            severity: {type: string}
            description: {type: string}
            artifacts: {type: array, items: {type: string}}
            status:
              type: string
              enum: [PENDING, PROCESSING, COMPLETE, ERROR]
            analysis_result:
              type: object
              properties:
                risk_assessment: {type: string, enum: [LOW, MEDIUM, HIGH, ERROR]}
                summary: {type: string}
                recommended_actions: {type: array, items: {type: string}}
                confidence: {type: number, format: float, minimum: 0, maximum: 1}
            created_at: {type: string, format: date-time}
            updated_at: {type: string, format: date-time}
      404:
        description: Alert not found
    """
    db = SessionLocal()
    try:
        alert = get_alert(db, pk)
        if not alert:
            return jsonify({"error": "alert not found"}), 404
        return jsonify(alert.to_dict())
    finally:
        db.close()


@app.route("/alerts", methods=["GET"])
def list_alerts():
    """
    List the latest 200 alerts, with optional filters.
    ---
    tags: [Alerts]
    parameters:
      - in: query
        name: source
        type: string
        enum: [SIEM, EDR, API]
        required: false
        description: Filter by source
      - in: query
        name: severity
        type: string
        enum: [LOW, MEDIUM, HIGH]
        required: false
        description: Filter by severity
    responses:
      200:
        description: List of alerts (sorted by date, descending)
        schema:
          type: array
          items:
            type: object
            properties:
              id: {type: integer}
              source: {type: string}
              severity: {type: string}
              description: {type: string}
              artifacts: {type: array, items: {type: string}}
              status: {type: string}
              analysis_result: {type: object}
              queue_position:
                type: integer
                description: Position in the queue (only for PENDING status; null otherwise)
              created_at: {type: string}
              updated_at: {type: string}
    """
    src_filter = request.args.get("source")
    sev_filter = request.args.get("severity")
    db = SessionLocal()
    try:
        query = db.query(Alert)
        if src_filter:
            query = query.filter(Alert.source == src_filter)
        if sev_filter:
            query = query.filter(Alert.severity == sev_filter)
        alerts = query.order_by(Alert.created_at.desc()).limit(200).all()
        pending_pks = [a.id for a in db.query(Alert).filter(Alert.status == "PENDING").order_by(Alert.created_at).all()]
        items = []
        for alert in alerts:
            item = alert.to_dict()
            item["queue_position"] = (pending_pks.index(alert.id) + 1) if alert.id in pending_pks else None
            items.append(item)
        return jsonify(items)
    finally:
        db.close()


@app.route("/alerts/retry-errors", methods=["POST"])
def retry_all_errors():
    """
    Re-queue every alert currently in ERROR status.
    ---
    tags: [Alerts]
    responses:
      202:
        description: All ERROR alerts re-queued
        schema:
          type: object
          properties:
            message: {type: string}
            count: {type: integer}
      500:
        description: Database error
    """
    db = SessionLocal()
    try:
        errors = db.query(Alert).filter(Alert.status == "ERROR").all()
        for alert in errors:
            alert.status = "PENDING"
            alert.analysis_result = None
            alert.updated_at = datetime.now(timezone.utc)
        if errors:
            commit_with_retry(db)
            for alert in errors:
                _pending_queue.put(alert.id)
                publish_event({"type": "status", "id": alert.id, "status": "PENDING"})
        return jsonify({"message": f"{len(errors)} alert(s) re-queued", "count": len(errors)}), 202
    except SQLAlchemyError as exc:
        db.rollback()
        return jsonify({"error": "failed to re-queue alerts", "detail": str(exc)}), 500
    finally:
        db.close()


@app.route("/alerts/<int:pk>/retry", methods=["POST"])
def retry_alert(pk: int):
    """
    Re-queue an alert for a new LLM analysis.
    ---
    tags: [Alerts]
    parameters:
      - in: path
        name: pk
        type: integer
        required: true
        description: ID of the alert to reanalyze
    responses:
      202:
        description: Alert successfully re-queued
        schema:
          type: object
          properties:
            message: {type: string, example: "alert re-queued"}
      404:
        description: Alert not found
      409:
        description: Alert is already in PENDING or PROCESSING state
      500:
        description: Failed to update the database
    """
    db = SessionLocal()
    try:
        alert = get_alert(db, pk)
        if not alert:
            return jsonify({"error": "alert not found"}), 404
        if alert.status in ("PENDING", "PROCESSING"):
            return jsonify({"error": "alert is already being processed"}), 409
        alert.status = "PENDING"
        alert.analysis_result = None
        alert.updated_at = datetime.now(timezone.utc)
        commit_with_retry(db)
        _pending_queue.put(alert.id)
        publish_event({"type": "status", "id": pk, "status": "PENDING"})
        return jsonify({"message": "alert re-queued"}), 202
    except SQLAlchemyError as exc:
        db.rollback()
        return jsonify({"error": "failed to re-queue alert", "detail": str(exc)}), 500
    finally:
        db.close()


@app.route("/schema/alert", methods=["GET"])
def schema_alert():
    """
    Return the JSON Schema for the POST /analyze request body.
    ---
    tags: [Schema]
    responses:
      200:
        description: JSON Schema describing required fields and constraints
        schema:
          type: object
    """
    return jsonify(AlertCreate.model_json_schema())


@app.route("/schema/analysis", methods=["GET"])
def schema_analysis():
    """
    Return the JSON Schema for the analysis result attached to an alert.
    ---
    tags: [Schema]
    responses:
      200:
        description: JSON Schema describing the analysis result object
        schema:
          type: object
    """
    return jsonify(AlertResponse.model_json_schema())


@app.route("/stream")
def stream():
    """
    Server-Sent Events (SSE) stream for real-time alert updates.
    ---
    tags: [Stream]
    produces:
      - text/event-stream
    responses:
      200:
        description: |
          Continuous stream of JSON events. Published types:
            * new_alert  — new alert created
            * status     — status change of an alert
            * analysis   — analysis completed
    """
    q = queue.Queue(maxsize=32)
    _event_subscribers.append(q)

    def event_generator():
        try:
            while True:
                message = q.get()
                yield message
        finally:
            _event_subscribers.remove(q)

    return Response(event_generator(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
