"""Generate the example paper image `legal-pad.jpg` (yellow legal pad with a double red margin).

Any photo or scan of a sheet works the same way as a template image; this script only
exists so the example needs no binary asset beyond what it creates.
Run:  python examples/templates/make_legal_pad.py
"""
import numpy as np
from PIL import Image

W, H, PITCH, FIRST = 1654, 2339, 58, 182
rng = np.random.default_rng(3)
img = np.empty((H, W, 3), np.float32)
img[:] = (250, 238, 160)
img *= (1 + 0.012 * rng.standard_normal((H, W, 1))).astype(np.float32)
for y in range(FIRST, H - 60, PITCH):
    img[y : y + 2, :, :] = (118, 150, 190)
img[:, 190:192] = (205, 80, 80)
img[:, 196:198] = (205, 80, 80)
img[120:122, :, :] = (205, 80, 80)  # header rule
Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save("examples/templates/legal-pad.jpg", quality=88)
