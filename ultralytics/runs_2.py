import argparse
import json
import os
import stat
import shutil
import subprocess
import time
import traceback
import concurrent.futures
import pandas as pd
import openslide
from typing import Dict, List, Any, Optional

conda_path = r'C:\Users\MXZY-AI\.conda\envs'

work_dir = {
    'prepath': r'D:\Users\MXZY-AI\PycharmProjects\PrePATH',
    'ultralytics': r'D:\Users\MXZY-AI\PycharmProjects\ultralytics',
    'mil': r'D:\Users\MXZY-AI\PycharmProjects\MIL_BASELINE'
}


def run_command(p, command, task_name):
    """执行命令行任务并处理异常"""
    try:
        print(f'开始执行{task_name}任务')
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{p}"
        result = subprocess.run(
            command,
            cwd=p,
            env=env,
            check=True,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=72000
        )
        print(command)
        print(f"✅ [{task_name}] 执行成功")
        print(f"输出摘要: {result.stdout[:100]}...")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ [{task_name}] 执行失败 (code={e.returncode})\n错误信息: {e.stderr}")
        traceback.print_exc()
        return False
    except subprocess.TimeoutExpired:
        print(f"⏰ [{task_name}] 执行超时")
        traceback.print_exc()
        return False
    except FileNotFoundError:
        print(f"🔍 [{task_name}] 文件未找到")
        traceback.print_exc()
        return False


def generate_cls_csv(csv_dir, coord_dir, wsi_dir, num):
    """生成CSV分割文件（含两列：case_id 和 slide_id），均匀分成num份"""
    csv_path = os.path.join(csv_dir, 'csv')
    os.makedirs(csv_path, exist_ok=True)
    slides = []
    for root, dirs, files in os.walk(wsi_dir):
        for file in files:
            if file.endswith('.svs'):
                slides.append(file)
    base_names = [
        os.path.splitext(slide)[0] for slide in slides
        if os.path.exists(os.path.join(coord_dir, 'patches', f'{os.path.splitext(slide)[0]}.h5'))
    ]

    df = pd.DataFrame({"case_id": base_names, "slide_id": base_names})
    total_rows = len(df)

    part_size = total_rows // num
    remainder = total_rows % num

    csv_files = []
    start_index = 0

    for i in range(num):
        current_part_size = part_size + (1 if i < remainder else 0)
        end_index = start_index + current_part_size

        part_df = df.iloc[start_index:end_index]
        part_csv_path = os.path.join(csv_path, f'part_{i}.csv')
        part_df.to_csv(part_csv_path, index=False)

        csv_files.append(part_csv_path)
        start_index = end_index

    return csv_files


def get_patch_csv(args):
    wsi_format = {'svs', 'ndpi', 'tif', 'tiff', 'mrxs'}
    output_40 = os.path.join(args.coord_dir, "40x_slides.csv")
    output_20 = os.path.join(args.coord_dir, "20x_slides.csv")
    output_10 = os.path.join(args.coord_dir, "10x_slides.csv")

    slides_40 = []
    slides_20 = []
    slides_10 = []

    for root, dirs, filenames in os.walk(args.wsi_dir):
        for filename in filenames:
            postfix = filename.split(".")[-1].lower()
            if postfix in wsi_format:
                slide_path = os.path.join(root, filename)
                try:
                    with openslide.OpenSlide(slide_path) as wsi:
                        objective = wsi.properties.get('openslide.objective-power', '20')
                        objective_int = int(objective)
                        if objective_int == 40:
                            slides_40.append(slide_path)
                        elif objective_int == 20:
                            slides_20.append(slide_path)
                        elif objective_int == 10:
                            slides_10.append(slide_path)
                except Exception as e:
                    print(f"处理文件 {slide_path} 时出错: {e}")
                    continue

    pd.DataFrame({'slide_path': slides_40}).to_csv(output_40, index=False, encoding='utf-8')
    pd.DataFrame({'slide_path': slides_20}).to_csv(output_20, index=False, encoding='utf-8')
    pd.DataFrame({'slide_path': slides_10}).to_csv(output_10, index=False, encoding='utf-8')

    return (output_40, output_20, output_10), ('1792', '896', '448')


