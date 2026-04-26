# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for SarcomaAI GUI
#
# Build steps:
#   1. cd sarcomaAI-gui/frontend && npm run build
#   2. cd sarcomaAI-gui && pyinstaller sarcomaai.spec
#
# Output: dist/SarcomaAI.app  (macOS)  or  dist/SarcomaAI/  (Windows/Linux)

import sys
from pathlib import Path

ROOT = Path(SPECPATH)          # sarcomaAI-gui/
BACKEND = ROOT / 'backend'
PIPELINE = ROOT / 'python_pipeline'
FRONTEND_BUILD = ROOT / 'frontend' / 'build'

# ---------------------------------------------------------------------------
# Data files bundled into the app
# ---------------------------------------------------------------------------
datas = [
    # React production build → served by Flask at /
    (str(FRONTEND_BUILD), 'frontend/build'),

    # Pipeline modules (run in-process inside the bundle)
    (str(PIPELINE / 'anonymization_fields'), 'python_pipeline/anonymization_fields'),
    (str(PIPELINE / 'dicom'), 'python_pipeline/dicom'),
    (str(PIPELINE / 'imaging'), 'python_pipeline/imaging'),
    (str(PIPELINE / 'config.py'), 'python_pipeline'),
    (str(PIPELINE / 'constants.py'), 'python_pipeline'),
    (str(PIPELINE / 'csv_utils.py'), 'python_pipeline'),
    (str(PIPELINE / 'ledger.py'), 'python_pipeline'),
    (str(PIPELINE / 'models.py'), 'python_pipeline'),
    (str(PIPELINE / 'pipeline_new.py'), 'python_pipeline'),
    (str(PIPELINE / 'series_select.py'), 'python_pipeline'),

    # Backend db module (imported by App.py as 'db')
    (str(BACKEND / 'db.py'), '.'),
]

# ---------------------------------------------------------------------------
# Hidden imports (packages that PyInstaller can't auto-detect)
# ---------------------------------------------------------------------------
hiddenimports = [
    # Flask ecosystem
    'flask',
    'flask_cors',
    'werkzeug',
    'werkzeug.serving',
    'werkzeug.middleware',
    'jinja2',
    'click',

    # DICOM / imaging
    'pydicom',
    'pydicom.encoders',
    'matplotlib',
    'matplotlib.pyplot',
    'matplotlib.backends.backend_agg',

    # SimpleITK (pulled in by imaging_normalize)
    'SimpleITK',
    'SimpleITK.SimpleITK',

    # pyCERR and all its declared dependencies
    'cerr',
    'cerr.plan_container',
    'cerr.dataclasses',
    'cerr.dataclasses.scan',
    'nibabel',
    'nibabel.loadsave',
    'scipy',
    'scipy.ndimage',
    'scipy.interpolate',
    'scipy.io',
    'h5py',
    'pandas',
    'skimage',
    'skimage.transform',
    'skimage.filters',
    'sklearn',
    'sklearn.preprocessing',
    'pywt',
    'shapely',
    'shapelysmooth',
    'surface_distance',
    'itk',
    'networkx',
    'imageio',

    # Standard library extras
    'queue',
    'threading',
    'webbrowser',
    'importlib',
    'sqlite3',
    'csv',
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
from PyInstaller.utils.hooks import collect_all as _collect_all

_sitk_datas, _sitk_bins, _sitk_hidden = _collect_all('SimpleITK')
datas += _sitk_datas
hiddenimports += _sitk_hidden

_cerr_datas, _cerr_bins, _cerr_hidden = _collect_all('cerr')
datas += _cerr_datas
hiddenimports += _cerr_hidden

for _pkg in ('nibabel', 'h5py', 'scipy', 'skimage', 'sklearn', 'pandas', 'itk'):
    _d, _b, _h = _collect_all(_pkg)
    datas += _d
    _cerr_bins += _b
    hiddenimports += _h

a = Analysis(
    [str(BACKEND / 'App.py')],
    pathex=[str(BACKEND)],
    binaries=_sitk_bins + _cerr_bins,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SarcomaAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # No terminal window on macOS/Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='sarcomaai.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SarcomaAI',
)

# macOS .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='SarcomaAI.app',
        icon=None,           # Replace with 'sarcomaai.icns' if you have one
        bundle_identifier='com.sarcomaai.gui',
        info_plist={
            'CFBundleName': 'SarcomaAI',
            'CFBundleDisplayName': 'SarcomaAI',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
            'LSUIElement': False,            # Show in Dock
        },
    )
