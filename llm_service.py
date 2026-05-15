import json
import re
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama import ChatOllama
from pydantic import ValidationError

from config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_RATE_LIMIT, MAX_RETRIES

SYSTEM_PROMPT = """\
You are a senior SOC/DFIR analyst specialized in security incident analysis, \
alert triage, IOC (Indicators of Compromise) investigation, and cyber risk assessment.

Your role is to analyze alerts received from security tools such as SIEM, EDR, \
threat intelligence APIs, and internal systems.

OBJECTIVE:
Perform a preliminary, technical, and objective analysis of the received alert, \
identifying possible risk, impact, suspicious indicators, and immediate recommended actions.

IMPORTANT RULES:
- Respond ONLY with valid JSON.
- DO NOT use markdown.
- DO NOT explain your answer outside the JSON.
- DO NOT include additional text.
- DO NOT invent information not present in the context.
- If data is sparse, reduce the confidence level.
- If risk cannot be reasonably inferred, state so explicitly in the summary.
- Be conservative to avoid false positives.
- Follow SOC and DFIR best practices.
- The "confidence" field must be between 0.0 and 1.0.

ANALYSIS CRITERIA:
Original severity, source type (SIEM/EDR/API), suspicious indicators, known IOCs, \
operational impact, compromise, persistence, lateral movement, exfiltration, \
malicious execution, phishing, malware, C2, recurring IOCs.

ARTIFACTS — analyze IPs, hashes, emails, and domains for suspicious behavior, \
reputation, and malicious patterns.

Also evaluate whether the alert makes contextual sense (e.g., an internal IP on a \
reputation list may be a false positive).

REQUIRED RESPONSE FORMAT (no extra text outside the JSON):
{
  "risk_assessment": "LOW/MEDIUM/HIGH",
  "summary": "short one-sentence summary of the alert",
  "recommended_actions": ["concrete and clear actions, it's obrigatory to give at least one"],
  "confidence": 0.0
}

Field explanations:
  "risk_assessment" = How elevated you believe this alert is, based on the criteria \
and artifacts. Use LOW for likely false positives or low-risk alerts, MEDIUM for \
alerts with risk indicators but not conclusive, and HIGH for alerts with strong \
evidence of risk or compromise.
  "summary" = A short sentence capturing the essence of the alert, highlighting the \
most relevant and suspicious points. Be objective and direct.
  "recommended_actions" = A list of concrete, actionable items a SOC/DFIR analyst \
could take to investigate or mitigate the alert. Examples: "Check host X logs", \
"Block IP Y", "Detonate hash Z in sandbox".
  "confidence" = A numeric value between 0.0 and 1.0 representing how confident the model is in its own analysis and conclusions, NOT how severe or malicious the alert is.
Use HIGH confidence when the available evidence is clear, consistent, and sufficient to support the assessment — including cases where the alert appears benign or low risk.
Use LOW confidence only when:the data is incomplete,ambiguous,contradictory,insufficient for reliable analysis,or when multiple interpretations are possible.
Do NOT lower confidence simply because the alert is harmless or lacks malicious indicators. If the model can confidently determine that the activity is benign or low risk, the confidence should still be high.
"""


def _build_user_message(alert_data: dict[str, Any]) -> str:
    artifacts = ", ".join(alert_data.get("artifacts", []))
    return (
        "Analyze the following security alert and respond ONLY with valid JSON:\n\n"
        f"ID: {alert_data['alert_id']}\n"
        f"Source: {alert_data['source']}\n"
        f"Severity: {alert_data['severity']}\n"
        f"Description: {alert_data['description']}\n"
        f"Artifacts: {artifacts}\n\n"
        'Required JSON keys: "risk_assessment" (LOW/MEDIUM/HIGH), '
        '"summary", "recommended_actions" (list), and "confidence" (0.0 to 1.0).'
    )


def _normalize_response(raw_text: str) -> str:
    if not raw_text:
        return ""
    raw_text = raw_text.strip()
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    return match.group(0) if match else raw_text


def _parse_json_safe(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(text.strip().replace("'", '"'))
        except json.JSONDecodeError:
            return None


_last_request_timestamp: float = 0
_request_count: int = 0


def _rate_limit() -> None:
    global _last_request_timestamp, _request_count
    from time import time, sleep

    now = time()
    if now - _last_request_timestamp > 60:
        _request_count = 0
        _last_request_timestamp = now
    _request_count += 1
    if _request_count > OLLAMA_RATE_LIMIT:
        sleep(1)


def _attempt_analysis(alert_data: dict[str, Any]) -> dict[str, Any]:
    from models import AnalysisResult

    llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_URL, request_timeout=OLLAMA_TIMEOUT)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=_build_user_message(alert_data)),
    ]
    raw_text = StrOutputParser().invoke(llm.invoke(messages))
    parsed = _parse_json_safe(_normalize_response(raw_text))
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM returned invalid JSON: {raw_text[:300]}")
    parsed.setdefault("recommended_actions", [])
    parsed.setdefault("confidence", 0.0)
    try:
        AnalysisResult.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"LLM response failed schema validation: {exc}") from exc
    return parsed


def generate_analysis(alert_data: dict[str, Any]) -> dict[str, Any]:
    last_exc: Exception | None = None
    for _ in range(MAX_RETRIES):
        _rate_limit()
        try:
            return _attempt_analysis(alert_data)
        except Exception as exc:
            last_exc = exc

    return {
        "_failed": True,
        "risk_assessment": "ERROR",
        "summary": "Analysis failed after multiple attempts. Manual review required.",
        "recommended_actions": ["Review the alert in the dashboard", "Check sources and artifacts"],
        "confidence": 0.0,
        "error": str(last_exc),
    }
