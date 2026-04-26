"""
pipeline_new.py — Copy selected DICOM series, anonymize, normalize, and write
a run-output file for the backend to consolidate into the ledger.

Changes from pipeline.py:
- No ledger.csv dependency. Rows are written to .pipeline_run_output.csv
  (a temporary file per run) which the backend merges into .ledger_internal.csv.
- Starting patient ID is determined solely from files on disk, not from ledger.csv.
- IS_NEW_DATASET removed — the backend controls dataset lifecycle.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

from config import (
    INSTITUTION,
    DATASET_PATH,
    STS_DATASET,
    SELECTION_CSV,
)

from ledger import _highest_patient_id_on_disk

from dicom.dicom_anonymize import anonymize_series
from dicom.dicom_tags import process_series_metadata

from imaging.imaging_normalize import bias_correct_and_standardize
from imaging.imaging_io import atomic_write_sitk

from series_select import copy_selected_series

RUN_OUTPUT_FILE = ".pipeline_run_output.csv"
RUN_OUTPUT_HEADER = ["OrigID", "NewID", "MRN", "Institution", "Study", "Series", "Modality", "STSName"]


def _append_run_row(run_output: Path, row: list) -> None:
    """Append a single row to the run output file, creating it with header if needed."""
    write_header = not run_output.exists()
    with run_output.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(RUN_OUTPUT_HEADER)
        writer.writerow(row)


def main() -> None:
    dataset, sts_dataset, selection_csv = (
        DATASET_PATH.resolve(),
        STS_DATASET.resolve(),
        SELECTION_CSV.resolve(),
    )

    if not dataset.exists():
        raise FileNotFoundError(dataset)
    if not selection_csv.exists():
        raise FileNotFoundError(selection_csv)

    sts_dataset.mkdir(parents=True, exist_ok=True)

    run_output = sts_dataset / RUN_OUTPUT_FILE

    # Determine next patient ID from files already on disk
    start_id = _highest_patient_id_on_disk(sts_dataset)
    logger.info("Next new Patient ID will start at PA%06d", start_id + 1)

    series_info = copy_selected_series(
        dataset, sts_dataset, selection_csv, INSTITUTION, start_id
    )
    logger.info("Selected %d series", len(series_info))

    root_dir = sts_dataset.parent / f"sts.{INSTITUTION}"

    for info in series_info:
        series_path = sts_dataset / "DICOM" / info.new_id / info.study / info.series

        info.mrn = process_series_metadata(series_path, info.sts_name)
        anonymize_series(series_path)
        logger.info("Anonymized %s", series_path.relative_to(sts_dataset))

        patient_dir = root_dir / f"sts.{INSTITUTION}.{info.new_id[2:]}"
        nifti_path  = patient_dir / f"sts.{INSTITUTION}.{info.new_id[2:]}.{info.modality}.nii"

        if nifti_path.exists():
            logger.info("NIfTI already exists, skipping: %s", nifti_path)
            success = True
        else:
            img     = bias_correct_and_standardize(series_path)
            success = img is not None
            if success:
                atomic_write_sitk(img, nifti_path)
                logger.info("Saved NIfTI → %s", nifti_path)

        if not success:
            logger.warning("Processing failed for %s; run output not updated.", info.sts_name)
            continue

        _append_run_row(
            run_output,
            [info.orig_id, info.new_id, info.mrn, INSTITUTION, info.study, info.series, info.modality, info.sts_name],
        )
        logger.info("Run output appended: %s (MRN %s, %s)", info.new_id, info.mrn, info.modality.upper())


if __name__ == "__main__":
    main()
