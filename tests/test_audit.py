"""
test_audit.py — Tests for dicom_audit.py

Verifies the three audit checks:
1. Standard tag verification — PASSED when clean, FAILED when PHI remains
2. Private tag scanning — NEEDS_REVIEW when suspicious value found
3. Scout detection — flags LOCALIZER series and low-slice-count series
"""

import pytest
from pathlib import Path

from dicom.dicom_anonymize import anonymize_series
from dicom.dicom_audit import (
    audit_series,
    audit_patient,
    _check_standard_tags,
    _scan_private_tags,
    _detect_scout,
)


class TestStandardTagCheck:

    def test_clean_series_passes(self, anonymized_series_dir):
        failures = _check_standard_tags(anonymized_series_dir, set())
        assert failures == []

    def test_scrubbed_series_has_no_tag_failures(self, anonymized_series_dir):
        from dicom.dicom_anonymize import load_sensitive_fields
        sensitive = load_sensitive_fields()
        failures = _check_standard_tags(anonymized_series_dir, sensitive)
        assert failures == [], (
            f"Expected no failures after anonymization, got: {failures}"
        )

    def test_unscrubbed_series_fails(self, dicom_series_dir):
        """Raw (un-anonymized) series should produce failures for PHI tags."""
        from dicom.dicom_anonymize import load_sensitive_fields
        sensitive = load_sensitive_fields()
        failures = _check_standard_tags(dicom_series_dir, sensitive)
        tag_names = [f.tag for f in failures]
        assert "PatientName" in tag_names
        assert "PatientID"   in tag_names

    def test_failure_reports_correct_value(self, dicom_series_dir):
        from dicom.dicom_anonymize import load_sensitive_fields
        sensitive = load_sensitive_fields()
        failures = _check_standard_tags(dicom_series_dir, sensitive)
        name_failures = [f for f in failures if f.tag == "PatientName"]
        assert any("Smith" in f.value for f in name_failures)


class TestPrivateTagScan:

    def test_no_flags_on_clean_series(self, anonymized_series_dir):
        flags = _scan_private_tags(anonymized_series_dir)
        assert flags == []

    def test_name_in_private_tag_flagged(self, private_tag_series_dir):
        flags = _scan_private_tags(private_tag_series_dir)
        assert len(flags) >= 1
        assert any("name" in f.reason.lower() for f in flags)

    def test_flag_contains_tag_code(self, private_tag_series_dir):
        flags = _scan_private_tags(private_tag_series_dir)
        assert any("0009" in f.tag for f in flags)


class TestScoutDetection:

    def test_normal_series_not_flagged(self, anonymized_series_dir):
        is_scout, reason, count = _detect_scout(anonymized_series_dir)
        assert not is_scout
        assert count == 10

    def test_localizer_image_type_flagged(self, scout_series_dir):
        is_scout, reason, count = _detect_scout(scout_series_dir)
        assert is_scout
        assert "LOCALIZER" in reason.upper()

    def test_low_slice_count_flagged(self, tmp_path):
        from conftest import _make_dicom
        series_dir = tmp_path / "tiny"
        series_dir.mkdir()
        for i in range(2):
            _make_dicom(series_dir / f"IM{i:03d}")
        is_scout, reason, count = _detect_scout(series_dir)
        assert is_scout
        assert count == 2


class TestAuditSeries:

    def test_passed_on_clean_series(self, anonymized_series_dir):
        result = audit_series(anonymized_series_dir, "SE000001")
        assert result.passed
        assert not result.tag_failures

    def test_failed_on_raw_series(self, dicom_series_dir):
        result = audit_series(dicom_series_dir, "SE000001")
        assert not result.passed
        assert len(result.tag_failures) > 0

    def test_needs_review_on_scout(self, scout_series_dir):
        anonymize_series(scout_series_dir)
        result = audit_series(scout_series_dir, "SE_SCOUT")
        assert result.passed        # tags are clean
        assert result.needs_review  # but it's a scout
        assert result.is_scout


class TestAuditPatient:

    def test_passed_status_all_clean(self, anonymized_series_dir):
        report = audit_patient(
            [(anonymized_series_dir, "SE000001")], "PA000001"
        )
        assert report.status == "PASSED"

    def test_failed_status_raw_series(self, dicom_series_dir):
        report = audit_patient(
            [(dicom_series_dir, "SE000001")], "PA000001"
        )
        assert report.status == "FAILED"

    def test_needs_review_status_scout(self, scout_series_dir):
        anonymize_series(scout_series_dir)
        report = audit_patient(
            [(scout_series_dir, "SE_SCOUT")], "PA000002"
        )
        assert report.status == "NEEDS_REVIEW"

    def test_failed_if_any_series_fails(self, anonymized_series_dir, tmp_path):
        """One clean + one raw series → overall FAILED."""
        from conftest import _make_dicom
        raw_dir = tmp_path / "SE000002_raw"
        raw_dir.mkdir()
        for i in range(10):
            _make_dicom(raw_dir / f"IM{i:03d}")
        report = audit_patient(
            [
                (anonymized_series_dir, "SE000001"),
                (raw_dir,              "SE000002"),
            ],
            "PA000003",
        )
        assert report.status == "FAILED"
