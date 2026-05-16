"""
conftest.py — shared pytest fixtures.

Creates synthetic DICOM files in temporary directories so tests never
touch real patient data. All names, IDs, and dates are fake.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

# Make pipeline modules importable without installing the package
PIPELINE_DIR = Path(__file__).parent.parent / "python_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(PIPELINE_DIR / "dicom"))
sys.path.insert(0, str(PIPELINE_DIR / "imaging"))


def _make_dicom(
    path: Path,
    patient_name: str = "Smith^John",
    patient_id: str = "MRN123456",
    patient_dob: str = "19850312",
    patient_sex: str = "M",
    series_date: str = "20240101",
    study_date: str = "20240101",
    institution: str = "TestHospital",
    modality: str = "MR",
    rows: int = 16,
    cols: int = 16,
    image_type: list = None,
    extra_private_tag: tuple = None,   # ((group, elem), value)
) -> Path:
    """Write a minimal valid DICOM file with controllable PHI fields."""
    ds = FileDataset(str(path), {}, file_meta=Dataset(), preamble=b"\x00" * 128)

    # File meta
    ds.file_meta.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.4"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian
    ds.is_implicit_VR  = False
    ds.is_little_endian = True

    # Patient / study / series identifiers
    ds.PatientName      = patient_name
    ds.PatientID        = patient_id
    ds.PatientBirthDate = patient_dob
    ds.PatientSex       = patient_sex
    ds.StudyDate        = study_date
    ds.SeriesDate       = series_date
    ds.AcquisitionDate  = series_date
    ds.ContentDate      = series_date
    ds.InstitutionName  = institution
    ds.Modality         = modality
    ds.SOPClassUID      = "1.2.840.10008.5.1.4.1.1.4"
    ds.SOPInstanceUID   = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()

    # Image type (used by scout detection)
    ds.ImageType = image_type or ["ORIGINAL", "PRIMARY", "M"]

    # Minimal pixel data (16x16 grayscale)
    pixel_array = np.zeros((rows, cols), dtype=np.uint16)
    ds.Rows            = rows
    ds.Columns         = cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated   = 16
    ds.BitsStored      = 16
    ds.HighBit         = 15
    ds.PixelRepresentation = 0
    ds.PixelData       = pixel_array.tobytes()

    # Optional private tag for testing private-tag audit
    if extra_private_tag is not None:
        (group, elem), value = extra_private_tag
        tag = pydicom.tag.Tag(group, elem)
        ds[tag] = pydicom.DataElement(tag, "LO", value)

    ds.save_as(str(path), write_like_original=False)
    return path


@pytest.fixture()
def dicom_series_dir(tmp_path):
    """
    A temporary directory containing 10 synthetic DICOM files with PHI.
    Represents a raw (un-anonymized) series from a PACS export.
    """
    series_dir = tmp_path / "SE000001"
    series_dir.mkdir()
    for i in range(10):
        _make_dicom(series_dir / f"IM{i:03d}")
    return series_dir


@pytest.fixture()
def scout_series_dir(tmp_path):
    """A 3-slice series tagged as LOCALIZER — should trigger scout detection."""
    series_dir = tmp_path / "SE_SCOUT"
    series_dir.mkdir()
    for i in range(3):
        _make_dicom(
            series_dir / f"IM{i:03d}",
            image_type=["ORIGINAL", "PRIMARY", "LOCALIZER"],
        )
    return series_dir


@pytest.fixture()
def private_tag_series_dir(tmp_path):
    """A series whose representative file contains a private tag with a name-like value."""
    series_dir = tmp_path / "SE_PRIVATE"
    series_dir.mkdir()
    for i in range(10):
        _make_dicom(
            series_dir / f"IM{i:03d}",
            extra_private_tag=((0x0009, 0x1001), "Smith^John"),
        )
    return series_dir


@pytest.fixture()
def anonymized_series_dir(dicom_series_dir):
    """The same series after running anonymize_series() on it."""
    from dicom.dicom_anonymize import anonymize_series
    anonymize_series(dicom_series_dir)
    return dicom_series_dir
