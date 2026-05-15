import pytest

import llm_service
from llm_service import (
    _build_user_message,
    _normalize_response,
    _parse_json_safe,
    generate_analysis,
)


# ── _build_user_message ─────────────────────────────────────────
def test_build_user_message_includes_all_fields():
    alert = {
        "alert_id": "42",
        "source": "SIEM",
        "severity": "HIGH",
        "description": "Suspicious login from external IP.",
        "artifacts": ["1.2.3.4", "user@example.com"],
    }
    msg = _build_user_message(alert)

    assert "ID: 42" in msg
    assert "Source: SIEM" in msg
    assert "Severity: HIGH" in msg
    assert "Description: Suspicious login from external IP." in msg
    assert "Artifacts: 1.2.3.4, user@example.com" in msg
    assert "valid JSON" in msg


def test_build_user_message_handles_empty_artifacts():
    alert = {
        "alert_id": "7",
        "source": "EDR",
        "severity": "LOW",
        "description": "Routine scan.",
        "artifacts": [],
    }
    msg = _build_user_message(alert)
    assert "Artifacts: \n" in msg or "Artifacts: " in msg


def test_build_user_message_missing_artifacts_key_defaults_to_empty():
    alert = {
        "alert_id": "1",
        "source": "API",
        "severity": "MEDIUM",
        "description": "Hello.",
    }
    msg = _build_user_message(alert)
    assert "Artifacts:" in msg


# ── _normalize_response ─────────────────────────────────────────
def test_normalize_response_strips_markdown_fences():
    raw = '```json\n{"risk_assessment": "HIGH", "summary": "x"}\n```'
    assert _normalize_response(raw) == '{"risk_assessment": "HIGH", "summary": "x"}'


def test_normalize_response_strips_leading_and_trailing_prose():
    raw = 'Sure! Here is the analysis:\n{"risk_assessment":"LOW"}\nLet me know.'
    assert _normalize_response(raw) == '{"risk_assessment":"LOW"}'


def test_normalize_response_handles_multiline_json():
    raw = 'noise\n{\n  "a": 1,\n  "b": 2\n}\n trailing'
    out = _normalize_response(raw)
    assert out.startswith("{") and out.endswith("}")
    assert '"a": 1' in out
    assert '"b": 2' in out


def test_normalize_response_empty_string_returns_empty():
    assert _normalize_response("") == ""
    assert _normalize_response(None) == ""


def test_normalize_response_no_braces_returns_stripped_original():
    assert _normalize_response("  no JSON here  ") == "no JSON here"


# ── _parse_json_safe ────────────────────────────────────────────
def test_parse_json_safe_returns_dict_for_valid_json():
    result = _parse_json_safe('{"risk_assessment": "HIGH", "confidence": 0.9}')
    assert result == {"risk_assessment": "HIGH", "confidence": 0.9}


def test_parse_json_safe_falls_back_to_single_quotes():
    result = _parse_json_safe("{'risk_assessment': 'LOW'}")
    assert result == {"risk_assessment": "LOW"}


def test_parse_json_safe_returns_none_for_garbage():
    assert _parse_json_safe("this is not JSON") is None


def test_parse_json_safe_returns_none_for_empty_string():
    assert _parse_json_safe("") is None


# ── _attempt_analysis (via monkeypatching the LLM) ──────────────
def test_attempt_analysis_returns_parsed_dict(monkeypatch):
    class FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            return type("FakeMsg", (), {
                "content": '{"risk_assessment": "MEDIUM", "summary": "ok", "confidence": 0.7}'
            })()

    class FakeParser:
        def invoke(self, response):
            return response.content

    monkeypatch.setattr(llm_service, "ChatOllama", FakeLLM)
    monkeypatch.setattr(llm_service, "StrOutputParser", lambda: FakeParser())

    alert = {
        "alert_id": "1",
        "source": "SIEM",
        "severity": "MEDIUM",
        "description": "Test alert.",
        "artifacts": ["1.1.1.1"],
    }
    result = llm_service._attempt_analysis(alert)
    assert result["risk_assessment"] == "MEDIUM"
    assert result["summary"] == "ok"
    assert result["confidence"] == 0.7
    assert result["recommended_actions"] == []  # default applied


def test_attempt_analysis_applies_default_confidence(monkeypatch):
    class FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            return type("FakeMsg", (), {
                "content": '{"risk_assessment": "LOW", "summary": "ok", "recommended_actions": ["a"]}'
            })()

    class FakeParser:
        def invoke(self, response):
            return response.content

    monkeypatch.setattr(llm_service, "ChatOllama", FakeLLM)
    monkeypatch.setattr(llm_service, "StrOutputParser", lambda: FakeParser())

    result = llm_service._attempt_analysis({
        "alert_id": "1", "source": "SIEM", "severity": "LOW",
        "description": "x", "artifacts": [],
    })
    assert result["confidence"] == 0.0  # default applied
    assert result["recommended_actions"] == ["a"]