def create_patch_cls(args):
    path = work_dir.get('prepath')
    coord_dir = os.path.join(args.output_dir, 'patches_wsi')
    os.makedirs(coord_dir, exist_ok=True)
    args.coord_dir = coord_dir
    csvs, patch_sizes = get_patch_csv(args)
    for csv, patch_size in zip(csvs, patch_sizes):
        patch_cmd = [
            os.path.join(conda_path, "clam/python.exe"),
            os.path.join(path, 'create_patches_fp.py'),
            "--source", args.wsi_dir,
            "--csv_path", csv,
            "--save_dir", coord_dir,
            "--preset", "maixin.csv",
            "--patch_level", '0',
            "--patch_size", patch_size,
            "--step_size", patch_size,
            "--wsi_format", 'svs;kfb',
            "--seg", "--patch", "--stitch", "--use_mp"
        ]
        if not run_command(path, patch_cmd, f"WSI生成 0 {patch_size} coords"):
            return False


def extract_features(csv_path, path, args, conda_path, coord_dir):
    """处理单个CSV文件的函数，用于并行执行"""
    feat_dir = os.path.join(args.output_dir, 'feat_wsi')
    task_name = f"WSI特征提取_{os.path.basename(csv_path)}"
    print(csv_path)
    feat_cmd = [
        os.path.join(conda_path, "clam/python.exe"),
        os.path.join(path, 'extract_features_fp_fast.py'),
        "--data_coors_dir", coord_dir,
        "--data_slide_dir", args.wsi_dir,
        "--slide_ext", '.svs;.kfb',
        "--csv_path", csv_path,
        "--feat_dir", feat_dir.replace('\\', '/'),
        "--batch_size", '48',
        "--model", args.model,
    ]

    return run_command(path, feat_cmd, task_name)


def extract_features_parallel(args):
    prepath = work_dir.get('prepath')
    coord_dir = os.path.join(args.output_dir, 'patches_wsi')

    csv_paths = generate_cls_csv(args.output_dir, coord_dir, args.wsi_dir, 2)
    csv_paths = [p for p in csv_paths if os.path.exists(p)]
    if not csv_paths: return False

    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as executor:
        future_to_csv = {executor.submit(extract_features, p, prepath, args, conda_path, coord_dir): p for p in
                         csv_paths}
        for future in concurrent.futures.as_completed(future_to_csv):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"处理失败: {future_to_csv[future]}, 错误: {e}")

    return len(results) > 0


def generate_yolo_csv(csv_path, output_dir, num_parts=2):
    csv_output_dir = os.path.join(output_dir, 'csv/yolo')
    os.makedirs(csv_output_dir, exist_ok=True)

    df = pd.read_csv(csv_path)

    if 'prediction' not in df.columns:
        raise ValueError(f"CSV文件 {csv_path} 中未找到'prediction'列")

    filtered_df = df[df['prediction'] == 1].copy()
    total_rows = len(filtered_df)

    if total_rows == 0:
        print("未找到prediction=1的行，无需分割")
        return []

    part_size = total_rows // num_parts
    remainder = total_rows % num_parts

    csv_files = []
    start_index = 0

    for i in range(num_parts):
        current_part_size = part_size + (1 if i < remainder else 0)
        end_index = start_index + current_part_size

        part_df = filtered_df.iloc[start_index:end_index]
        part_csv_path = os.path.join(csv_output_dir, f'part_{i}.csv')
        part_df.to_csv(part_csv_path, index=False)

        csv_files.append(part_csv_path)
        start_index = end_index

    return csv_files


def run_yolo_task(path, coord_dir, args, csv_part_path):
    yolo_cmd = [
        os.path.join(conda_path, "ultralytics/python.exe"),
        os.path.join(path, 'infer/yolo2x.py'),
        "--model", 'yolo',
        "--task", 'detect',
        "--data_coors_dir", coord_dir,
        "--data_slide_dir", args.wsi_dir,
        "--csv_path", csv_part_path,
        "--ckpts",
        'runs/detect/yolo11s_0512/weights/best.pt;runs/detect/yolo11s_0702/weights/best.pt;runs/detect/cbam/weights/best.pt;runs/detect/pki/weights/best.pt',
        "--slide_ext", '.kfb;.svs',
        "--batch_size", '2',
        "--output_dir", os.path.join(args.output_dir, 'yolo'),
    ]
    return run_command(path, yolo_cmd, f"YOLO检测（{os.path.basename(csv_part_path)}）")


