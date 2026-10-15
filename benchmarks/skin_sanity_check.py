"""
Centralized sanity check for the skin model (no federation, no DP).

Purpose: find out whether SkinCNN (pretrained MobileNetV3-Small) can learn
HAM10000 at all, and which training settings matter.

Protocol:
  - Same 80/20 stratified split as the federated experiment (seed 42).
  - The 20% test split is used ONCE, for the final report of the chosen config.
  - Configs are compared on a 10% validation split carved from the training set.
  - Keeps the pretrained BatchNorm (no GroupNorm conversion, which is only
    needed for Opacus DP-SGD and discards pretrained statistics).

Run:  python benchmarks/skin_sanity_check.py --config adam_weighted --epochs 6
"""
import sys, time, json, argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split, GroupShuffleSplit
import pandas as pd
from PIL import Image

from models.skin_cnn import SkinCNN

SEED = 42
CACHE = PROJECT_ROOT / "data" / "processed" / "ham10000_224.pt"
CACHE_CROPPED = PROJECT_ROOT / "data" / "processed" / "ham10000_224_cropped.pt"
CACHE_ISIC = PROJECT_ROOT / "data" / "processed" / "ham10000_isic2019_224.pt"
META = PROJECT_ROOT / "data" / "raw" / "ham10000_meta" / "HAM10000_metadata.csv"
HAM_DIR = PROJECT_ROOT / "data" / "raw" / "ham10000"
SKIN_CLASSES = ["MEL", "NV", "BCC", "AKIEC", "BKL", "DF", "VASC"]


def build_cropped_cache():
    """Crop each image to its lesion-mask bounding box (with a margin) before
    resizing, instead of resizing the whole frame. Removes background
    skin/hair as noise. Builds its own cache so the uncropped cache (and any
    run using it) is untouched."""
    gt = pd.read_csv(HAM_DIR / "GroundTruth.csv")
    ids = gt["image"].tolist()
    labels = gt[SKIN_CLASSES].values.argmax(axis=1)
    arr = np.empty((len(ids), 3, 224, 224), dtype=np.uint8)
    for i, img_id in enumerate(ids):
        img = Image.open(HAM_DIR / "images" / f"{img_id}.jpg").convert("RGB")
        mask_path = HAM_DIR / "masks" / f"{img_id}_segmentation.png"
        if mask_path.exists():
            m = np.array(Image.open(mask_path))
            ys, xs = np.where(m > 127)
            if len(xs) > 0:
                w, h = img.size
                sx, sy = w / m.shape[1], h / m.shape[0]
                x0, x1 = xs.min() * sx, xs.max() * sx
                y0, y1 = ys.min() * sy, ys.max() * sy
                pad_x, pad_y = (x1 - x0) * 0.15, (y1 - y0) * 0.15
                x0, y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
                x1, y1 = min(w, x1 + pad_x), min(h, y1 + pad_y)
                if x1 > x0 and y1 > y0:
                    img = img.crop((x0, y0, x1, y1))
        img = img.resize((224, 224), Image.BILINEAR)
        arr[i] = np.asarray(img).transpose(2, 0, 1)
    CACHE_CROPPED.parent.mkdir(parents=True, exist_ok=True)
    cache = {"X": torch.from_numpy(arr), "ids": ids, "labels": labels}
    torch.save(cache, CACHE_CROPPED)
    return cache
OUT_DIR = PROJECT_ROOT / "benchmarks" / "results" / "skin"
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

CONFIGS = {
    # name: (optimizer, lr, class_weighted, augment)
    "sgd_plain":      ("sgd",  0.01, False, False),
    "adam_plain":     ("adam", 1e-3, False, False),
    "adam_weighted":  ("adam", 1e-3, True,  True),
    "adam_lowlr":     ("adam", 3e-4, True,  True),
    "adam_cosine":    ("adam", 3e-4, True,  True),  # same as adam_lowlr, with cosine LR decay
    "adam_cosine60":  ("adam", 3e-4, True,  True),  # cosine, longer schedule
}


def normalize(x):
    return (x.float() / 255.0 - MEAN) / STD


def augment(x):
    """Dermoscopy images have no canonical orientation: flips and 90-degree rotations are label-preserving."""
    if np.random.rand() < 0.5:
        x = torch.flip(x, dims=[3])
    if np.random.rand() < 0.5:
        x = torch.flip(x, dims=[2])
    k = np.random.randint(4)
    return torch.rot90(x, k, dims=[2, 3])


