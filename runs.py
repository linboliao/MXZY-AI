import argparse
import json
import sys
import pandas as pd
import numpy as np
import openslide
import geopandas as gpd
from pathlib import Path
from collections import Counter
import os

os.environ["PYTHONIOENCODING"] = "utf-8"
# 动态路径设置
work_dir = {"prepath": "PrePATH", "ultralytics": "ultralytics", "mil": "MIL_BASELINE"}
for p in work_dir.values():
    if p not in sys.path: sys.path.insert(0, p)

import create_patches_fp, extract_features_fp_stains, extract_features_fp_fast
import infer_mil
from infer import yolo2x3

# 常量定义
GRADE_MAP = {i: v for i, v in enumerate(["3+3", "3+4", "4+3", "4+4", "3+5", "4+5", "5+4", "5+5"])}
ISUP_MAP = {"3+3": 1, "3+4": 2, "4+3": 3, "4+4": 4, "3+5": 4, "5+3": 4, "4+5": 5, "5+4": 5, "5+5": 5}


def get_map(path, col):
    if not os.path.exists(path):
        print(f"警告: 文件路径不存在 - {path}")
        # 返回一个空的字典
        return {}

    df = pd.read_csv(path, dtype={"slide_id": str})

    if "slide_id" not in df.columns or col not in df.columns:
        print(f"警告: CSV 中缺少必要的列 (slide_id 或 {col})")
        return {}

    return df.set_index("slide_id")[col].to_dict()


def run_wsi_patching(args):
    """按倍率分类并生成切片坐标"""
    patch_dir = Path(args.output_dir) / "patches_cls"
    patch_dir.mkdir(parents=True, exist_ok=True)

    # 倍率映射：倍率 -> (size)
    mag_config = {40: 896, 20: 448, 10: 224}
    results = {mag: [] for mag in mag_config}

    for path in Path(args.wsi_dir).glob("*"):
        if path.suffix.lower() in [".svs", ".ndpi", ".tif", ".tiff", ".mrxs"]:
            with openslide.OpenSlide(str(path)) as wsi:
                mag = int(wsi.properties.get("openslide.objective-power", 20))
                if mag in results: results[mag].append(str(path))

    for mag, size in mag_config.items():
        if not results[mag]: continue
        csv_path = patch_dir / f"{mag}x_slides.csv"
        pd.DataFrame({"slide_path": results[mag]}).to_csv(csv_path, index=False)

        # 执行任务
        create_patches_fp.main(argparse.Namespace(
            source=args.wsi_dir, csv_path=str(csv_path), save_dir=str(patch_dir),
            preset="maixin.csv", patch_level=0, patch_size=size, step_size=size,
            wsi_format="svs", seg=True, patch=True, stitch=True, use_mp=True, process_list=None, no_auto_skip=True,
        ))
    args.coord_dir = patch_dir


def generate_cls_csv(csv_dir, coord_dir, wsi_dir, num):
    """筛选有效切片并切分为 num 个 CSV 清单"""
    csv_out = Path(csv_dir) / 'csv'
    csv_out.mkdir(parents=True, exist_ok=True)

    # 获取有效病例列表
    valid_bases = [
        f.stem for f in Path(wsi_dir).glob("*.svs")
        if (Path(coord_dir) / 'patches' / f"{f.stem}.h5").exists()
           and (Path(coord_dir) / 'patches' / f"{f.stem}.h5").stat().st_size > 0
    ]

    # 切分 DataFrame 并保存
    df = pd.DataFrame({"case_id": valid_bases, "slide_id": valid_bases})
    csv_files = []

    for i, part_df in enumerate(np.array_split(df, max(1, num))):
        if not part_df.empty:
            path = csv_out / f'part_{i}.csv'
            part_df.to_csv(path, index=False)
            csv_files.append(str(path))
    return csv_files


def run_feature_extraction(args, num=0):
    """执行特征提取流水线"""
    feat_dir = Path(args.output_dir) / "feat_cls"
    coord_dir = Path(args.output_dir) / "patches_cls"

    worker = extract_features_fp_stains if args.normal else extract_features_fp_fast

    for csv in generate_cls_csv(feat_dir, coord_dir, args.wsi_dir, num):
        print(f"🧬 提取特征: {Path(csv).name}")
        worker.main(argparse.Namespace(
            data_coors_dir=coord_dir,
            data_slide_dir=args.wsi_dir,
            slide_ext='.svs',
            csv_path=csv,
            feat_dir=feat_dir,
            batch_size=48,
            model=args.model,
            custom_downsample=1,
            target_patch_size=-1,
            save_storage='no',
            ignore_partial='yes'
        ))


