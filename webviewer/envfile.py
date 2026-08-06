"""Minimal, dependency-free loader for deployment environment files."""

import os
from pathlib import Path


def load_env_file(path, *, override=False):
    """Load KEY=VALUE pairs without executing shell expressions."""
    if not path:
        return None
    env_path = Path(path).expanduser().resolve()
    if not env_path.is_file():
        raise FileNotFoundError(f"环境配置文件不存在: {env_path}")

    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{env_path}:{line_number} 缺少 '='")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            raise ValueError(f"{env_path}:{line_number} 环境变量名无效")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path