def run_yolo(args):
    """YOLO目标检测任务"""
    path = work_dir.get('prepath')
    coord_dir = os.path.join(args.output_dir, 'patches_0_2048')
    patch_cmd = [
        os.path.join(conda_path, "clam/python.exe"),
        os.path.join(path, 'create_patches_fp.py'),
        "--source", args.wsi_dir,
        "--save_dir", coord_dir,
        "--preset", "maixin.csv",
        "--patch_level", '0',
        "--patch_size", '2048',
        "--step_size", '2048',
        "--wsi_format", 'svs;kfb',
        "--seg", "--patch", "--stitch", "--use_mp"
    ]
    if not run_command(path, patch_cmd, "WSI生成 0 2048 coords"):
        return False
    path = work_dir.get('ultralytics')
    # yolo_cmd = [
    #     os.path.join(conda_path, "ultralytics/python.exe"),
    #     os.path.join(path, 'infer/yolo2x.py'),
    #     "--model", 'yolo',
    #     "--task", 'detect',
    #     "--data_coors_dir", coord_dir,
    #     "--data_slide_dir", args.wsi_dir,
    #     "--csv_path", args.csv_path,
    #     "--ckpts",
    #     'runs/detect/yolo11s_0512/weights/best.pt;runs/detect/yolo11s_0702/weights/best.pt;runs/detect/cbam/weights/best.pt;runs/detect/pki/weights/best.pt',
    #     "--slide_ext", '.kfb;.svs',
    #     "--batch_size", '2',
    #     "--output_dir", os.path.join(args.output_dir, 'yolo'),
    # ]
    split_csv_files = generate_yolo_csv(args.csv_path, args.output_dir, num_parts=2)
    if not split_csv_files:
        return None  # 没有需要处理的文件

    # 定义YOLO任务执行函数

    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as executor:

        futures = [executor.submit(run_yolo_task, path, coord_dir, args, csv_file) for csv_file in split_csv_files]

        # 等待任务完成并处理结果
        for future in futures:
            try:
                result = future.result()
                print(f"任务完成: {result}")
            except Exception as e:
                print(f"任务执行出错: {str(e)}")
                return False
    return True
    # yolo_cmd = [
    #     os.path.join(conda_path, "ultralytics/python.exe"),
    #     os.path.join(path, 'infer/yolo_detect.py'),
    #     "--slide_dir", args.wsi_dir,
    #     "--output_dir",  os.path.join(args.output_dir, 'yolo')
    # ]
    # if not run_command(path, yolo_cmd, "YOLO检测"):
    #     return False
    # path = work_dir.get('ultralytics')
    # yolo_cmd = [
    #     os.path.join(conda_path, "ultralytics/python.exe"),
    #     os.path.join(path, 'infer/yolo2x.py'),
    #     "--model", 'yolo',
    #     "--task", 'segment',
    #     "--data_coors_dir", coord_dir,
    #     "--data_slide_dir", args.wsi_dir,
    #     "--ckpts", 'runs/segment/yolo12n/weights/best.pt',
    #     "--slide_ext", '.kfb;.svs',
    #     "--batch_size", '8',
    #     "--output_dir", os.path.join(args.output_dir, 'yolo'),
    # ]
    # if not run_command(path, yolo_cmd, "YOLO分割"):
    #     return False
    # path = work_dir.get('ultralytics')
    # yolo_cmd = [
    #     os.path.join(conda_path, "ultralytics/python.exe"),
    #     os.path.join(path, 'infer/merger.py'),
    #     "--input_dir", os.path.join(args.output_dir, 'yolo'),
    #     "--output_dir", os.path.join(args.output_dir, 'yolo'),
    # ]
    # return run_command(path, yolo_cmd, "合并")


def gen_test_csv(args):
    test_csv = os.path.join(args.output_dir, 'test.csv')
    if os.path.exists(test_csv):
        os.remove(test_csv)
    feat_dir = os.path.join(args.output_dir, f'feat_wsi/pt_files/{args.model}')
    feat_files = [entry.path for entry in os.scandir(feat_dir)]
    # feat_files = [os.path.join(feat_dir, f) for f in os.listdir(feat_dir)]
    df = pd.DataFrame({
        "test_slide_path": feat_files,
        "test_label": [0 for _ in range(len(feat_files))],
    })
    df.to_csv(test_csv, index=False)
    return test_csv


