import os
import argparse
import traceback

from infer.yolo2_old import MultiGeoResults

import warnings

warnings.filterwarnings("ignore")

parser = argparse.ArgumentParser()
parser.add_argument('--ckpt', type=list, default=[
    rf'D:\Users\MXZY-AI\PycharmProjects\ultralytics\runs\detect\yolo11s_0512\weights\best.pt',
    rf'D:\Users\MXZY-AI\PycharmProjects\ultralytics\runs\detect\cbam\weights\best.pt',
    rf'D:\Users\MXZY-AI\PycharmProjects\ultralytics\runs\detect\yolo11s_0702\weights\best.pt',
    rf'D:\Users\MXZY-AI\PycharmProjects\ultralytics\runs\detect\pki\weights\best.pt'
])
parser.add_argument('--data_root', type=str, default=None, help='patch directory')
parser.add_argument('--gpu', type=str, default='0', help='patch directory')
parser.add_argument('--slide_dir', type=str, default=rf'D:\Dataset\test\slides', help='patch directory')
parser.add_argument('--output_dir', type=str, default=rf'D:\Dataset\test\yolo', help='output directory')
parser.add_argument('--patch_size', type=int, default=2048, help='patch size')
parser.add_argument('--infer_size', type=int, default=1536, help='patch size')
parser.add_argument('--slide_list', type=list, default=[])
parser.add_argument('--slide', type=str, default='', help='patch directory')
parser.add_argument('--show_level', type=int, default=0)

if __name__ == '__main__':
    try:
        args = parser.parse_args()
        os.makedirs(args.output_dir, exist_ok=True)
        # GeoResults(args).parallel_run()
        MultiGeoResults(args).parallel_run()
    except :
        traceback.print_exc()

    # GeoJSONProcessor(args).parallel_process()
    # TiffResults(args).parallel_run()
    # PicResults(args).parallel_run()
    # MdsResults(args).parallel_run()
    # LMResults(args).parallel_run()
    # KVResults(args).parallel_run()
