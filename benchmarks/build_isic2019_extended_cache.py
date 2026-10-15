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
SKIN_CLASSES = ["MEL", "NV", "BCC", "AKIEC", "BKL", "DF", "VASC"]
NV_CAP = 1000  # NV is already 67% of HAM10000; add a little for diversity, not more imbalance
SEED = 42


def main():
    ham_gt = pd.read_csv(HAM_DIR / "GroundTruth.csv")
    ham_ids = ham_gt["image"].tolist()
    ham_labels = ham_gt[SKIN_CLASSES].values.argmax(axis=1)

    iso = pd.read_csv(ISIC_GT)
    iso = iso.rename(columns={"AK": "AKIEC"})
    usable = iso[(iso["SCC"] == 0) & (iso["UNK"] == 0) & (~iso["image"].isin(set(ham_ids)))].copy()
    usable["label"] = usable[SKIN_CLASSES].values.argmax(axis=1)

    rng = np.random.default_rng(SEED)
    nv_idx = usable.index[usable["label"] == SKIN_CLASSES.index("NV")]
    if len(nv_idx) > NV_CAP:
        drop = rng.choice(nv_idx, size=len(nv_idx) - NV_CAP, replace=False)
        usable = usable.drop(index=drop)

    print(f"HAM10000: {len(ham_ids)} images")
    print(f"ISIC 2019 extra (deduped, no SCC/UNK, NV capped at {NV_CAP}): {len(usable)} images")
    counts = pd.Series(SKIN_CLASSES)[usable["label"]].value_counts()
    print("extra class counts:\n", counts)

    extra_ids = usable["image"].tolist()
    extra_labels = usable["label"].values

    all_ids = ham_ids + extra_ids
    all_labels = np.concatenate([ham_labels, extra_labels])
    print(f"combined total: {len(all_ids)} images")

    arr = np.empty((len(all_ids), 3, 224, 224), dtype=np.uint8)
    for i, img_id in enumerate(ham_ids):
        img = Image.open(HAM_DIR / "images" / f"{img_id}.jpg").convert("RGB").resize((224, 224), Image.BILINEAR)
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

    OUT.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"X": torch.from_numpy(arr), "ids": all_ids, "labels": all_labels}, OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
