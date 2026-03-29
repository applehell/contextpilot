"""Tests for the secret detector."""
from __future__ import annotations

import pytest

from src.core.secrets import SecretDetector, SensitivityReport


@pytest.fixture
def detector():
    return SecretDetector()


class TestDetectPatterns:
    def test_no_secrets(self, detector):
        report = detector.scan("This is a normal text about Python programming.")
        assert not report.is_sensitive
        assert report.max_severity == "none"

    def test_password_assignment(self, detector):
        report = detector.scan('password = "SuperSecret123"')
        assert report.is_sensitive
        assert report.max_severity == "critical"
        assert any(f.pattern_name == "password_assignment" for f in report.findings)

    def test_api_key(self, detector):
        report = detector.scan('api_key: ABCDEF1234567890ABCDEF')
        assert report.is_sensitive
        assert any(f.pattern_name == "api_key" for f in report.findings)

    def test_bearer_token(self, detector):
        report = detector.scan('Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig')
        assert report.is_sensitive
        assert any(f.pattern_name == "bearer_token" for f in report.findings)

    def test_private_key(self, detector):
        report = detector.scan("-----BEGIN RSA PRIVATE KEY-----\nMIIEowI...")
        assert report.max_severity == "critical"
        assert any(f.pattern_name == "private_key" for f in report.findings)

    def test_connection_string(self, detector):
        report = detector.scan("postgres://user:pass123@db.example.com:5432/mydb")
        assert report.is_sensitive
        assert report.max_severity == "critical"

    def test_wifi_password(self, detector):
        report = detector.scan("WLAN Passwort: MyWiFiPass123")
        assert report.is_sensitive
        assert any(f.pattern_name == "wifi_password" for f in report.findings)

    def test_private_ip(self, detector):
        report = detector.scan("Server at 192.168.1.78")
        assert report.is_sensitive
        assert any(f.pattern_name == "private_ip" for f in report.findings)
        assert report.max_severity == "low"

    def test_email(self, detector):
        report = detector.scan("Contact: user@example.com")
        assert any(f.pattern_name == "email_address" for f in report.findings)

    def test_github_token(self, detector):
        report = detector.scan("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij1234")
        assert report.is_sensitive
        assert any(f.pattern_name == "github_token" for f in report.findings)

    def test_aws_key(self, detector):
        report = detector.scan("AKIAIOSFODNN7EXAMPLE")
        assert any(f.pattern_name == "aws_key" for f in report.findings)

    def test_inline_credential(self, detector):
        report = detector.scan("http://admin:secret123@myhost.local/api")
        assert any(f.pattern_name == "inline_credential" for f in report.findings)

    def test_multiple_findings(self, detector):
        text = 'password = "test123"\napi_key: ABCDEF1234567890ABCDEF\n192.168.1.1'
        report = detector.scan(text)
        assert len(report.findings) >= 3
        assert report.max_severity == "critical"


class TestRedact:
    def test_redact_password(self, detector):
        text = 'password = "SuperSecret123"'
        result = detector.redact(text)
        assert "SuperSecret123" not in result
        assert "[REDACTED:" in result

    def test_redact_preserves_low(self, detector):
        text = "Server at <server-ip>"
        result = detector.redact(text)
        assert "<server-ip>" in result  # low severity not redacted

    def test_redact_connection_string(self, detector):
        text = "postgres://admin:s3cret@db.local:5432/mydb"
        result = detector.redact(text)
        assert "s3cret" not in result


class TestClassifyMemory:
    def test_clean_memory(self, detector):
        sev = detector.classify_memory("note", "Just a note about cooking", [])
        assert sev == "none"

    def test_sensitive_memory(self, detector):
        sev = detector.classify_memory("creds", 'password = "abc123xyz"', ["auth"])
        assert sev in ("critical", "high")


class TestSensitivityReport:
    def test_empty_report(self):
        r = SensitivityReport()
        assert not r.is_sensitive
        assert r.max_severity == "none"
        assert r.severity_counts == {}

    def test_counts(self):
        from src.core.secrets import SecretFinding
        r = SensitivityReport(findings=[
            SecretFinding("a", "critical", "x"),
            SecretFinding("b", "high", "y"),
            SecretFinding("c", "high", "z"),
        ])
        assert r.severity_counts == {"critical": 1, "high": 2}
        assert r.max_severity == "critical"
