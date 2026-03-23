"""Secret detector — identifies sensitive content in memories."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class SecretFinding:
    pattern_name: str
    severity: str  # "critical", "high", "medium", "low"
    matched_text: str
    line_number: int = 0


@dataclass
class SensitivityReport:
    findings: List[SecretFinding] = field(default_factory=list)

    @property
    def is_sensitive(self) -> bool:
        return len(self.findings) > 0

    @property
    def max_severity(self) -> str:
        if not self.findings:
            return "none"
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return min(self.findings, key=lambda f: order.get(f.severity, 99)).severity

    @property
    def severity_counts(self) -> dict:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return {k: v for k, v in counts.items() if v > 0}


# (pattern_name, severity, regex)
_PATTERNS: List[Tuple[str, str, re.Pattern]] = [
    # Critical: private keys, full credentials
    ("private_key", "critical", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE)),
    ("password_assignment", "critical", re.compile(
        r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{6,}", re.IGNORECASE)),
    ("connection_string", "critical", re.compile(
        r"(?:postgres|mysql|mongodb|redis|amqp)://[^\s]+:[^\s]+@[^\s]+", re.IGNORECASE)),

    # High: API keys, tokens, secrets
    ("api_key", "high", re.compile(
        r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}", re.IGNORECASE)),
    ("bearer_token", "high", re.compile(
        r"(?:Bearer|token|auth)\s+[A-Za-z0-9_\-.]{20,}", re.IGNORECASE)),
    ("long_lived_token", "high", re.compile(
        r"(?:access.token|long.lived.token|ha_token)\s*[:=]\s*['\"]?eyJ[A-Za-z0-9_\-]+", re.IGNORECASE)),
    ("generic_secret", "high", re.compile(
        r"(?:secret|SECRET|client_secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}", re.IGNORECASE)),
    ("aws_key", "high", re.compile(
        r"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    ("github_token", "high", re.compile(
        r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}")),

    # Medium: WiFi passwords, credentials in URLs, env vars
    ("wifi_password", "medium", re.compile(
        r"(?:wlan|wifi|ssid|network)\s*(?:passwort|password|pwd|key)\s*[:=]\s*['\"]?[^\s'\"]{4,}", re.IGNORECASE)),
    ("inline_credential", "medium", re.compile(
        r"://[^/\s:]+:[^@/\s]{4,}@", re.IGNORECASE)),
    ("env_secret", "medium", re.compile(
        r"(?:export\s+)?[A-Z_]{3,}(?:_KEY|_SECRET|_TOKEN|_PASSWORD|_PASS)\s*=\s*['\"]?[^\s'\"]{4,}")),
    ("basic_auth", "medium", re.compile(
        r"(?:Authorization|auth):\s*Basic\s+[A-Za-z0-9+/=]{10,}", re.IGNORECASE)),
    ("hex_secret", "medium", re.compile(
        r"(?:key|token|secret|pass)\s*[:=]\s*['\"]?[0-9a-fA-F]{32,}['\"]?", re.IGNORECASE)),

    # Low: IP addresses, email addresses (potentially PII)
    ("private_ip", "low", re.compile(
        r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
    ("email_address", "low", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    ("phone_number", "low", re.compile(
        r"\+?\d{2,4}[\s\-]?\d{3,5}[\s\-]?\d{4,8}")),
]


class SecretDetector:
    """Scans text for secrets, credentials, and sensitive information."""

    def scan(self, text: str) -> SensitivityReport:
        findings = []
        lines = text.splitlines()
        for line_num, line in enumerate(lines, 1):
            for name, severity, pattern in _PATTERNS:
                for match in pattern.finditer(line):
                    matched = match.group(0)
                    # Redact the actual secret value for the finding
                    if len(matched) > 20:
                        redacted = matched[:8] + "..." + matched[-4:]
                    else:
                        redacted = matched[:6] + "..."
                    findings.append(SecretFinding(
                        pattern_name=name,
                        severity=severity,
                        matched_text=redacted,
                        line_number=line_num,
                    ))
        return SensitivityReport(findings=findings)

    def redact(self, text: str) -> str:
        result = text
        for name, severity, pattern in _PATTERNS:
            if severity in ("critical", "high"):
                result = pattern.sub(f"[REDACTED:{name}]", result)
        return result

    def classify_memory(self, key: str, value: str, tags: list) -> str:
        """Returns severity level: 'critical', 'high', 'medium', 'low', or 'none'."""
        report = self.scan(f"{key}\n{value}\n{' '.join(tags)}")
        return report.max_severity
