"""
Cycle-level respiratory sanity check: segments ICBHI at its ANNOTATED
breathing-cycle boundaries instead of arbitrary fixed 3 s windows, and
reports both cycle-level and recording-level (majority-vote) accuracy.

This targets two of the gaps found in the fixed-window experiment:
  1. Label noise from windows that don't line up with real cycles.
  2. No use of the fact that one recording has many cycles -- voting across
     them is the standard way to get a recording-level prediction.

Protocol: patient-level 80/20 split (seed 42). Validation is carved from
training patients only. The test split is scored once, with --final_test.

Run:  python benchmarks/respiratory_cycle_sanity_check.py --config pretrained --epochs 20 --final_test
"""
import sys, json, time, argparse
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import f1_score

from models.respiratory_cnn import RespiratoryCNN
from models.skin_cnn import SkinCNN
sys.path.insert(0, str(PROJECT_ROOT / "benchmarks"))
from respiratory_federated_experiment import build_cycle_dataset, patient_split, CLASSES, SEED

CACHE = PROJECT_ROOT / "data" / "processed" / "icbhi_cycles.pt"
OUT_DIR = PROJECT_ROOT / "benchmarks" / "results" / "respiratory"

CONFIGS = {
    "adam_lowlr": ("adam", 3e-4, True, False),
    "pretrained": ("adam", 3e-4, True, True),
}

IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def to_pretrained_input(x):
    lo = x.amin(dim=(1, 2, 3), keepdim=True)
    hi = x.amax(dim=(1, 2, 3), keepdim=True)
    x = (x - lo) / (hi - lo + 1e-6)
    x = x.repeat(1, 3, 1, 1)
    x = F.interpolate(x, size=224, mode="bilinear", align_corners=False)
    return (x - IMAGENET_MEAN) / IMAGENET_STD


def load_cycles():
    if CACHE.exists():
        c = torch.load(CACHE, weights_only=False)
        return c["X"], c["y"], c["pid"], c["rec"]
    X, y, pid, rec = build_cycle_dataset()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"X": X, "y": y, "pid": pid, "rec": rec}, CACHE)
    return X, y, pid, rec


@torch.inference_mode()
def predict(model, X, pretrained, bs=64):
    model.eval()
    preds = []
    for s in range(0, len(X), bs):
        xb = to_pretrained_input(X[s:s + bs]) if pretrained else X[s:s + bs]
        preds.append(model(xb).argmax(1))
    return torch.cat(preds).numpy()


@torch.inference_mode()
def predict_tta(model, X, pretrained, bs=64, shifts=(0, 8, -8, 16, -16)):
    """Test-time augmentation for spectrograms: average softmax over small
    circular time-shifts (the audio analogue of the flips used for images --
    a cough/crackle/wheeze is still the same event a few frames earlier or
    later). Does not touch labels or retrain anything."""
    model.eval()
    probs_sum = None
    for shift in shifts:
        Xs = torch.roll(X, shifts=shift, dims=3) if shift else X
        batch_probs = []
        for s in range(0, len(Xs), bs):
            xb = to_pretrained_input(Xs[s:s + bs]) if pretrained else Xs[s:s + bs]
            batch_probs.append(F.softmax(model(xb), dim=1))
        probs = torch.cat(batch_probs)
        probs_sum = probs if probs_sum is None else probs_sum + probs
    return (probs_sum / len(shifts)).argmax(1).numpy()


