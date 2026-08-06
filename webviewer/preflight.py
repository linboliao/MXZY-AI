"""Deployment checks for the campus GPU worker."""

import importlib
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def required_pipeline_assets(normal=True):
    cancer_variant = "10x-normal" if normal else "10x"
    assets = [
        "PrePATH/presets/maixin.csv",
        "MIL_BASELINE/configs/cancer/CLAM_MB_MIL-h-optimus-1.yaml",
        "MIL_BASELINE/configs/gleason/CLAM_MB_MIL-h-optimus-1.yaml",
        "MIL_BASELINE/ckpts/gleason/best.pth",
        "ultralytics/runs/detect/yolo11s_0512/weights/last.pt",
        "ultralytics/runs/detect/yolo11s_0702/weights/last.pt",
        "ultralytics/runs/detect/cbam/weights/best.pt",
        "ultralytics/runs/detect/pki/weights/best.pt",
    ]
    assets.extend(
        f"MIL_BASELINE/ckpts/cancer/{cancer_variant}/best_f{fold}.pth"
        for fold in range(1, 6)
    )
    return tuple(assets)


def check_worker_runtime(normal=True):
    checks = []
    for module_name in ("torch", "openslide", "pandas", "geopandas", "h5py", "timm"):
        try:
            importlib.import_module(module_name)
            checks.append((True, f"Python 依赖 {module_name}"))
        except Exception as error:
            checks.append((False, f"Python 依赖 {module_name}: {error}"))

    try:
        torch = importlib.import_module("torch")
        available = bool(torch.cuda.is_available())
        detail = torch.cuda.get_device_name(0) if available else "未检测到 CUDA GPU"
        checks.append((available, f"CUDA: {detail}"))
    except Exception as error:
        checks.append((False, f"CUDA: {error}"))

    for relative_path in required_pipeline_assets(normal=normal):
        path = PROJECT_ROOT / relative_path
        valid = path.is_file() and path.stat().st_size > 0
        checks.append((valid, f"模型资产 {relative_path}"))

    if os.getenv("HF_TOKEN"):
        checks.append((True, "HF_TOKEN 已配置"))
    else:
        checks.append((True, "HF_TOKEN 未配置；仅在 H-optimus-1 已缓存且可访问时可运行"))
    return checks


def print_checks(checks):
    for passed, message in checks:
        print(f"[{'OK' if passed else 'FAIL'}] {message}")
    return all(passed for passed, _message in checks)
