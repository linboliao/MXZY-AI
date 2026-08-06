"""Isolated worker for ``run_medical_image_pipeline.py``."""

import argparse
import json
import multiprocessing
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from run_medical_image_pipeline import run_medical_image_pipeline


def main():
    parser = argparse.ArgumentParser(description="MXZY-AI Web Viewer pipeline worker")
    parser.add_argument("--wsi-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", default="h-optimus-1")
    parser.add_argument(
        "--normal",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用或关闭染色归一化",
    )
    args = parser.parse_args()

    pipeline_result = run_medical_image_pipeline(
        wsi_dir=args.wsi_dir,
        output_dir=args.output_dir,
        model=args.model,
        normal=args.normal,
        wsi_format="svs",
    )

    if isinstance(pipeline_result, dict) and not pipeline_result.get("success", False):
        print(
            f"流水线失败：{pipeline_result.get('error', '未提供错误信息')}",
            file=sys.stderr,
        )
        return 1

    result_path = Path(args.output_dir) / "exist_cancer.json"
    if not result_path.is_file():
        print("流水线未生成 exist_cancer.json", file=sys.stderr)
        return 2

    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"流水线结果文件无效：{error}", file=sys.stderr)
        return 3

    if not isinstance(result.get("geojson_files"), list):
        print("流水线结果缺少 geojson_files 列表", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    raise SystemExit(main())
