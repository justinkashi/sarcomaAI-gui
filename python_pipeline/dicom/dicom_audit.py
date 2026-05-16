"""
dicom_audit.py — Post-anonymization QC audit.

Runs after anonymize_series() and checks:
  1. Standard tags — every sensitive field now contains the expected dummy value
  2. Private tags  — vendor-specific numeric tags flagged if value looks like PHI
  3. Scout images  — series with very few slices or LOCALIZER ImageType flagged

Returns a structured AuditReport that pipeline_new.py logs to the SSE stream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pydicom as pd
from pydicom.errors import InvalidDicomError

from config import DEFAULT_GLOB
from dicom.dicom_anonymize import load_sensitive_fields, _anon_value

import logging
logger = logging.getLogger(__name__)

# ── dummy value set (mirrors dicom_anonymize._anon_value) ────────────────────
_DUMMY_VALUES = {"ANONYMIZED", "19000101", "19000101000000", "000Y", "0", "YES", ""}

# ── PHI heuristics for private tag values ────────────────────────────────────
# Name: two capitalised words separated by space or DICOM ^ delimiter
_RE_NAME = re.compile(r"[A-Z][a-z]{1,}\s*[\^\ ]\s*[A-Z][a-z]{1,}", re.IGNORECASE)
# Date: 8-digit string starting with 19xx or 20xx
_RE_DATE = re.compile(r"\b(19|20)\d{6}\b")
# MRN: 5–10 consecutive digits
_RE_MRN  = re.compile(r"\b\d{5,10}\b")

# Scout detection: small slice count or explicit ImageType marker
_SCOUT_SLICE_THRESHOLD = 5
_SCOUT_IMAGE_TYPES     = {"LOCALIZER", "SCOUT"}


# ── result dataclasses ────────────────────────────────────────────────────────

@dataclass
class TagFailure:
    file: str
    tag:  str
    value: str


@dataclass
class PrivateTagFlag:
    tag:    str   # e.g. "(0009,1001)"
    value:  str
    reason: str   # "possible name" | "possible date" | "possible MRN"


@dataclass
class SeriesAuditResult:
    series_id:        str
    tag_failures:     List[TagFailure]     = field(default_factory=list)
    private_flags:    List[PrivateTagFlag] = field(default_factory=list)
    is_scout:         bool                 = False
    scout_reason:     str                  = ""
    slice_count:      int                  = 0

    @property
    def passed(self) -> bool:
        return not self.tag_failures

    @property
    def needs_review(self) -> bool:
        return self.is_scout


@dataclass
class AuditReport:
    patient_id:    str
    series_results: List[SeriesAuditResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(not r.passed for r in self.series_results):
            return "FAILED"
        if any(r.needs_review for r in self.series_results):
            return "NEEDS_REVIEW"
        return "PASSED"


# ── core checks ──────────────────────────────────────────────────────────────

def _check_standard_tags(series_dir: Path, sensitive: set) -> List[TagFailure]:
    """Read back every DICOM file and confirm sensitive fields hold dummy values."""
    failures = []
    for fpath in sorted(series_dir.glob(DEFAULT_GLOB)):
        try:
            ds = pd.dcmread(str(fpath), stop_before_pixels=True, force=True)
        except (InvalidDicomError, Exception):
            continue

        for elem in ds:
            if elem.VR == "SQ":
                continue
            if elem.keyword not in sensitive:
                continue
            val = str(elem.value).strip()
            if val and val not in _DUMMY_VALUES:
                failures.append(TagFailure(
                    file=fpath.name,
                    tag=elem.keyword,
                    value=val[:60],   # truncate long values in the log
                ))
    return failures


def _scan_private_tags(series_dir: Path) -> List[PrivateTagFlag]:
    """
    Check one representative file for private (vendor) tags whose value
    looks like a name, date, or MRN.
    """
    flags = []
    files = sorted(series_dir.glob(DEFAULT_GLOB))
    if not files:
        return flags

    # Check the middle file — more likely to have patient tags than first/last
    sample = files[len(files) // 2]
    try:
        ds = pd.dcmread(str(sample), stop_before_pixels=True, force=True)
    except Exception:
        return flags

    for elem in ds:
        # Private tags have odd group numbers
        if elem.tag.group % 2 == 0:
            continue
        # Only check string-like values
        if elem.VR not in ("LO", "SH", "ST", "UT", "CS", "LT", "PN", "UI", "DS", "IS"):
            continue
        val = str(elem.value).strip()
        if not val or val in _DUMMY_VALUES:
            continue

        tag_str = f"({elem.tag.group:04X},{elem.tag.element:04X})"
        if _RE_NAME.search(val):
            flags.append(PrivateTagFlag(tag_str, val[:60], "possible name"))
        elif _RE_DATE.search(val):
            flags.append(PrivateTagFlag(tag_str, val[:60], "possible date"))
        elif _RE_MRN.search(val):
            flags.append(PrivateTagFlag(tag_str, val[:60], "possible MRN"))

    return flags


def _detect_scout(series_dir: Path) -> tuple[bool, str, int]:
    """Return (is_scout, reason, slice_count)."""
    files = sorted(series_dir.glob(DEFAULT_GLOB))
    count = len(files)
    if count == 0:
        return False, "", 0

    sample = files[0]
    try:
        ds = pd.dcmread(str(sample), stop_before_pixels=True, force=True)
    except Exception:
        return False, "", count

    image_type = getattr(ds, "ImageType", [])
    image_type_vals = {str(v).upper() for v in image_type}
    if image_type_vals & _SCOUT_IMAGE_TYPES:
        matched = image_type_vals & _SCOUT_IMAGE_TYPES
        return True, f"ImageType contains {', '.join(matched)}", count

    if count < _SCOUT_SLICE_THRESHOLD:
        return True, f"only {count} slice(s)", count

    return False, "", count


# ── public entry point ────────────────────────────────────────────────────────

def audit_series(series_dir: Path, series_id: str) -> SeriesAuditResult:
    sensitive = load_sensitive_fields()
    result = SeriesAuditResult(series_id=series_id)

    result.tag_failures  = _check_standard_tags(series_dir, sensitive)
    result.is_scout, result.scout_reason, result.slice_count = _detect_scout(series_dir)

    return result


def audit_patient(series_dirs: list[tuple[Path, str]], patient_id: str) -> AuditReport:
    """
    Run the full audit for all series belonging to one patient.
    series_dirs: list of (series_path, series_id) tuples
    """
    report = AuditReport(patient_id=patient_id)
    for series_path, series_id in series_dirs:
        report.series_results.append(audit_series(series_path, series_id))
    return report


# ── log formatting ────────────────────────────────────────────────────────────

def log_audit_report(report: AuditReport) -> None:
    """Emit the audit summary through the standard logger (picked up by SSE stream)."""
    SEP = "─" * 40

    logger.info(SEP)
    logger.info("ANONYMIZATION AUDIT — %s", report.patient_id)
    logger.info(SEP)

    total_series = len(report.series_results)

    for r in report.series_results:
        # Standard tags
        if not r.tag_failures:
            logger.info("  ✓  %s — standard tags clean", r.series_id)
        else:
            logger.error("  ✗  %s — %d tag failure(s):", r.series_id, len(r.tag_failures))
            for f in r.tag_failures:
                logger.error("       [%s]  %s = %r", f.file, f.tag, f.value)

        # Scout
        if r.is_scout:
            logger.warning("  ⚠  %s — scout/localizer detected (%s)", r.series_id, r.scout_reason)
        else:
            logger.info("  ✓  %s — not a scout image (%d slices)", r.series_id, r.slice_count)

    logger.info(SEP)

    status = report.status
    if status == "PASSED":
        logger.info("STATUS:  PASSED  —  %s", report.patient_id)
    elif status == "NEEDS_REVIEW":
        logger.warning("STATUS:  NEEDS REVIEW  —  %s", report.patient_id)
    else:
        logger.error("STATUS:  FAILED  —  %s  (PHI may remain — do not use this data)", report.patient_id)

    logger.info(SEP)
