from pathlib import Path
import numpy as np
import SimpleITK as sitk

import logging

logger = logging.getLogger(__name__)

def bias_correct_and_standardize(series_dir: Path) -> sitk.Image | None:
    """
    Perform N4 bias field correction and Z-score normalization on a DICOM series.

    Loads the DICOM series with SimpleITK's native series reader. Applies:
    1. N4 bias field correction (SimpleITK).
    2. Percentile-based intensity clipping (0.5-99.5%).
    3. Z-score normalization (mean=0, std=1).

    Returns:
        A SimpleITK.Image with corrected and normalized data, or None on failure.
    """
    try:
        # Load DICOM series using SimpleITK's native reader (no pyCERR needed)
        dicom_files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(series_dir))
        if not dicom_files:
            logger.error("No DICOM files found in %s", series_dir)
            return None
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(dicom_files)
        itk_orig = reader.Execute()

        logger.info("N4 bias correction on %s", series_dir.name)

        # Apply N4 bias correction — get corrected image directly from SimpleITK
        corrector = sitk.N4BiasFieldCorrectionImageFilter()
        corrector.SetMaximumNumberOfIterations([20, 20, 10])
        corrected_itk = corrector.Execute(itk_orig)

        # Work entirely in numpy from here — avoids CERR coordinate round-trip
        corrected = sitk.GetArrayFromImage(corrected_itk).astype(np.float64)

        # Clip intensities to 0.5–99.5th percentile to suppress outliers
        lo, hi = np.percentile(corrected, [0.5, 99.5])
        corrected = np.clip(corrected, lo, hi)

        # Normalize to zero mean, unit variance
        mean, std = corrected.mean(), max(corrected.std(), 1e-8)
        norm_arr = (corrected - mean) / std

        # Reconstruct SimpleITK image preserving geometry from corrected image
        norm_img = sitk.GetImageFromArray(norm_arr)
        norm_img.CopyInformation(corrected_itk)

        return norm_img

    except Exception as exc:
        logger.error("N4/Z-score failed for %s: %s", series_dir, exc)
        return None