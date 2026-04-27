"""
generate_ico.py — Build sarcomaai.ico from the sarcomaai.iconset PNG files.

Run once before the Windows build:
    dist_venv\Scripts\python.exe generate_ico.py
"""

from pathlib import Path
from PIL import Image

ICONSET = Path(__file__).parent / 'sarcomaai.iconset'
OUTPUT  = Path(__file__).parent / 'sarcomaai.ico'

# Sizes to include in the .ico (standard Windows icon sizes)
SIZES = [16, 32, 48, 64, 128, 256]

# Map each size to the best available PNG from the iconset
SIZE_TO_FILE = {
    16:  'icon_16x16.png',
    32:  'icon_32x32.png',
    48:  'icon_32x32@2x.png',   # 64px — closest to 48; PIL will resize
    64:  'icon_64x64.png',
    128: 'icon_128x128.png',
    256: 'icon_256x256.png',
}

images = []
for size, filename in SIZE_TO_FILE.items():
    src = ICONSET / filename
    if not src.exists():
        print(f"  [skip] {src.name} not found")
        continue
    img = Image.open(src).convert('RGBA').resize((size, size), Image.LANCZOS)
    images.append(img)
    print(f"  [ok]   {size}x{size} from {src.name}")

if not images:
    raise RuntimeError("No source images found — check sarcomaai.iconset/")

images[0].save(
    OUTPUT,
    format='ICO',
    sizes=[(img.width, img.height) for img in images],
    append_images=images[1:],
)
print(f"\nWrote {OUTPUT}")
