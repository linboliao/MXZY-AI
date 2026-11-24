import os

WEIGHTS = "/NAS2/Data1/lbliao/Code-195/PrePATH/models/ckpts/mSTAR.bin"


def get_trans():
    from torchvision import transforms

    return transforms.Compose([
        transforms.Resize(224, antialias=True),
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    ])


def get_model(device):
    import timm
    import torch

    model = timm.create_model(
        "vit_large_patch16_224", img_size=224, patch_size=16,
        init_values=1e-5, num_classes=0, dynamic_img_size=True,
    )
    weights = os.getenv("MAIXIN_MSTAR_WEIGHTS", WEIGHTS)
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    return model.to(device).eval()
