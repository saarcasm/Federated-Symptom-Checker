import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import os
import json
import flwr as fl
import torch
import pandas as pd
import numpy as np

from data.partition import create_client_dataloaders, create_tabular_test_loader
from federated.dp_config import DPConfig, create_dp_config
from federated.client import create_client_fn
from federated.strategy import FedSymptomStrategy
from federated.server import create_server_config, get_evaluate_fn

def main():
    parser = argparse.ArgumentParser(description="Federated Symptom Checker Simulation")
    parser.add_argument("--model", type=str, required=True, choices=["symptom_mlp", "skin_cnn", "respiratory_cnn"])
    parser.add_argument("--dataset", type=str, required=True, choices=["tabular", "skin", "respiratory"])
    parser.add_argument("--num_clients", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--local_epochs", type=int, default=3)
    parser.add_argument("--epsilon", type=float, default=2.0, help="target epsilon, inf means no DP")
    parser.add_argument("--delta", type=float, default=None, help="target delta; defaults to 1/n per client if unset. Pass 1e-5 to match the paper's Table II.")
    parser.add_argument("--max_grad_norm", type=float, default=1.0)
    parser.add_argument("--use_fedprox", action="store_true")
    parser.add_argument("--mu", type=float, default=0.01)
    parser.add_argument("--alpha", type=float, default=0.5, help="Dirichlet alpha for non-IID")
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--device", type=str, default="auto", choices=["cuda", "cpu", "auto"])
    parser.add_argument("--output_dir", type=str, default="results")
    
    args = parser.parse_args()
    
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Starting simulation on {device}")

    # 1. Load and partition dataset
    try:
        client_dataloaders = create_client_dataloaders(
            dataset_name=args.dataset,
            num_clients=args.num_clients,
            batch_size=args.batch_size,
            alpha=args.alpha
        )
    except Exception as e:
        print(f"Warning: Failed to load real data ({e}), using dummy data for compilation testing.")
        # Dummy fallback for compilation
        class DummyDataset(torch.utils.data.Dataset):
            def __len__(self): return 100
            def __getitem__(self, idx): return torch.randn(3, 224, 224), 0
        dl = torch.utils.data.DataLoader(DummyDataset(), batch_size=args.batch_size)
        client_dataloaders = [(dl, dl) for _ in range(args.num_clients)]

    # Server-side evaluation must run against a single, global, held-out
    # test set -- never a client's local val shard, which (a) is itself
    # part of the training data and (b) only reflects that one client's
    # non-IID slice (paper Section III-D: "held-out test set"). Only the
    # tabular branch has this real held-out split wired up end to end;
    # skin/respiratory fall back to a client's val set until their own
    # train/test split is built (paper Section V-D names this as future work).
    if args.dataset == 'tabular':
        test_loader = create_tabular_test_loader(batch_size=args.batch_size)
    else:
        test_loader = client_dataloaders[0][1]

    # Model dimensions must come from the actual data, not a model class's
    # hardcoded constructor defaults -- those can silently drift out of
    # sync with the real dataset's shape. For symptom_mlp specifically,
    # input_dim/num_classes are derived here from the held-out test set
    # (the one tensor that always holds the FULL, unpartitioned label set).
    model_kwargs = {}
    if args.dataset == 'tabular':
        test_ds = test_loader.dataset
        model_kwargs = {
            'input_dim': test_ds.tensors[0].shape[1],
            'num_classes': int(torch.unique(test_ds.tensors[1]).numel()),
        }

    # DP config template: only target_epsilon/target_delta/max_grad_norm/
    # enabled are used from this. The actual noise multiplier is computed
    # PER CLIENT inside federated/client.py's create_client_fn, from each
    # client's own shard size -- not from an average across clients -- so
    # clients with smaller shards get a proportionally larger noise
    # multiplier for the same target epsilon (paper Section III-C).
    if args.epsilon == float('inf'):
        dp_config = DPConfig(target_epsilon=float('inf'), target_delta=0.0,
                              max_grad_norm=args.max_grad_norm, noise_multiplier=0.0, enabled=False)
    else:
        dp_config = DPConfig(target_epsilon=args.epsilon, target_delta=args.delta,
                              max_grad_norm=args.max_grad_norm, noise_multiplier=0.0, enabled=True)

    # 2. Create client function
    client_fn = create_client_fn(
        model_name=args.model,
        client_dataloaders=client_dataloaders,
        local_epochs=args.local_epochs,
        dp_config=dp_config,
        device=device,
        model_kwargs=model_kwargs
    )

    # 3. Create strategy
    eval_fn = get_evaluate_fn(args.model, test_loader, device, model_kwargs=model_kwargs)
    
    strategy = FedSymptomStrategy(
        use_fedprox=args.use_fedprox,
        mu=args.mu,
        track_communication=True,
        checkpoint_dir=str(out_dir / "checkpoints"),
        model_name=args.model,
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=args.num_clients,
        min_available_clients=args.num_clients,
        evaluate_fn=eval_fn
    )

    # 4. Run simulation
    history = fl.simulation.start_simulation(
        client_fn=client_fn,
        num_clients=args.num_clients,
        config=fl.server.ServerConfig(num_rounds=args.rounds),
        strategy=strategy,
        client_resources={"num_cpus": 1.0, "num_gpus": 1.0 if device.type == "cuda" else 0.0}
    )

    # 5. Save results as real, parseable JSON (str(dict) is not valid JSON --
    # it uses Python repr syntax, e.g. single quotes and tuples, which
    # json.load() cannot read back)
    results_file = out_dir / f"results_{args.model}_eps{args.epsilon}.json"
    res_dict = {
        "losses_distributed": history.losses_distributed,
        "metrics_distributed": history.metrics_distributed,
        "losses_centralized": history.losses_centralized,
        "metrics_centralized": history.metrics_centralized
    }
    with open(results_file, 'w') as f:
        json.dump(res_dict, f, indent=2, default=str)

    print(f"Simulation complete. Results saved to {out_dir}")

if __name__ == "__main__":
    main()
