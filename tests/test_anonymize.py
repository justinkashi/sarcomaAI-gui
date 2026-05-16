"""
test_anonymize.py — Tests for dicom_anonymize.py

Verifies that after anonymize_series() runs:
- Every sensitive tag contains the expected dummy value
- Files are overwritten in place (not duplicated)
- The PatientIdentityRemoved flag is set
"""

import pydicom
import pytest
from pathlib import Path

from dicom.dicom_anonymize import anonymize_series, load_sensitive_fields

DUMMY_TEXT     = "ANONYMIZED"
DUMMY_DATE     = "19000101"
DUMMY_DATETIME = "19000101000000"
DUMMY_AGE      = "000Y"
DUMMY_DECIMAL  = "0"


def _read_first(series_dir: Path) -> pydicom.Dataset:
    files = sorted(series_dir.glob("IM*"))
    assert files, "No DICOM files found in series dir"
    return pydicom.dcmread(str(files[0]), force=True)


class TestAnonymizeSeries:

    def test_patient_name_scrubbed(self, dicom_series_dir):
        anonymize_series(dicom_series_dir)
        ds = _read_first(dicom_series_dir)
        assert str(ds.PatientName) == DUMMY_TEXT

    def test_patient_id_scrubbed(self, dicom_series_dir):
        anonymize_series(dicom_series_dir)
        ds = _read_first(dicom_series_dir)
        assert ds.PatientID == DUMMY_TEXT

    def test_dates_scrubbed(self, dicom_series_dir):
        anonymize_series(dicom_series_dir)
        ds = _read_first(dicom_series_dir)
        assert ds.PatientBirthDate == DUMMY_DATE
        assert ds.StudyDate        == DUMMY_DATE
        assert ds.SeriesDate       == DUMMY_DATE
        assert ds.AcquisitionDate  == DUMMY_DATE
        assert ds.ContentDate      == DUMMY_DATE

    def test_institution_scrubbed(self, dicom_series_dir):
        anonymize_series(dicom_series_dir)
        ds = _read_first(dicom_series_dir)
        assert ds.InstitutionName == DUMMY_TEXT

    def test_patient_identity_removed_flag_set(self, dicom_series_dir):
        anonymize_series(dicom_series_dir)
        ds = _read_first(dicom_series_dir)
        assert ds.PatientIdentityRemoved == "YES"

    def test_all_files_scrubbed(self, dicom_series_dir):
        anonymize_series(dicom_series_dir)
        files = sorted(dicom_series_dir.glob("IM*"))
        assert len(files) == 10, "Should still have 10 files — no duplicates created"
        for fpath in files:
            ds = pydicom.dcmread(str(fpath), force=True)
            assert str(ds.PatientName) == DUMMY_TEXT, f"{fpath.name} still has PHI"

    def test_all_sensitive_fields_scrubbed(self, dicom_series_dir):
        """Every field in sensitive_fields.json that exists in the file must be a dummy value."""
        anonymize_series(dicom_series_dir)
        sensitive = load_sensitive_fields()
        real_dummy_values = {DUMMY_TEXT, DUMMY_DATE, DUMMY_DATETIME, DUMMY_AGE, DUMMY_DECIMAL, "YES", ""}

        for fpath in sorted(dicom_series_dir.glob("IM*")):
            ds = pydicom.dcmread(str(fpath), force=True)
            for elem in ds:
                if elem.keyword in sensitive:
                    assert str(elem.value).strip() in real_dummy_values, (
                        f"{fpath.name}: tag {elem.keyword!r} still contains {elem.value!r}"
                    )

    def test_pixel_data_preserved(self, dicom_series_dir):
        """Anonymization must not touch pixel data."""
        anonymize_series(dicom_series_dir)
        ds = _read_first(dicom_series_dir)
        assert ds.PixelData is not None
        assert len(ds.PixelData) > 0