from collections import defaultdict


def merge_predictions_by_voting(output_dir, model_indices=[0, 1, 2, 3]):
    """
    合并多个模型的预测结果，采用投票方式（多数表决）

    Args:
        output_dir: 根输出目录（包含cancer子目录）
        model_indices: 模型索引列表，默认[0,1,2,3,4]对应cancer/0到cancer/4

    Returns:
        合并后的DataFrame（包含slide_id和最终prediction）
    """
    # 存储每个slide_id的所有预测结果
    slide_predictions = defaultdict(list)

    # 读取每个模型的结果文件
    for idx in model_indices:
        # 构建结果文件路径
        result_dir = os.path.join(output_dir, f'cancer/{idx}')
        result_file = os.path.join(result_dir, 'Infer_Result_CLAM_MB_MIL.csv')

        # 检查文件是否存在
        if not os.path.exists(result_file):
            raise FileNotFoundError(f"模型{idx}的结果文件不存在: {result_file}")

        # 读取CSV文件
        df = pd.read_csv(result_file)

        # 检查必要的列是否存在
        required_cols = ['slide_id', 'prediction']
        if not set(required_cols).issubset(df.columns):
            raise ValueError(f"结果文件{result_file}缺少必要列，需要: {required_cols}")

        # 收集每个slide_id的预测结果
        for _, row in df.iterrows():
            slide_id = row['slide_id']
            prediction = row['prediction']
            # 确保prediction是整数（处理可能的浮点型1.0/0.0）
            slide_predictions[slide_id].append(int(prediction))

    # 进行投票（多数表决）
    merged_results = []
    for slide_id, preds in slide_predictions.items():
        # 统计0和1的票数
        count_0 = preds.count(0)
        count_1 = preds.count(1)

        # 多数表决（若票数相等，默认倾向于1，可根据需求调整）
        final_pred = 1 if count_1 >= count_0 else 0
        merged_results.append({
            'slide_id': slide_id,
            'prediction': final_pred,
            'votes_0': count_0,  # 可选：保留票数统计
            'votes_1': count_1
        })

    # 转换为DataFrame并排序
    merged_df = pd.DataFrame(merged_results)
    merged_df = merged_df[['slide_id', 'prediction', 'votes_0', 'votes_1']]  # 调整列顺序
    merged_df = merged_df.sort_values(by='slide_id').reset_index(drop=True)

    # 保存合并结果到根目录
    output_file = os.path.join(output_dir, 'cancer', 'merged_voting_result.csv')
    merged_df.to_csv(output_file, index=False)
    print(f"投票合并结果已保存至: {output_file}")

    return merged_df


