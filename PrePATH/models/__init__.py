"""Feature encoders used by the medical-image inference pipeline."""

import os


os.environ.setdefault("HF_HOME", os.path.join("PrePATH", "models", "ckpts", "huggingface"))

__all__ = ["list_models", "get_model", "get_custom_transformer"]

_IMPLEMENTED_MODELS = ("h-optimus-1",)


def list_models():
    """Return the feature encoders shipped with this inference-only branch."""
    print("The following models are implemented:")
    for model_name in _IMPLEMENTED_MODELS:
        print(model_name)
    return list(_IMPLEMENTED_MODELS)


def _require_supported_model(model_name):
    normalized_name = model_name.lower()
    if normalized_name not in _IMPLEMENTED_MODELS:
        supported = ", ".join(_IMPLEMENTED_MODELS)
        raise NotImplementedError(
            f"{model_name} is not included in this inference-only branch; "
            f"supported models: {supported}"
        )
    return normalized_name


def get_model(model_name, device, gpu_num, jit=False):
    """Build the feature encoder required by the pipeline."""
    del gpu_num, jit
    _require_supported_model(model_name)
    from models.h_optimus_1 import get_model as build_model

    return build_model(device)


def get_custom_transformer(model_name):
    """Build the matching image preprocessing transform."""
    _require_supported_model(model_name)
    from models.h_optimus_1 import get_trans

    return get_trans()
