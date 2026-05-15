import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SensitiveMatch:
    field: str
    category: str
    hint: str


# Credential key names that unambiguously identify a secret when followed by =value or :value
_CRED_KEYS = (
    r"password|passwd|pwd|"
    r"secret|secret_key|client_secret|consumer_secret|"
    r"api[_\-]?key|apikey|api[_\-]?secret|"
    r"token|access_token|auth_token|refresh_token|id_token|"
    r"session_key|session_token|master_key|encryption_key|"
    r"private_key|signing_key"
)

# Each entry: (compiled regex, category, human-readable hint)
_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # key = value  or  key: value  (requires a non-trivial value of at least 4 chars)
    (
        re.compile(rf"(?i)\b(?:{_CRED_KEYS})\s*[=:]\s*(?!\s)\S{{4,}}"),
        "credential",
        "credential key-value pair (e.g. password=..., token=...)",
    ),
    # PEM private key block header
    (
        re.compile(r"-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----"),
        "private_key",
        "PEM private key block",
    ),
    # AWS IAM access key ID (format is fixed: AKIA/AGPA/… + 16 uppercase alphanumeric)
    (
        re.compile(r"\b(?:AKIA|AGPA|AIPA|ANPA|ANVA|AROA|ASCA|ASIA)[0-9A-Z]{16}\b"),
        "aws_credential",
        "AWS access key ID",
    ),
    # AWS secret access key assignment
    (
        re.compile(r"(?i)aws[_\-]?(?:secret[_\-]?)?access[_\-]?key\s*[=:]\s*\S{20,}"),
        "aws_credential",
        "AWS secret access key assignment",
    ),
    # Connection string with embedded credentials:  scheme://user:pass@host
    (
        re.compile(r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^:@/\s]{0,64}:[^@\s]{3,}@"),
        "connection_string",
        "connection string with embedded credentials (scheme://user:pass@host)",
    ),
    # GitHub tokens (personal, OAuth, server-to-server, fine-grained)
    (
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
        "github_token",
        "GitHub token (ghp_/gho_/ghu_/ghs_/ghr_)",
    ),
    # Google API key
    (
        re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
        "google_credential",
        "Google API key (AIza...)",
    ),
    # Slack API tokens
    (
        re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,255}\b"),
        "slack_token",
        "Slack API token (xox...)",
    ),
    # Authorization header with an inline credential value
    (
        re.compile(r"(?i)\bauthorization\s*[=:]\s*(?:bearer|basic|token)\s+\S{8,}"),
        "credential",
        "Authorization header with inline credential",
    ),
]


def _scan(field: str, text: str) -> list[SensitiveMatch]:
    """Return one SensitiveMatch per distinct (category, hint) found in text."""
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    matches: list[SensitiveMatch] = []
    for pattern, category, hint in _PATTERNS:
        key = (category, hint)
        if key not in seen and pattern.search(text):
            seen.add(key)
            matches.append(SensitiveMatch(field=field, category=category, hint=hint))
    return matches


def validate_no_sensitive_data(description: str, artifacts: list[str]) -> list[SensitiveMatch]:
    """Check description and every artifact for sensitive data patterns.

    Returns a list of matches (empty means clean). The matched value itself is
    never included in the result to avoid logging the secret.
    """
    issues = _scan("description", description)
    for i, artifact in enumerate(artifacts):
        issues.extend(_scan(f"artifacts[{i}]", str(artifact)))
    return issues
