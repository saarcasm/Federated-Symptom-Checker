"""
Skin lesion classifier using MobileNetV3-Small backbone.
"""

import torch
import torch.nn as nn
from opacus.validators import ModuleValidator
from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights


class _NoInplaceResidual(nn.Module):
    """Drop-in replacement for torchvision's InvertedResidual that avoids the
    in-place `result += input` skip-connection add, which breaks Opacus's
    per-sample-gradient backward hooks. A real nn.Module subclass (rather
    than a monkey-patched bound method) so it survives the pickling that
    ModuleValidator.fix() does when cloning the model."""
    def __init__(self, orig_block: nn.Module):
        super().__init__()
        self.block = orig_block.block
        self.use_res_connect = orig_block.use_res_connect

    def forward(self, input: torch.Tensor) -> torch.Tensor:
        result = self.block(input)
        if self.use_res_connect:
            result = result + input
        return result


def _replace_inverted_residuals(root: nn.Module) -> None:
    """Recursively replace every InvertedResidual submodule in place with
    _NoInplaceResidual, reusing (not copying) its underlying block so
    pretrained weights are preserved."""
    for name, child in list(root.named_children()):
        if type(child).__name__ == "InvertedResidual" and hasattr(child, "use_res_connect"):
            setattr(root, name, _NoInplaceResidual(child))
        else:
            _replace_inverted_residuals(child)


class SkinCNN(nn.Module):
    """
    CNN for Skin Lesion Classification.
    Uses MobileNetV3-Small backbone.
    Input: 224x224x3 RGB images
    Output: 7 HAM10000 classes
    """
    def __init__(self, num_classes: int = 7):
        super(SkinCNN, self).__init__()
        # Load pretrained MobileNetV3-Small
        weights = MobileNet_V3_Small_Weights.DEFAULT
        self.backbone = mobilenet_v3_small(weights=weights)

        # Replace classifier head
        # MobileNetV3-Small features output 576 channels before classifier
        in_features = 576
        self.backbone.classifier = nn.Sequential(
            nn.Linear(in_features, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes)
        )

        # MobileNetV3's Hardswish/Hardsigmoid/ReLU modules default to
        # inplace=True, which is incompatible with Opacus's per-sample
        # gradient backward hooks ("BackwardHookFunction is a view and is
        # being modified inplace"). Disable inplace everywhere so DP-SGD
        # training doesn't crash on every batch.
        for module in self.backbone.modules():
            if hasattr(module, "inplace"):
                module.inplace = False

        # torchvision's InvertedResidual.forward() also does an in-place
        # `result += input` for the skip connection, which trips the same
        # Opacus hook issue and isn't controlled by an `inplace` attribute.
        _replace_inverted_residuals(self.backbone)

        # Opacus can't compute per-sample gradients through BatchNorm (batch
        # statistics leak information across samples in a batch), so
        # federated/client.py replaces it with GroupNorm before local DP
        # training. That replacement must happen HERE, once, at construction
        # time rather than per-round inside fit() -- otherwise every freshly
        # instantiated client model starts with BatchNorm-shaped parameters
        # while the FedAvg-aggregated global weights are GroupNorm-shaped
        # (fewer tensors, different shapes), causing a state_dict shape
        # mismatch as soon as round 2 broadcasts the aggregated parameters.
        self.backbone = ModuleValidator.fix(self.backbone)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)

if __name__ == "__main__":
    model = SkinCNN()
    x = torch.randn(2, 3, 224, 224)
    out = model(x)
    print(f"SkinCNN Output shape: {out.shape} (Expected: 2, 7)")
    print(f"Number of parameters: {sum(p.numel() for p in model.parameters())}")
