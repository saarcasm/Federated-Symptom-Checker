"""
Extend the HAM10000 skin cache with non-duplicate ISIC 2019 images, to fix
HAM10000's severe class imbalance (DF and VASC have under 150 training
images each). ISIC 2019 is built on top of HAM10000 plus extra sources, and
has far more examples of the rare classes -- this adds those, not more NV
(already 67% of HAM10000), capped so it doesn't shift the imbalance the
other way.

Images already appearing in HAM10000 (by ISIC id) are excluded, so there is
no train/test leakage between the two sources. SCC and UNK (ISIC-2019-only
classes, not in the paper's 7-class HAM10000 scheme) are excluded. AK is
mapped to AKIEC (same class, different name).

Produces data/processed/ham10000_isic2019_224.pt, in the same format as the
other skin caches (X, ids, labels), so skin_sanity_check.py can use it with
a one-line change to CACHE.

Run: python benchmarks/build_isic2019_extended_cache.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import torch
from PIL import Image

HAM_DIR = PROJECT_ROOT / "data" / "raw" / "ham10000"
ISIC_GT = PROJECT_ROOT / "data" / "raw" / "isic2019" / "ISIC_2019_Training_GroundTruth.csv"
ISIC_IMG_DIR = PROJECT_ROOT / "data" / "raw" / "isic2019" / "train-image" / "image"
OUT = PROJECT_ROOT / "data" / "processed" / "ham10000_isic2019_224.pt"
OUT_CROPPED = PROJECT_ROOT / "data" / "processed" / "ham10000_cropped_isic2019_224.pt"
# Note: re-running this script overwrites OUT with the current cap. If this version's
# cap differs from a previously saved cache, delete the old file first so stale data
# isn't silently reused.
SKIN_CLASSES = ["MEL", "NV", "BCC", "AKIEC", "BKL", "DF", "VASC"]
CLASS_CAP = 1000  # cap EVERY class's extra contribution (not just NV), so the combined
                   # cache stays small enough to safely fit in memory on this machine.
                   # DF/VASC/AKIEC are all well under this cap anyway, so the classes that
                   # actually needed rebalancing are unaffected; this only trims how much
                   # extra MEL/BCC/BKL/NV (already reasonably represented) gets added.
SEED = 42


def crop_to_mask(img, img_id):
    """Crop to the lesion mask's bounding box (15% margin), same logic as
    skin_sanity_check.py's build_cropped_cache. ISIC-2019 extras have no
    mask, so only the HAM10000 portion of this cache is cropped."""
    mask_path = HAM_DIR / "masks" / f"{img_id}_segmentation.png"
    if not mask_path.exists():
        return img
    m = np.array(Image.open(mask_path))
    ys, xs = np.where(m > 127)
    if len(xs) == 0:
        return img
    w, h = img.size
    sx, sy = w / m.shape[1], h / m.shape[0]
    x0, x1 = xs.min() * sx, xs.max() * sx
    y0, y1 = ys.min() * sy, ys.max() * sy
    pad_x, pad_y = (x1 - x0) * 0.15, (y1 - y0) * 0.15
    x0, y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    x1, y1 = min(w, x1 + pad_x), min(h, y1 + pad_y)
    return img.crop((x0, y0, x1, y1)) if x1 > x0 and y1 > y0 else img


def main(crop):
    ham_gt = pd.read_csv(HAM_DIR / "GroundTruth.csv")
    ham_ids = ham_gt["image"].tolist()
    ham_labels = ham_gt[SKIN_CLASSES].values.argmax(axis=1)

    iso = pd.read_csv(ISIC_GT)
    iso = iso.rename(columns={"AK": "AKIEC"})
    usable = iso[(iso["SCC"] == 0) & (iso["UNK"] == 0) & (~iso["image"].isin(set(ham_ids)))].copy()
    usable["label"] = usable[SKIN_CLASSES].values.argmax(axis=1)

    rng = np.random.default_rng(SEED)
    for cls_idx in range(len(SKIN_CLASSES)):
        cls_rows = usable.index[usable["label"] == cls_idx]
        if len(cls_rows) > CLASS_CAP:
            drop = rng.choice(cls_rows, size=len(cls_rows) - CLASS_CAP, replace=False)
            usable = usable.drop(index=drop)

    print(f"HAM10000: {len(ham_ids)} images")
    print(f"ISIC 2019 extra (deduped, no SCC/UNK, each class capped at {CLASS_CAP}): {len(usable)} images")
    counts = pd.Series(SKIN_CLASSES)[usable["label"]].value_counts()
    print("extra class counts:\n", counts)

    extra_ids = usable["image"].tolist()
    extra_labels = usable["label"].values

    all_ids = ham_ids + extra_ids
    all_labels = np.concatenate([ham_labels, extra_labels])
    print(f"combined total: {len(all_ids)} images")

    arr = np.empty((len(all_ids), 3, 224, 224), dtype=np.uint8)
    for i, img_id in enumerate(ham_ids):
        img = Image.open(HAM_DIR / "images" / f"{img_id}.jpg").convert("RGB")
        if crop:
            img = crop_to_mask(img, img_id)
        img = img.resize((224, 224), Image.BILINEAR)
        arr[i] = np.asarray(img).transpose(2, 0, 1)
        if i % 2000 == 0:
            print(f"HAM images: {i}/{len(ham_ids)}", flush=True)
    for j, img_id in enumerate(extra_ids):
        # Already 224x224 in this Kaggle copy; resize is a no-op safety net if not.
        img = Image.open(ISIC_IMG_DIR / f"{img_id}.jpg").convert("RGB")
        if img.size != (224, 224):
            img = img.resize((224, 224), Image.BILINEAR)
        arr[len(ham_ids) + j] = np.asarray(img).transpose(2, 0, 1)
        if j % 2000 == 0:
            print(f"ISIC extra images: {j}/{len(extra_ids)}", flush=True)

    out_path = OUT_CROPPED if crop else OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"X": torch.from_numpy(arr), "ids": all_ids, "labels": all_labels}, out_path)
    print("wrote", out_path)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", action="store_true",
                    help="also crop the HAM10000 portion to its lesion mask bounding box")
    main(crop=ap.parse_args().crop)
