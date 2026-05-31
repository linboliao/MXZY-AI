import os

os.environ['HF_ENDPOINT'] = "https://hf-mirror.com"
os.environ['HF_HOME'] = r'.\PrePATH\models\ckpts\huggingface'
import torch

from pathlib import Path

import cv2
import numpy as np
import staintools
# import torch
import torchstain
from PIL import Image
from matplotlib import pyplot as plt
from torchvision.transforms import transforms
from wsi_normalizer import TorchVahadaneNormalizer, imread

script_dir = Path(__file__).resolve().parent
REF_IMG_PATH = str(script_dir / "target.png")


def visualize(org_img, stain_img):
    # 创建对比可视化
    plt.figure(figsize=(16, 8))

    # 原始图像（左侧）
    plt.subplot(1, 2, 1)
    plt.imshow(org_img)
    plt.axis('off')
    plt.title("原始图像")

    # 归一化图像（右侧）
    plt.subplot(1, 2, 2)
    plt.imshow(stain_img)
    plt.axis('off')
    plt.title("染色归一化结果")

    # 保存并显示结果
    plt.tight_layout()
    plt.savefig('normalization_comparison.png', bbox_inches='tight', dpi=120)
    plt.show()


class StainTools:
    def __init__(self, method='macenko'):
        """
            使用stains_tool 包进行染色归一化
            method: macenko, vahadane
        """
        print("初始化染色归一化参考图像...")

        try:
            ref_img = staintools.read_image(REF_IMG_PATH)
            self.ref_img = staintools.LuminosityStandardizer.standardize(ref_img)
            normalizer = staintools.StainNormalizer(method=method)
            normalizer.fit(ref_img)
            self.normalizer = normalizer
            print("染色归一化参考图像已加载")
        except Exception as e:
            print(f"参考图像加载失败: {e}")
            raise

    def __call__(self, img):
        img_np = np.array(img)
        try:
            img_np = self.normalizer.transform(img_np)
        except Exception as e:
            print(f"染色归一化失败: {e}")
        return Image.fromarray(img_np)


class WSINormalizer:
    def __init__(self, gpu=0):
        """
        wsi_normalizer
        """
        print("初始化染色归一化参考图像...")
        try:
            # 创建归一化器并拟合参考图像
            self.normalizer = TorchVahadaneNormalizer(device=f'cuda:{gpu}')
            self.normalizer.fit(imread(REF_IMG_PATH))
            print("染色归一化参考图像已加载")
        except Exception as e:
            print(f"参考图像加载失败: {e}")
            raise

    def __call__(self, img):
        # 将输入图像转换为NumPy数组
        img_np = np.array(img)
        try:
            # 执行染色归一化处理
            img_np = self.normalizer.transform(img_np)
        except Exception as e:
            print(f"染色归一化失败: {e}")
            img_np = img_np  # 失败时保持原图
        img2 = Image.fromarray(img_np)
        return img2

def scale_to_255(x):
    return x * 255.0

class TorchStain:
    def __init__(self):
        print("初始化染色归一化参考图像...")
        try:
            target = cv2.cvtColor(cv2.imread(REF_IMG_PATH), cv2.COLOR_BGR2RGB)
            self.tensor_transform = transforms.Compose([
                transforms.ToTensor(),
                transforms.Lambda(scale_to_255)
            ])
            target_tensor = self.tensor_transform(target).float()
            normalizer = torchstain.normalizers.MacenkoNormalizer(backend='torch')
            normalizer.fit(target_tensor)
            self.normalizer = normalizer
            print("染色归一化参考图像已加载")
        except Exception as e:
            print(f"参考图像加载失败: {e}")
            raise

    def __call__(self, img):
        source = np.array(img)
        source_tensor = self.tensor_transform(source).float()
        try:
            normalized_tensor = self.normalizer.normalize(source_tensor, stains=False)[0]
            normalized_tensor = torch.clamp(normalized_tensor, 0, 255)
            normalized_np = normalized_tensor.numpy().astype(np.uint8)
            pil_image = Image.fromarray(normalized_np)
        except Exception as e:
            pil_image = img

        return pil_image