def run_cancer_inference(args):
    mil_path = Path(work_dir["mil"])
    ckpt = "10x-normal" if args.normal else "10x"
    out_dir = Path(args.output_dir) / "cancer"

    for i in range(5):
        fold_dir = out_dir / str(i)
        fold_dir.mkdir(parents=True, exist_ok=True)
        infer_mil.main(argparse.Namespace(
            yaml_path=mil_path / f"configs/cancer/CLAM_MB_MIL-{args.model}.yaml",
            test_dataset_csv=args.test_csv,
            model_weight_path=mil_path / f"ckpts/cancer/{ckpt}/best_f{i + 1}.pth",
            test_log_dir=str(fold_dir)
        ))

    # 投票汇总逻辑
    slide_preds = {}
    for i in range(5):
        df = pd.read_csv(out_dir / f"{i}/Infer_Result_CLAM_MB_MIL.csv", dtype={"slide_id": str})
        for sid, pred in zip(df["slide_id"], df["prediction"]):
            slide_preds.setdefault(sid, []).append(int(pred))

    merged = [{"slide_id": sid, "prediction": 1 if sum(p) >= len(p) / 2 else 0,
               "votes_0": p.count(0), "votes_1": p.count(1)} for sid, p in slide_preds.items()]
    pd.DataFrame(merged).to_csv(out_dir / "merged_voting_result.csv", index=False)


def run_gleason_inference(args):
    mil_path = Path(work_dir["mil"])
    output_dir = Path(args.output_dir) / "gleason"
    output_dir.mkdir(parents=True, exist_ok=True)

    task_args = argparse.Namespace(
        yaml_path=mil_path / f"configs/gleason/CLAM_MB_MIL-{args.model}.yaml",
        test_dataset_csv=str(args.test_csv),
        model_weight_path=mil_path / "ckpts/gleason/best.pth",
        test_log_dir=str(output_dir)
    )
    infer_mil.main(task_args)


def run_yolo_inference(args, csv_file):

    out_dir = Path(args.output_dir) / "yolo"
    out_dir.mkdir(parents=True, exist_ok=True)

    task_args = argparse.Namespace(
        slide_dir=args.wsi_dir,
        csv_path=csv_file,
        gpu=0,
        ckpts=";".join([
            "ultralytics/runs/detect/yolo11s_0512/weights/last.pt",
            "ultralytics/runs/detect/yolo11s_0702/weights/last.pt",
            "ultralytics/runs/detect/cbam/weights/best.pt",
            "ultralytics/runs/detect/pki/weights/best.pt"
        ]),
        patch_size=2048,
        infer_size=1536,
        output_dir=str(out_dir),
        show_level=0,
    )
    yolo2x3.main(task_args)


def analysis_report(output_dir):
    out = Path(output_dir)
    cancer_df = pd.read_csv(out / "cancer/merged_voting_result.csv", dtype={"slide_id": str})
    tissue_map = get_map(out / "yolo/area.csv", "area")
    gleason_map = get_map(out / "gleason/Infer_Result_CLAM_MB_MIL.csv", "prediction")

    results = {}
    for _, row in cancer_df.iterrows():
        sid = row["slide_id"]
        geo_path = out / "yolo" / f"{sid}-detect.geojson"
        num = 0
        if geo_path.exists():
            def is_malignant(val):
                if isinstance(val, dict):
                    return val.get('name') == 'Malignant'
                return False

            gdf = gpd.read_file(geo_path)
            gdf = gdf[gdf['classification'].apply(is_malignant)].copy()

            out_file = os.path.join(output_dir, f'{sid}.geojson')
            gdf.to_file(out_file, driver='GeoJSON')
            num = len(gdf)

        g_grade = GRADE_MAP.get(gleason_map.get(sid), "N/A")
        results[f"{sid}.geojson"] = {
            "filename": f"{sid}.geojson",
            "type": "Benign" if row["prediction"] == 0 or num == 0 else "Malignant",
            "percentage": tissue_map.get(sid, "N/A"),
            "Gleason": str(g_grade),
            "ISUP": str(ISUP_MAP.get(g_grade, "N/A")),
        }
    with open(out / "exist_cancer.json", "w", encoding="utf-8") as f:
        json.dump({"geojson_files": list(results.values())}, f, indent=2, ensure_ascii=False)


def run_medical_image_pipeline(wsi_dir: str, output_dir: str, **kwargs):
    """保持接口不变的调度器"""
    args = argparse.Namespace(wsi_dir=wsi_dir, output_dir=output_dir, **kwargs)

    run_wsi_patching(args)
    run_feature_extraction(args)

    # 构建测试清单
    feat_files = list((Path(output_dir) / "feat_cls/pt_files" / args.model).glob("*.pt"))
    args.test_csv = Path(output_dir) / "test.csv"
    pd.DataFrame({"test_slide_path": [str(f) for f in feat_files], "test_label": 0}).to_csv(args.test_csv, index=False)

    run_cancer_inference(args)
    run_gleason_inference(args)
    csv_path = Path(args.output_dir) / "cancer" / "merged_voting_result.csv"
    run_yolo_inference(args, str(csv_path))

    analysis_report(output_dir)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.set_start_method('spawn', force=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--wsi_dir", default=r"D:\Workspace\学习\迈新\AI VS 中级医生病灶识别\slides")
    parser.add_argument("--output_dir", default=r"D:\Workspace\学习\迈新\AI VS 中级医生病灶识别\result")
    parser.add_argument("--slide_list", default=None)
    parser.add_argument("--patch_level", type=int, default=0)
    parser.add_argument("--wsi_format", default="svs;kfb")
    parser.add_argument("--model", default="h-optimus-1")
    parser.add_argument("--normal", action="store_true")  # 用 action="store_true" 处理布尔开关

    args = parser.parse_args()

    run_medical_image_pipeline(**vars(args))
