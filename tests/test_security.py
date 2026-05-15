import pytest
from security import SensitiveMatch, validate_no_sensitive_data, _scan


# ── _scan: credential key=value pairs ──────────────────────────
class TestCredentialKeyValue:
    def test_password_equals(self):
        assert _scan("f", "password=SuperSecret1") != []

    def test_password_colon(self):
        assert _scan("f", "password: SuperSecret1") != []

    def test_passwd_variant(self):
        assert _scan("f", "passwd=abc123") != []

    def test_token_equals(self):
        assert _scan("f", "token=eyABCDEFGHIJ") != []

    def test_access_token(self):
        assert _scan("f", "access_token=abcdefghijkl") != []

    def test_api_key_underscore(self):
        assert _scan("f", "api_key=ABCDEFGH1234") != []

    def test_api_key_no_separator(self):
        assert _scan("f", "apikey=ABCDEFGH1234") != []

    def test_client_secret(self):
        assert _scan("f", "client_secret=very_long_secret_value") != []

    def test_secret_equals(self):
        assert _scan("f", "secret=topsecretvalue") != []

    def test_session_token(self):
        assert _scan("f", "session_token=xYz9876abcdef") != []

    def test_case_insensitive(self):
        assert _scan("f", "PASSWORD=hunter2") != []
        assert _scan("f", "API_KEY=some_key_value") != []

    def test_category_is_credential(self):
        matches = _scan("f", "token=abc1234567")
        assert any(m.category == "credential" for m in matches)

    def test_value_too_short_not_flagged(self):
        # value shorter than 4 chars should not trigger
        assert _scan("f", "password=abc") == []

    def test_prose_mention_not_flagged(self):
        # "password" alone in a sentence without an assignment is not a credential
        assert _scan("f", "The attacker performed a password spray attack") == []

    def test_password_reset_not_flagged(self):
        assert _scan("f", "User requested a password reset") == []


# ── _scan: PEM private keys ─────────────────────────────────────
class TestPemPrivateKey:
    def test_rsa_private_key(self):
        assert _scan("f", "-----BEGIN RSA PRIVATE KEY-----") != []

    def test_ec_private_key(self):
        assert _scan("f", "-----BEGIN EC PRIVATE KEY-----") != []

    def test_openssh_private_key(self):
        assert _scan("f", "-----BEGIN OPENSSH PRIVATE KEY-----") != []

    def test_generic_private_key(self):
        assert _scan("f", "-----BEGIN PRIVATE KEY-----") != []

    def test_category_is_private_key(self):
        matches = _scan("f", "-----BEGIN RSA PRIVATE KEY-----")
        assert any(m.category == "private_key" for m in matches)

    def test_public_key_not_flagged(self):
        assert _scan("f", "-----BEGIN PUBLIC KEY-----") == []

    def test_certificate_not_flagged(self):
        assert _scan("f", "-----BEGIN CERTIFICATE-----") == []


# ── _scan: AWS credentials ──────────────────────────────────────
class TestAwsCredentials:
    def test_akia_access_key(self):
        assert _scan("f", "AKIAIOSFODNN7EXAMPLE") != []

    def test_agpa_access_key(self):
        assert _scan("f", "AGPA1234567890ABCDEF") != []

    def test_aws_secret_key_assignment(self):
        assert _scan("f", "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY") != []

    def test_category_is_aws_credential(self):
        matches = _scan("f", "AKIAIOSFODNN7EXAMPLE")
        assert any(m.category == "aws_credential" for m in matches)

    def test_akia_too_short_not_flagged(self):
        # Must be exactly AKIA + 16 chars
        assert _scan("f", "AKIA123") == []


# ── _scan: connection strings ───────────────────────────────────
class TestConnectionStrings:
    def test_postgres_with_password(self):
        assert _scan("f", "postgresql://admin:s3cr3t@db.internal:5432/app") != []

    def test_mysql_with_password(self):
        assert _scan("f", "mysql://root:password123@localhost/mydb") != []

    def test_mongodb_with_password(self):
        assert _scan("f", "mongodb://user:pass1234@cluster.example.com/db") != []

    def test_redis_with_password(self):
        assert _scan("f", "redis://:myredispassword@redis.host:6379") != []

    def test_category_is_connection_string(self):
        matches = _scan("f", "postgresql://admin:hunter2@host/db")
        assert any(m.category == "connection_string" for m in matches)

    def test_url_without_password_not_flagged(self):
        assert _scan("f", "https://api.example.com/v1/endpoint") == []

    def test_ip_artifact_not_flagged(self):
        assert _scan("f", "1.2.3.4") == []


# ── _scan: GitHub tokens ────────────────────────────────────────
class TestGithubTokens:
    def test_ghp_personal_token(self):
        token = "ghp_" + "A" * 36
        assert _scan("f", token) != []

    def test_gho_oauth_token(self):
        token = "gho_" + "B" * 36
        assert _scan("f", token) != []

    def test_ghs_server_token(self):
        token = "ghs_" + "C" * 36
        assert _scan("f", token) != []

    def test_category_is_github_token(self):
        token = "ghp_" + "X" * 36
        matches = _scan("f", token)
        assert any(m.category == "github_token" for m in matches)


# ── _scan: Google API keys ──────────────────────────────────────
class TestGoogleApiKey:
    def test_google_key(self):
        key = "AIza" + "A" * 35
        assert _scan("f", key) != []

    def test_category_is_google_credential(self):
        key = "AIza" + "B" * 35
        matches = _scan("f", key)
        assert any(m.category == "google_credential" for m in matches)