def cycle_and_recording_metrics(preds, y_true, rec_ids):
    cyc_acc = float((preds == y_true).mean())
    cyc_f1 = float(f1_score(y_true, preds, average="macro"))

    # Recording-level label: majority vote of the TRUE cycle labels (a recording
    # can contain a mix, since labels are per-cycle). Recording-level prediction:
    # majority vote of the PREDICTED cycle labels.
    true_by_rec, pred_by_rec = {}, {}
    for p, t, r in zip(preds, y_true, rec_ids):
        true_by_rec.setdefault(r, []).append(int(t))
        pred_by_rec.setdefault(r, []).append(int(p))
    rec_ids_sorted = sorted(true_by_rec)
    rt = np.array([Counter(true_by_rec[r]).most_common(1)[0][0] for r in rec_ids_sorted])
    rp = np.array([Counter(pred_by_rec[r]).most_common(1)[0][0] for r in rec_ids_sorted])
    rec_acc = float((rt == rp).mean())
    rec_f1 = float(f1_score(rt, rp, average="macro"))
    return cyc_acc, cyc_f1, rec_acc, rec_f1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=list(CONFIGS), required=True)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--final_test", action="store_true")
    ap.add_argument("--tta", action="store_true",
                    help="test-time augmentation at final evaluation: average predictions over small time-shifts")
    ap.add_argument("--save_checkpoint", action="store_true",
                    help="save the trained model's state_dict alongside the result json")
    ap.add_argument("--resume", action="store_true",
                    help="resume from the _inprogress checkpoint for this config, if one exists")
    args = ap.parse_args()
    opt_name, lr, weighted, pretrained = CONFIGS[args.config]

    torch.manual_seed(SEED); np.random.seed(SEED)
    X, y, pid, rec = load_cycles()
    idx_tr, idx_te = patient_split(pid)

    rng = np.random.default_rng(SEED)
    tr_patients = np.unique(pid[idx_tr])
    rng.shuffle(tr_patients)
    val_p = set(tr_patients[: max(1, len(tr_patients) // 8)])
    is_val = np.array([p in val_p for p in pid[idx_tr]])
    idx_fit, idx_val = idx_tr[~is_val], idx_tr[is_val]

    Xf, yf = X[idx_fit], y[idx_fit]
    Xv, yv = X[idx_val], y[idx_val]
    print(f"config={args.config} opt={opt_name} lr={lr} weighted={weighted} pretrained={pretrained}", flush=True)
    print(f"cycles: fit={len(yf)} val={len(yv)} test={len(idx_te)}", flush=True)
    print("fit class counts:", torch.bincount(yf, minlength=4).tolist(), flush=True)
    print(f"recordings: train={len(set(rec[idx_tr]))} test={len(set(rec[idx_te]))}", flush=True)

    torch.manual_seed(SEED)
    model = SkinCNN(num_classes=4) if pretrained else RespiratoryCNN(num_classes=4)
    opt = (torch.optim.Adam(model.parameters(), lr=lr) if opt_name == "adam"
           else torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9))

    weights = None
    if weighted:
        counts = torch.bincount(yf, minlength=4).float()
        weights = (counts.sum() / (4 * counts)).clamp(max=10.0)
        print("class weights:", [round(w, 2) for w in weights.tolist()], flush=True)

    ckpt_path = OUT_DIR / f"cycle_sanity_{args.config}_inprogress.pt"
    hist_path = OUT_DIR / f"cycle_sanity_{args.config}_inprogress_history.json"
    history = []
    start_epoch = 0
    if args.resume and ckpt_path.exists() and hist_path.exists():
        model.load_state_dict(torch.load(ckpt_path, weights_only=True))
        history = json.loads(hist_path.read_text())
        start_epoch = history[-1]["epoch"]
        print(f"resumed from {ckpt_path} at epoch {start_epoch}", flush=True)

    for ep in range(start_epoch, args.epochs):
        t0 = time.time()
        model.train()
        perm = torch.randperm(len(yf))
        for s in range(0, len(perm), args.batch_size):
            b = perm[s:s + args.batch_size]
            xb = to_pretrained_input(Xf[b]) if pretrained else Xf[b]
            loss = F.cross_entropy(model(xb), yf[b], weight=weights)
            opt.zero_grad()
            loss.backward()
            opt.step()
        preds = predict(model, Xv, pretrained)
        va_acc = float((preds == yv.numpy()).mean())
        va_f1 = float(f1_score(yv.numpy(), preds, average="macro"))
        history.append({"epoch": ep + 1, "val_acc": va_acc, "val_macro_f1": va_f1})
        print(f"epoch {ep+1:2d}  loss={loss.item():.3f}  val_acc={va_acc:.4f}  "
              f"val_macro_f1={va_f1:.4f}  ({time.time()-t0:.0f}s)", flush=True)
        if args.save_checkpoint:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), ckpt_path)
            hist_path.write_text(json.dumps(history, indent=2))

    result = {"config": args.config, "history": history}
    if args.final_test:
        preds = predict(model, X[idx_te], pretrained)
        cyc_acc, cyc_f1, rec_acc, rec_f1 = cycle_and_recording_metrics(preds, y[idx_te].numpy(), rec[idx_te])
        result.update(test_cycle_acc=cyc_acc, test_cycle_macro_f1=cyc_f1,
                      test_recording_acc=rec_acc, test_recording_macro_f1=rec_f1)
        print(f"TEST (cycle-level)      acc={cyc_acc:.4f}  macro_f1={cyc_f1:.4f}", flush=True)
        print(f"TEST (recording-level)  acc={rec_acc:.4f}  macro_f1={rec_f1:.4f}", flush=True)
        if args.tta:
            preds_tta = predict_tta(model, X[idx_te], pretrained)
            t_cyc_acc, t_cyc_f1, t_rec_acc, t_rec_f1 = cycle_and_recording_metrics(
                preds_tta, y[idx_te].numpy(), rec[idx_te])
            result.update(test_cycle_acc_tta=t_cyc_acc, test_cycle_macro_f1_tta=t_cyc_f1,
                          test_recording_acc_tta=t_rec_acc, test_recording_macro_f1_tta=t_rec_f1)
            print(f"TEST (cycle-level, TTA)      acc={t_cyc_acc:.4f}  macro_f1={t_cyc_f1:.4f}", flush=True)
            print(f"TEST (recording-level, TTA)  acc={t_rec_acc:.4f}  macro_f1={t_rec_f1:.4f}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"cycle_sanity_{args.config}{'_final' if args.final_test else ''}.json"
    out.write_text(json.dumps(result, indent=2))
    print("wrote", out, flush=True)
    if args.save_checkpoint:
        ckpt = out.with_suffix(".pt")
        torch.save(model.state_dict(), ckpt)
        print("wrote", ckpt, flush=True)


if __name__ == "__main__":
    main()