@torch.inference_mode()
def evaluate(model, X, y, bs=128):
    model.eval()
    preds = []
    for s in range(0, len(X), bs):
        preds.append(model(normalize(X[s:s + bs])).argmax(1))
    p = torch.cat(preds).numpy()
    t = y.numpy()
    return float((p == t).mean()), float(f1_score(t, p, average="macro"))


@torch.inference_mode()
def evaluate_tta(model, X, y, bs=128, views=(0, 1, 2, 3)):
    """Test-time augmentation: average softmax over the same label-preserving
    flips/rotations used in training augmentation, then take the argmax.
    Standard technique -- does not touch labels or retrain anything."""
    model.eval()
    probs_sum = None
    for v in views:
        batch_probs = []
        for s in range(0, len(X), bs):
            xb = normalize(X[s:s + bs])
            if v == 1:
                xb = torch.flip(xb, dims=[3])
            elif v == 2:
                xb = torch.flip(xb, dims=[2])
            elif v == 3:
                xb = torch.rot90(xb, 1, dims=[2, 3])
            batch_probs.append(F.softmax(model(xb), dim=1))
        probs = torch.cat(batch_probs)
        probs_sum = probs if probs_sum is None else probs_sum + probs
    p = (probs_sum / len(views)).argmax(1).numpy()
    t = y.numpy()
    return float((p == t).mean()), float(f1_score(t, p, average="macro"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=list(CONFIGS), required=True)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--grouped", action=argparse.BooleanOptionalAction, default=True,
                    help="split by lesion_id (default); --no-grouped reproduces the old random split")
    ap.add_argument("--crop_lesion", action="store_true",
                    help="crop to the lesion mask's bounding box before resizing (builds its own cache)")
    ap.add_argument("--extended_isic", action="store_true",
                    help="train on HAM10000 + non-duplicate ISIC-2019 extras (run "
                         "build_isic2019_extended_cache.py first); mutually exclusive with --crop_lesion")
    ap.add_argument("--tta", action="store_true",
                    help="test-time augmentation at final evaluation: average predictions over flips/rotations")
    ap.add_argument("--save_checkpoint", action="store_true",
                    help="save the trained model's state_dict alongside the result json")
    ap.add_argument("--resume", action="store_true",
                    help="resume from the _inprogress checkpoint for this exact config/tag, if one exists")
    ap.add_argument("--final_test", action="store_true",
                    help="evaluate on the held-out test split (do this once, for the chosen config)")
    args = ap.parse_args()
    opt_name, lr, weighted, aug = CONFIGS[args.config]

    torch.manual_seed(SEED); np.random.seed(SEED)
    if args.extended_isic:
        assert not args.crop_lesion, "--extended_isic and --crop_lesion are mutually exclusive"
        assert CACHE_ISIC.exists(), "run benchmarks/build_isic2019_extended_cache.py first"
        cache = torch.load(CACHE_ISIC, weights_only=False)
    elif args.crop_lesion:
        cache = (torch.load(CACHE_CROPPED, weights_only=False) if CACHE_CROPPED.exists()
                 else build_cropped_cache())
    else:
        cache = torch.load(CACHE, weights_only=False)  # our own cache file (contains numpy labels)
    X, labels = cache["X"], np.asarray(cache["labels"])
    if args.grouped:
        # Split by lesion: several images of one lesion must never sit on both sides.
        meta = pd.read_csv(META)
        lesion = dict(zip(meta["image_id"], meta["lesion_id"]))
        groups = np.array([lesion.get(i, i) for i in cache["ids"]])  # ISIC-2019 extras have no lesion_id -> each is its own group
        gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
        idx_tr, idx_te = next(gss.split(np.zeros(len(labels)), labels, groups))
        gss2 = GroupShuffleSplit(n_splits=1, test_size=0.1, random_state=SEED)
        a, b = next(gss2.split(np.zeros(len(idx_tr)), labels[idx_tr], groups[idx_tr]))
        idx_fit, idx_val = idx_tr[a], idx_tr[b]
    else:
        idx_tr, idx_te = train_test_split(np.arange(len(labels)), test_size=0.2,
                                          stratify=labels, random_state=SEED)
        idx_fit, idx_val = train_test_split(idx_tr, test_size=0.1,
                                            stratify=labels[idx_tr], random_state=SEED)
    y = torch.tensor(labels, dtype=torch.long)

    Xf, yf = X[idx_fit], y[idx_fit]
    Xv, yv = X[idx_val], y[idx_val]
    print(f"config={args.config} opt={opt_name} lr={lr} weighted={weighted} aug={aug}", flush=True)
    print(f"fit={len(yf)} val={len(yv)} test={len(idx_te)}", flush=True)
    print("fit class counts:", torch.bincount(yf, minlength=7).tolist(), flush=True)

    model = SkinCNN(num_classes=7)
    if opt_name == "sgd":
        opt = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    else:
        opt = torch.optim.Adam(model.parameters(), lr=lr)

    weights = None
    if weighted:
        counts = torch.bincount(yf, minlength=7).float()
        weights = (counts.sum() / (7 * counts)).clamp(max=10.0)
        print("class weights:", [round(w, 2) for w in weights.tolist()], flush=True)

    tag = ("grouped" if args.grouped else "random") + ("_cropped" if args.crop_lesion else "") + ("_isic2019" if args.extended_isic else "")
    ckpt_path = OUT_DIR / f"sanity_{args.config}_{tag}_inprogress.pt"
    hist_path = OUT_DIR / f"sanity_{args.config}_{tag}_inprogress_history.json"

    history = []
    start_epoch = 0
    if args.resume and ckpt_path.exists() and hist_path.exists():
        model.load_state_dict(torch.load(ckpt_path, weights_only=True))
        history = json.loads(hist_path.read_text())
        start_epoch = history[-1]["epoch"]
        print(f"resumed from {ckpt_path} at epoch {start_epoch}", flush=True)

    sched = None
    if args.config.startswith("adam_cosine"):
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
        for _ in range(start_epoch):  # fast-forward when resuming (initial_lr isn't set
            sched.step()               # on a fresh optimizer, so last_epoch=N at construction fails)

    for ep in range(start_epoch, args.epochs):
        t0 = time.time()
        model.train()
        perm = torch.randperm(len(yf))
        for s in range(0, len(perm), args.batch_size):
            b = perm[s:s + args.batch_size]
            xb = Xf[b]
            if aug:
                xb = augment(xb)
            loss = F.cross_entropy(model(normalize(xb)), yf[b], weight=weights)
            opt.zero_grad()
            loss.backward()
            opt.step()
        if sched is not None:
            sched.step()
        va_acc, va_f1 = evaluate(model, Xv, yv)
        history.append({"epoch": ep + 1, "val_acc": va_acc, "val_macro_f1": va_f1})
        print(f"epoch {ep+1}  loss={loss.item():.3f}  val_acc={va_acc:.4f}  val_macro_f1={va_f1:.4f}  "
              f"({time.time()-t0:.0f}s)", flush=True)
        if args.save_checkpoint:
            # Save after every epoch (overwriting), not just at the end -- a kill late in
            # training should cost at most the last epoch, not the whole run (use --resume
            # to continue from here instead of restarting from scratch).
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), ckpt_path)
            hist_path.write_text(json.dumps(history, indent=2))

    result = {"config": args.config, "history": history}
    if args.final_test:
        te_acc, te_f1 = evaluate(model, X[idx_te], y[idx_te])
        result["test_acc"], result["test_macro_f1"] = te_acc, te_f1
        print(f"TEST  acc={te_acc:.4f}  macro_f1={te_f1:.4f}", flush=True)
        if args.tta:
            tta_acc, tta_f1 = evaluate_tta(model, X[idx_te], y[idx_te])
            result["test_acc_tta"], result["test_macro_f1_tta"] = tta_acc, tta_f1
            print(f"TEST (TTA)  acc={tta_acc:.4f}  macro_f1={tta_f1:.4f}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"sanity_{args.config}_{tag}{'_final' if args.final_test else ''}.json"
    out.write_text(json.dumps(result, indent=2))
    print("wrote", out, flush=True)
    if args.save_checkpoint:
        ckpt = out.with_suffix(".pt")
        torch.save(model.state_dict(), ckpt)
        print("wrote", ckpt, flush=True)


if __name__ == "__main__":
    main()