# ── _scan: Slack tokens ──────────────────────────────────────────
class TestSlackTokens:
    def test_slack_bot_token(self):
        assert _scan("f", "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOp") != []

    def test_slack_app_token(self):
        assert _scan("f", "xoxa-12345678901234567890") != []

    def test_category_is_slack_token(self):
        matches = _scan("f", "xoxb-12345678901234567890123")
        assert any(m.category == "slack_token" for m in matches)


# ── _scan: Authorization headers ───────────────────────────────
class TestAuthorizationHeader:
    def test_bearer_token(self):
        assert _scan("f", "Authorization: Bearer eyABCDEFGHIJKLMNOP") != []

    def test_basic_auth(self):
        assert _scan("f", "authorization=basic dXNlcjpwYXNzd29yZA==") != []

    def test_category_is_credential(self):
        matches = _scan("f", "Authorization: Bearer abcdefghijklmnop")
        assert any(m.category == "credential" for m in matches)


# ── validate_no_sensitive_data: field attribution ───────────────
class TestFieldAttribution:
    def test_description_field_reported(self):
        matches = validate_no_sensitive_data("password=hunter2xyz", [])
        assert any(m.field == "description" for m in matches)

    def test_artifact_field_reported(self):
        matches = validate_no_sensitive_data("normal alert", ["password=hunter2xyz"])
        assert any("artifacts[0]" in m.field for m in matches)

    def test_multiple_artifacts_correct_index(self):
        matches = validate_no_sensitive_data("ok", ["1.1.1.1", "AKIAIOSFODNN7EXAMPLE"])
        assert any("artifacts[1]" in m.field for m in matches)

    def test_clean_payload_returns_empty(self):
        assert validate_no_sensitive_data(
            "Suspicious login from 1.2.3.4 detected by SIEM",
            ["1.2.3.4", "user@example.com", "d41d8cd98f00b204e9800998ecf8427e"],
        ) == []

    def test_empty_artifacts_returns_empty(self):
        assert validate_no_sensitive_data("Brute force attempt detected", []) == []

    def test_deduplication_same_category_same_field(self):
        # Two password= patterns in the same text should only produce one entry per hint
        matches = _scan("f", "password=abc1234 and password=xyz9876")
        hints = [(m.category, m.hint) for m in matches]
        assert len(hints) == len(set(hints))


# ── Integration: POST /analyze rejects sensitive payloads ───────
class TestAnalyzeEndpointRejectsSensitiveData:
    def test_password_in_description_returns_400(self, app_client):
        res = app_client.post("/analyze", json={
            "source": "SIEM",
            "severity": "HIGH",
            "description": "Login failed: password=SuperSecret99",
            "artifacts": [],
        })
        assert res.status_code == 400
        body = res.get_json()
        assert body["error"] == "sensitive data detected"
        assert isinstance(body["details"], list)
        assert len(body["details"]) > 0
        assert body["schema_url"] == "/schema/alert"

    def test_aws_key_in_artifact_returns_400(self, app_client):
        res = app_client.post("/analyze", json={
            "source": "API",
            "severity": "LOW",
            "description": "Credential leak detected.",
            "artifacts": ["AKIAIOSFODNN7EXAMPLE"],
        })
        assert res.status_code == 400
        body = res.get_json()
        assert body["error"] == "sensitive data detected"
        assert any("artifacts[0]" in d["field"] for d in body["details"])

    def test_pem_key_in_description_returns_400(self, app_client):
        res = app_client.post("/analyze", json={
            "source": "EDR",
            "severity": "HIGH",
            "description": "File contained -----BEGIN RSA PRIVATE KEY----- data",
            "artifacts": [],
        })
        assert res.status_code == 400
        assert res.get_json()["error"] == "sensitive data detected"

    def test_connection_string_in_artifact_returns_400(self, app_client):
        res = app_client.post("/analyze", json={
            "source": "SIEM",
            "severity": "MEDIUM",
            "description": "Exfiltration attempt detected.",
            "artifacts": ["postgresql://admin:s3cr3t@db.internal/prod"],
        })
        assert res.status_code == 400

    def test_clean_payload_still_accepted(self, app_client):
        res = app_client.post("/analyze", json={
            "source": "SIEM",
            "severity": "HIGH",
            "description": "Brute force attack detected from external IP.",
            "artifacts": ["1.2.3.4", "attacker@evil.com"],
        })
        assert res.status_code == 202

    def test_response_does_not_echo_secret_value(self, app_client):
        secret = "MySuperSecretPassword99"
        res = app_client.post("/analyze", json={
            "source": "API",
            "severity": "LOW",
            "description": f"password={secret}",
            "artifacts": [],
        })
        assert res.status_code == 400
        body_text = res.get_data(as_text=True)
        assert secret not in body_text


@pytest.fixture
def app_client(monkeypatch):
    import db
    import sqlalchemy
    import app as app_module
    from app import app
    from db import SessionLocal, init_db
    import llm_service

    original_engine = db.engine
    import tempfile, pathlib
    db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"
    engine = sqlalchemy.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    monkeypatch.setattr(db, "engine", engine)
    SessionLocal.configure(bind=engine)
    monkeypatch.setattr(app_module, "start_worker", lambda: None)
    monkeypatch.setattr(llm_service, "generate_analysis", lambda d: {
        "risk_assessment": "LOW", "summary": "test", "recommended_actions": [], "confidence": 0.5,
    })
    init_db()
    try:
        yield app.test_client()
    finally:
        SessionLocal.configure(bind=original_engine)
        engine.dispose()
        if db_path.exists():
            db_path.unlink(missing_ok=True)