def run_cls(args):
    path = work_dir.get('mil')

    cancer_dir = os.path.join(args.output_dir, 'cancer/0')
    test_cmd = [
        os.path.join(conda_path, f'clam/python.exe'),
        os.path.join(path, 'infer_mil.py'),
        "--yaml_path", os.path.join(path, f'configs/cancer/CLAM_MB_MIL-{args.model}.yaml'),
        "--test_dataset_csv", args.test_csv,
        "--model_weight_path", os.path.join(path, 'ckpts/cancer/best_f1.pth'),
        "--test_log_dir", cancer_dir
    ]
    if not run_command(path, test_cmd, "癌症诊断"):
        return False
    cancer_dir = os.path.join(args.output_dir, 'cancer/1')
    test_cmd = [
        os.path.join(conda_path, f'clam/python.exe'),
        os.path.join(path, 'infer_mil.py'),
        "--yaml_path", os.path.join(path, f'configs/cancer/CLAM_MB_MIL-{args.model}.yaml'),
        "--test_dataset_csv", args.test_csv,
        "--model_weight_path", os.path.join(path, 'ckpts/cancer/best_f3.pth'),
        "--test_log_dir", cancer_dir
    ]
    if not run_command(path, test_cmd, "癌症诊断"):
        return False
    cancer_dir = os.path.join(args.output_dir, 'cancer/2')
    test_cmd = [
        os.path.join(conda_path, f'clam/python.exe'),
        os.path.join(path, 'infer_mil.py'),
        "--yaml_path", os.path.join(path, f'configs/cancer/CLAM_MB_MIL-{args.model}.yaml'),
        "--test_dataset_csv", args.test_csv,
        "--model_weight_path", os.path.join(path, 'ckpts/cancer/best_f5.pth'),
        "--test_log_dir", cancer_dir
    ]
    if not run_command(path, test_cmd, "癌症诊断"):
        return False
    cancer_dir = os.path.join(args.output_dir, 'cancer/3')
    test_cmd = [
        os.path.join(conda_path, f'clam/python.exe'),
        os.path.join(path, 'infer_mil.py'),
        "--yaml_path", os.path.join(path, f'configs/cancer/CLAM_MB_MIL-{args.model}.yaml'),
        "--test_dataset_csv", args.test_csv,
        "--model_weight_path", os.path.join(path, 'ckpts/cancer/last_f4.pth'),
        "--test_log_dir", cancer_dir
    ]
    if not run_command(path, test_cmd, "癌症诊断"):
        return False
    # cancer_dir = os.path.join(args.output_dir, 'cancer/4')
    # test_cmd = [
    #     os.path.join(conda_path, f'clam/python.exe'),
    #     os.path.join(path, 'infer_mil.py'),
    #     "--yaml_path", os.path.join(path, f'configs/cancer/CLAM_MB_MIL-{args.model}.yaml'),
    #     "--test_dataset_csv", args.test_csv,
    #     "--model_weight_path", os.path.join(path, 'ckpts/cancer/last_f4.pth'),
    #     "--test_log_dir", cancer_dir
    # ]
    # if not run_command(path, test_cmd, "癌症诊断"):
    #     return False
    merge_predictions_by_voting(args.output_dir)


def run_isup(args):
    path = work_dir.get('mil')

    isup_dir = os.path.join(args.output_dir, 'isup')

    test_cmd = [
        os.path.join(conda_path, f'clam/python.exe'),
        os.path.join(path, 'infer_mil.py'),
        "--yaml_path", os.path.join(path, f'configs/isup/CLAM_MB_MIL-{args.model}.yaml'),
        "--test_dataset_csv", args.test_csv,
        "--model_weight_path", os.path.join(path, 'ckpts/isup/best.pth'),
        "--test_log_dir", isup_dir
    ]
    return run_command(path, test_cmd, "isup 诊断")


def run_gleason(args):
    path = work_dir.get('mil')

    isup_dir = os.path.join(args.output_dir, 'gleason')

    test_cmd = [
        os.path.join(conda_path, f'clam/python.exe'),
        os.path.join(path, 'infer_mil.py'),
        "--yaml_path", os.path.join(path, f'configs/gleason/CLAM_MB_MIL-{args.model}.yaml'),
        "--test_dataset_csv", args.test_csv,
        "--model_weight_path", os.path.join(path, 'ckpts/gleason/best.pth'),
        "--test_log_dir", isup_dir
    ]
    return run_command(path, test_cmd, "gleason 诊断")


grade_mapping = {
    0: "3+3",
    1: "3+4",
    2: "4+3",
    3: "4+4",
    4: "3+5",
    5: "4+5",
    6: "5+4",
    7: "5+5"
}
isup_mapping = {
    "3+3": 1,
    "3+4": 2,
    "4+3": 3,
    "4+4": 4,
    "3+5": 4,
    "5+3": 4,
    "4+5": 5,
    "5+4": 5,
    "5+5": 5

}


def execute_phase_parallel(tasks, task_names, args, max_workers=2):
    """并行执行阶段任务"""
    print(f"🚀 开始并行执行 {len(tasks)} 个任务: {', '.join(task_names)}")

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务到执行器
        future_to_task = {executor.submit(task, args): name for task, name in zip(tasks, task_names)}

        results = {}
        # 等待所有任务完成并收集结果
        for future in concurrent.futures.as_completed(future_to_task):
            task_name = future_to_task[future]
            try:
                result = future.result()
                results[task_name] = result
                print(f"✅ [{task_name}] 执行完成")
            except Exception as e:
                results[task_name] = False
                print(f"❌ [{task_name}] 执行失败: {e}")

    return results