def test_attempt_analysis_raises_on_non_dict_payload(monkeypatch):
    class FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            return type("FakeMsg", (), {"content": "this is not JSON at all"})()

    class FakeParser:
        def invoke(self, response):
            return response.content

    monkeypatch.setattr(llm_service, "ChatOllama", FakeLLM)
    monkeypatch.setattr(llm_service, "StrOutputParser", lambda: FakeParser())

    with pytest.raises(ValueError, match="invalid JSON"):
        llm_service._attempt_analysis({
            "alert_id": "1", "source": "SIEM", "severity": "LOW",
            "description": "x", "artifacts": [],
        })


# ── generate_analysis (retry + fallback) ────────────────────────
def test_generate_analysis_returns_first_successful_attempt(monkeypatch):
    invoke_count = {"n": 0}

    class FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            invoke_count["n"] += 1
            return type("R", (), {
                "content": '{"risk_assessment": "HIGH", "summary": "x", "recommended_actions": [], "confidence": 0.8}'
            })()

    class FakeParser:
        def invoke(self, response):
            return response.content

    monkeypatch.setattr(llm_service, "ChatOllama", FakeLLM)
    monkeypatch.setattr(llm_service, "StrOutputParser", FakeParser)
    monkeypatch.setattr(llm_service, "_rate_limit", lambda: None)

    result = generate_analysis({"alert_id": "1", "source": "SIEM", "severity": "HIGH", "description": "x", "artifacts": []})
    assert result["risk_assessment"] == "HIGH"
    assert "_failed" not in result
    assert invoke_count["n"] == 1


def test_generate_analysis_retries_then_falls_back(monkeypatch):
    invoke_count = {"n": 0}

    class FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            invoke_count["n"] += 1
            raise RuntimeError("LLM unreachable")

    class FakeParser:
        def invoke(self, response):
            return response.content

    monkeypatch.setattr(llm_service, "ChatOllama", FakeLLM)
    monkeypatch.setattr(llm_service, "StrOutputParser", FakeParser)
    monkeypatch.setattr(llm_service, "_rate_limit", lambda: None)

    result = generate_analysis({"alert_id": "1", "source": "SIEM", "severity": "HIGH", "description": "x", "artifacts": []})
    assert invoke_count["n"] == llm_service.MAX_RETRIES
    assert result["_failed"] is True
    assert result["risk_assessment"] == "ERROR"
    assert result["confidence"] == 0.0
    assert "LLM unreachable" in result["error"]
    assert isinstance(result["recommended_actions"], list)
    assert len(result["recommended_actions"]) > 0


def test_generate_analysis_recovers_after_transient_failure(monkeypatch):
    invoke_count = {"n": 0}

    class FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            invoke_count["n"] += 1
            if invoke_count["n"] < 2:
                raise RuntimeError("transient blip")
            return type("R", (), {
                "content": '{"risk_assessment": "LOW", "summary": "calm", "recommended_actions": [], "confidence": 0.6}'
            })()

    class FakeParser:
        def invoke(self, response):
            return response.content

    monkeypatch.setattr(llm_service, "ChatOllama", FakeLLM)
    monkeypatch.setattr(llm_service, "StrOutputParser", FakeParser)
    monkeypatch.setattr(llm_service, "_rate_limit", lambda: None)

    result = generate_analysis({"alert_id": "1", "source": "EDR", "severity": "LOW", "description": "x", "artifacts": []})
    assert invoke_count["n"] == 2
    assert result["risk_assessment"] == "LOW"
    assert "_failed" not in result


# ── Ollama unavailable (real network call, no mocks on ChatOllama) ──────────
def test_ollama_service_is_reachable():
    """Checks whether Ollama is online at the configured OLLAMA_URL."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(llm_service.OLLAMA_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434

    try:
        with socket.create_connection((host, port), timeout=3):
            reachable = True
    except OSError:
        reachable = False

    assert reachable, f"Ollama is not reachable at {llm_service.OLLAMA_URL}"


# ── rate limiter sanity check ───────────────────────────────────
def test_rate_limit_resets_counter_after_one_minute(monkeypatch):
    fake_now = {"t": 1_000_000.0}

    def fake_time():
        return fake_now["t"]

    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(llm_service, "OLLAMA_RATE_LIMIT", 3)
    monkeypatch.setattr("time.time", fake_time)
    monkeypatch.setattr("time.sleep", fake_sleep)
    llm_service._last_request_timestamp = 0
    llm_service._request_count = 0

    for _ in range(3):
        llm_service._rate_limit()
    assert sleeps == []  # within limit

    llm_service._rate_limit()
    assert sleeps == [1]  # 4th call triggers throttle

    fake_now["t"] += 61
    llm_service._rate_limit()
    assert llm_service._request_count == 1  # counter reset