def run_medical_image_pipeline(
        # 路径配置参数
        wsi_dir: str,
        output_dir: str,
        slide_list=None,

        patch_level: int = 0,
        wsi_format: str = "svs;kfb",
        model: str = "h-optimus-1",
) -> Dict[str, Any]:
    """
    执行医学图像处理流水线

    Args:
        wsi_dir: WSI图像目录，默认为第一批数据路径
        slide_list: slide列表，使用分号分隔的字符串
        output_dir: 合并结果输出目录
        patch_level: 提取层级，默认为0
        wsi_format: slide格式，默认为'svs;kfb'
        model: 基础模型，默认为'h-optimus-1'

    Returns:
        包含执行结果和统计信息的字典
    """
    args = argparse.Namespace()
    args.wsi_dir = wsi_dir
    args.slide_list = slide_list
    args.output_dir = output_dir
    args.patch_level = patch_level
    args.wsi_format = wsi_format
    args.model = model

    if slide_list:
        slide_list_items = slide_list.split(';')
        tmp_dir = os.path.join(output_dir, 'tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        for slide in slide_list_items:
            shutil.copy(os.path.join(wsi_dir, slide), tmp_dir)
        args.wsi_dir = tmp_dir

    all_results = {}
    execution_stats = {}
    st = time.time()

    try:
        # 阶段1：并行执行 run_wsi_task 和 run_yolo
        phase1_tasks = [run_wsi_task, run_yolo]
        phase1_names = ["特征提取", "YOLO检测"]

        phase1_results = execute_phase_parallel(
            phase1_tasks, phase1_names, args, max_workers=2,
        )
        all_results.update(phase1_results)

        phase1_time = time.time() - st
        execution_stats["phase1_time"] = phase1_time
        print(f"⏱️ 阶段1执行时间: {phase1_time:.2f}秒")

        # 生成测试CSV
        st_csv = time.time()
        args.test_csv = gen_test_csv(args)
        csv_gen_time = time.time() - st_csv
        execution_stats["csv_gen_time"] = csv_gen_time
        print(f"⏱️ CSV生成时间: {csv_gen_time:.2f}秒")

        # 阶段2：并行执行 run_cls, run_isup, run_gleason
        st_phase2 = time.time()
        phase2_tasks = [run_cls, run_isup, run_gleason]
        phase2_names = ["癌症诊断", "ISUP诊断", "Gleason诊断"]

        phase2_results = execute_phase_parallel(
            phase2_tasks, phase2_names, args, max_workers=3,
        )
        all_results.update(phase2_results)

        phase2_time = time.time() - st_phase2
        execution_stats["phase2_time"] = phase2_time
        print(f"⏱️ 阶段2执行时间: {phase2_time:.2f}秒")

        # 总执行时间
        total_time = phase1_time + csv_gen_time + phase2_time
        execution_stats["total_time"] = total_time
        print(f"⏱️ 总执行时间: {total_time:.2f}秒")

        # 生成结果文件
        if all_results.get("癌症诊断", True):
            _generate_result_files(output_dir)

        return {
            "success": True,
            "results": all_results,
            "statistics": execution_stats,
            "output_dir": output_dir
        }

    except Exception as e:
        print(f"❌ 流水线执行失败: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "statistics": execution_stats
        }


def _generate_result_files(output_dir: str) -> None:
    """生成最终的结果文件"""
    result_json = os.path.join(output_dir, 'exist_cancer.json')
    cancer_csv = os.path.join(output_dir, 'cancer/merged_voting_result.csv')
    tissue_csv = os.path.join(output_dir, 'yolo/area.csv')
    gleason_csv = os.path.join(output_dir, 'gleason/Infer_Result_CLAM_MB_MIL.csv')
    isup_csv = os.path.join(output_dir, 'isup/Infer_Result_CLAM_MB_MIL.csv')

    results = []

    # 读取各阶段结果CSV文件
    cancer_df = pd.read_csv(cancer_csv, dtype={'slide_id': str})
    tissue_df = pd.read_csv(tissue_csv, dtype={'slide_id': str})
    gleason_df = pd.read_csv(gleason_csv, dtype={'slide_id': str})
    isup_df = pd.read_csv(isup_csv, dtype={'slide_id': str})

    # 处理每个slide的结果
    for slide_id, pred in zip(cancer_df['slide_id'], cancer_df['prediction']):
        if pred == 0:
            typ = 'Benign'
        else:
            typ = 'Malignant'
        tissue = tissue_df[tissue_df['slide_id'].astype(str) == str(slide_id)]
        gleason = gleason_df[gleason_df['slide_id'].astype(str) == str(slide_id)]
        # isup = isup_df[isup_df['slide_id'].astype(str) == str(slide_id)]

        tissue_area = tissue['area'].iloc[0] if not tissue.empty else "N/A"
        gleason_grade = grade_mapping[gleason['prediction'].iloc[0]] if not gleason.empty else 'N/A'
        # isup_grade = isup_mapping[isup['prediction'].iloc[0]] if not isup.empty else 'N/A'
        isup_grade = isup_mapping[gleason_grade] if gleason_grade != 'N/A' else "N/A"

        result = {
            "filename": f'{slide_id}.geojson',
            "type": typ,
            "percentage": tissue_area,
            "Gleason": f"{gleason_grade}",
            "ISUP": f"{isup_grade}"
        }
        results.append(result)
    import geopandas as gpd
    for file in os.listdir(os.path.join(output_dir, 'yolo')):
        if file.endswith("-detect.geojson"):
            file_path = os.path.join(output_dir, 'yolo', file)
            # shutil.copy(file_path, os.path.join(output_dir, file))
            gdf = gpd.read_file(file_path)
            gdf = gdf[
                gdf['classification'].apply(
                    lambda x: json.loads(x.replace("'", '"')).get('name') == 'Malignant'
                )
            ]
            gdf.to_file(os.path.join(output_dir, file.replace('-detect.geojson', '.geojson')))
    # 读取或创建结果JSON文件
    try:
        with open(result_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"geojson_files": []}

    # 添加新结果
    # data['geojson_files'].extend(results)
    for new_result in results:
        # 查找是否已存在相同filename的记录
        found = False
        for i, existing_result in enumerate(data['geojson_files']):
            if existing_result['filename'] == new_result['filename']:
                # 更新已存在的记录
                data['geojson_files'][i] = new_result
                found = True
                break

        # 如果不存在，则添加新记录
        if not found:
            data['geojson_files'].append(new_result)

    # 写入结果文件
    with open(result_json, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


parser = argparse.ArgumentParser(description="医学图像处理流水线 v1.0")

# 路径参数组
path_group = parser.add_argument_group("路径配置")
path_group.add_argument("--wsi_dir", type=str, default=r"D:\测试病例(100例)", help="WSI图像目录")
path_group.add_argument("--slide_list", type=str, help="slide 列表，使用;分隔")
path_group.add_argument("--output_dir", default=r"D:\测试病例(100例)\test1", help="合并结果输出目录")

# WSI参数组
wsi_group = parser.add_argument_group("WSI处理参数")
wsi_group.add_argument("--patch_level", type=int, default=0, help="提取层级")
wsi_group.add_argument("--wsi_format", default="svs;kfb", help="slide 格式，使用;分隔")
wsi_group.add_argument("--model", default="h-optimus-1", help="基础模型")

# 任务控制组
control_group = parser.add_argument_group("任务控制")
control_group.add_argument("-j", "--jobs", type=int, default=-1, help="并行任务数（-1=自动使用所有核心）")


def handle_remove_readonly(func, path, exc_info):
    """处理只读文件的删除回调"""
    os.chmod(path, stat.S_IWRITE)  # 去除只读属性
    func(path)


if __name__ == "__main__":
    try:
        args = parser.parse_args()
        print(args)
        if args.slide_list:
            slide_list = args.slide_list.split(';')
            tmp_dir = os.path.join(args.output_dir, 'tmp')
            os.makedirs(tmp_dir, exist_ok=True)
            for slide in slide_list:
                shutil.copy(os.path.join(args.wsi_dir, slide), tmp_dir)
            args.wsi_dir = tmp_dir

        all_results = {}
        st = time.time()
        # run_patch(args)
        phase1_tasks = [run_wsi_task]
        phase1_names = ["特征提取"]

        phase1_results = execute_phase_parallel(phase1_tasks, phase1_names, args, max_workers=2)
        all_results.update(phase1_results)

        phase1_time = time.time() - st
        print(f"⏱️ 阶段1执行时间: {phase1_time:.2f}秒")

        # 生成测试CSV（必须在阶段1完成后执行）
        st = time.time()
        args.test_csv = gen_test_csv(args)
        csv_gen_time = time.time() - st
        print(f"⏱️ CSV生成时间: {csv_gen_time:.2f}秒")

        # 阶段2：并行执行 run_cls, run_isup, run_gleason
        st = time.time()
        phase2_tasks = [run_cls, run_isup, run_gleason]
        phase2_names = ["癌症诊断", "ISUP诊断", "Gleason诊断"]

        phase2_results = execute_phase_parallel(phase2_tasks, phase2_names, args, max_workers=3)
        all_results.update(phase2_results)
        args.csv_path = os.path.join(args.output_dir, 'cancer/merged_voting_result.csv')
        run_yolo(args)

        phase2_time = time.time() - st
        print(f"⏱️ 阶段2执行时间: {phase2_time:.2f}秒")

        # 总执行时间
        total_time = phase1_time + csv_gen_time + phase2_time
        print(f"⏱️ 总执行时间: {total_time:.2f}秒")

        if all_results.get("癌症诊断", True) and all_results.get("癌症诊断", True) and all_results.get("癌症诊断",
                                                                                                       True):
            result_json = os.path.join(args.output_dir, 'exist_cancer.json')
            cancer_csv = os.path.join(args.output_dir, 'cancer/merged_voting_result.csv')
            tissue_csv = os.path.join(args.output_dir, 'yolo/area.csv')
            gleason_csv = os.path.join(args.output_dir, 'gleason/Infer_Result_CLAM_MB_MIL.csv')
            isup_csv = os.path.join(args.output_dir, 'isup/Infer_Result_CLAM_MB_MIL.csv')

            results = []

            cancer_df = pd.read_csv(cancer_csv)
            tissue_df = pd.read_csv(tissue_csv)
            gleason_df = pd.read_csv(gleason_csv)
            isup_df = pd.read_csv(isup_csv)

            for slide_id, pred in zip(cancer_df['slide_id'], cancer_df['prediction']):
                if pred == 1:
                    type = "malignant"
                else:
                    type = "benign"
                tissue = tissue_df[tissue_df['slide_id'].astype(str) == str(slide_id)]
                gleason = gleason_df[gleason_df['slide_id'].astype(str) == str(slide_id)]
                isup = isup_df[isup_df['slide_id'].astype(str) == str(slide_id)]
                tissue = tissue['area'].iloc[0] if not tissue.empty else "N/A"
                gleason = grade_mapping[gleason['prediction'].iloc[0]] if not gleason.empty else 'N/A'
                isup = grade_mapping[isup['prediction'].iloc[0]] if not isup.empty else 'N/A'
                result = {
                    "filename": f'{slide_id}.geojson',
                    "type": type,
                    "percentage": tissue,
                    "Gleason": f"{gleason};ISUP: {isup}"
                }
                results.append(result)
            import geopandas as gpd

            for file in os.listdir(os.path.join(args.output_dir, 'yolo')):
                if file.endswith('_detect.geojson') or file.endswith('_segment.geojson'):
                    continue
                if file.endswith(".geojson"):
                    file_path = os.path.join(args.output_dir, 'yolo', file)

                    gdf = gpd.read_file(file_path)
                    gdf = gdf[
                        gdf['classification'].apply(
                            lambda x: json.loads(x.replace("'", '"')).get('name') == 'Malignant'
                        )
                    ]
                    gdf.to_file(os.path.join(args.output_dir, file))
            # 读取或创建结果JSON文件
            try:
                with open(result_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except FileNotFoundError:
                data = {"geojson_files": []}

            # 添加新结果
            # data['geojson_files'].extend(results)
            for new_result in results:
                # 查找是否已存在相同filename的记录
                found = False
                for i, existing_result in enumerate(data['geojson_files']):
                    if existing_result['filename'] == new_result['filename']:
                        # 更新已存在的记录
                        data['geojson_files'][i] = new_result
                        found = True
                        break

                # 如果不存在，则添加新记录
                if not found:
                    data['geojson_files'].append(new_result)

            # 写入结果文件
            with open(result_json, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)


    finally:
        pass
        # shutil.rmtree(tmp_dir, onerror=handle_remove_readonly)
        # print(f"\n已成功删除文件夹: {tmp_dir}")
