import os
import shutil
import cv2
import numpy as np
from PIL import Image

base = r'F:\gleason patch\val'
IMAGES_DIR = base + '/images'
MASKS_DIR = base + '/masks'
LM_DIR = base + '/labelme'
TARGET_FOLDER = r'F:\gleason patch\val1'

# 确保目标文件夹存在
os.makedirs(os.path.join(TARGET_FOLDER, 'images'), exist_ok=True)
os.makedirs(os.path.join(TARGET_FOLDER, 'masks'), exist_ok=True)
os.makedirs(os.path.join(TARGET_FOLDER, 'labelme'), exist_ok=True)

# 定义不同类别的颜色（BGR格式）
CLASS_COLORS = {
    0: [0, 0, 0, 0],  # 背景：黑色透明
    1: [0, 0, 255, 128],  # 类别1：红色
    2: [0, 255, 0, 128],  # 类别2：绿色
    3: [255, 0, 0, 128],  # 类别3：蓝色
    4: [0, 255, 255, 128]  # 类别4：黄色
}

CLASS_LABELS = {
    0: 'bg',
    1: 'benign',
    2: 'grade 3',
    3: 'grade 4',
    4: 'grade 5'
}

# 获取所有图片文件名
image_files = [f for f in os.listdir(IMAGES_DIR) if f.endswith(('.jpg', '.png', '.jpeg', '.tif', '.tiff'))]
image_files.sort()


# 获取屏幕尺寸
def get_screen_resolution():
    """
    获取屏幕分辨率，用于自适应调整显示大小
    """
    try:
        # 尝试通过OpenCV获取屏幕信息
        screen_info = os.popen("xrandr 2>/dev/null | grep '*'").read().split()[0]
        if 'x' in screen_info:
            width, height = map(int, screen_info.split('x'))
            return width, height
    except:
        pass

    # 默认使用常见分辨率
    return 1920, 1080  # 默认Full HD


# 获取屏幕尺寸
SCREEN_WIDTH, SCREEN_HEIGHT = get_screen_resolution()
MAX_DISPLAY_WIDTH = SCREEN_WIDTH - 100
MAX_DISPLAY_HEIGHT = SCREEN_HEIGHT - 150
print(f"屏幕分辨率: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
print(f"最大显示尺寸: {MAX_DISPLAY_WIDTH}x{MAX_DISPLAY_HEIGHT}")


def resize_for_display(image, max_width=100, max_height=100, keep_aspect=True):
    """
    自适应调整图片大小以适合屏幕显示
    """
    if max_width is None:
        max_width = MAX_DISPLAY_WIDTH // 2
    if max_height is None:
        max_height = MAX_DISPLAY_HEIGHT

    h, w = image.shape[:2]

    if keep_aspect:
        # 保持宽高比
        scale = min(max_width / w, max_height / h, 1.0)
        new_w = int(w * scale)
        new_h = int(h * scale)
    else:
        new_w = min(w, max_width)
        new_h = min(h, max_height)

    if new_w != w or new_h != h:
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        return resized, scale
    return image, 1.0


def create_overlay(img, mask):
    """
    创建mask叠加图
    """
    overlay = img.copy().astype(np.float32)

    for class_id, color in CLASS_COLORS.items():
        if class_id == 0:  # 背景跳过
            continue
        mask_indices = mask == class_id
        if np.any(mask_indices):
            bgr_color = np.array(color[:3], dtype=np.float32)
            alpha = color[3] / 255.0

            for c in range(3):  # BGR三个通道
                overlay_channel = overlay[:, :, c]
                overlay_channel[mask_indices] = (overlay_channel[mask_indices] * (1 - alpha) +
                                                 bgr_color[c] * alpha)

    return overlay.astype(np.uint8)


def create_display_image(img, overlay, filename, i, total, mask):
    """
    创建要显示的合成图像
    """
    # 调整图片大小以适应显示
    max_single_width = 750
    img_resized, img_scale = resize_for_display(img, max_single_width, MAX_DISPLAY_HEIGHT)
    overlay_resized, overlay_scale = resize_for_display(overlay, max_single_width, MAX_DISPLAY_HEIGHT)

    # 确保两张图片高度一致
    max_height = max(img_resized.shape[0], overlay_resized.shape[0])

    # 创建空白画布
    combined_width = img_resized.shape[1] + overlay_resized.shape[1]
    combined = np.zeros((max_height, combined_width, 3), dtype=np.uint8)

    # 放置原图
    combined[0:img_resized.shape[0], 0:img_resized.shape[1]] = img_resized

    # 放置叠加图
    combined[0:overlay_resized.shape[0], img_resized.shape[1]:] = overlay_resized

    # 添加标题
    cv2.putText(combined, f'Original {filename}', (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    cv2.putText(combined, 'Mask Overlay', (img_resized.shape[1] + 10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)

    # 添加文件名和进度
    info_text = f'{filename} ({i + 1}/{total})'
    cv2.putText(combined, info_text, (10, combined.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    # 添加缩放比例信息
    if img_scale < 1.0:
        scale_text = f'Scale: {img_scale:.2%}'
        cv2.putText(combined, scale_text, (combined.shape[1] - 150, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)

    # 添加图例
    legend_y = 70
    legend_x = img_resized.shape[1] + 20

    for class_id in range(1, 5):  # 只显示类别1-4
        if np.any(mask == class_id):  # 只显示存在的类别
            bgr_color = tuple(int(c) for c in CLASS_COLORS[class_id][:3])

            # 绘制颜色方块
            cv2.rectangle(combined, (legend_x, legend_y - 15),
                          (legend_x + 20, legend_y), bgr_color, -1)
            cv2.rectangle(combined, (legend_x, legend_y - 15),
                          (legend_x + 20, legend_y), (255, 255, 255), 1)

            # 添加标签文本
            label_text = CLASS_LABELS[class_id]
            cv2.putText(combined, label_text, (legend_x + 25, legend_y - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)

            legend_y += 25

    # 添加操作提示
    # instruction_y = combined.shape[0] - 40
    # cv2.putText(combined, 'Press 1: Keep (skip)', (10, instruction_y),
    #             cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    # cv2.putText(combined, 'Other key: Move to new dataset', (10, instruction_y + 25),
    #             cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    return combined


# 创建可调整大小的窗口
cv2.namedWindow('Image Review Tool', cv2.WINDOW_NORMAL)
cv2.resizeWindow('Image Review Tool', min(MAX_DISPLAY_WIDTH, 1600), min(MAX_DISPLAY_HEIGHT, 900))

# 遍历每张图片
for i, filename in enumerate(image_files):
    print(f"\n处理进度: {i + 1}/{len(image_files)}")
    print(f"当前文件: {filename}")

    try:
        # 加载图片
        img_pil = Image.open(os.path.join(IMAGES_DIR, filename))

        # 转换为RGB
        if img_pil.mode in ['RGBA', 'LA', 'P']:
            img_pil = img_pil.convert('RGB')
        elif img_pil.mode == 'L':
            img_pil = img_pil.convert('RGB')

        # 转换为OpenCV格式
        img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

        # 加载mask
        mask_pil = Image.open(os.path.join(MASKS_DIR, filename))
        mask = np.array(mask_pil)

        # 打印图片信息
        print(f"原图尺寸: {img.shape[1]}x{img.shape[0]}")
        print(f"Mask尺寸: {mask.shape[1]}x{mask.shape[0]}")

        # 创建叠加图
        overlay = create_overlay(img, mask)

        # 创建显示图像
        display_img = create_display_image(img, overlay, filename, i, len(image_files), mask)

        # 显示图片
        cv2.imshow('Image Review Tool', display_img)

        # 调整窗口大小以适应图片
        display_height, display_width = display_img.shape[:2]
        cv2.resizeWindow('Image Review Tool', display_width, display_height)

        # 等待按键输入
        print("操作说明:")
        print("  1. 按 '1' 键: 保留当前图片（不移动到新数据集）")
        print("  2. 按其他任意键: 将图片移动到新数据集")
        print("  3. 按 'q' 键: 退出程序")
        print("请选择操作: ", end='')

        # 获取按键
        cv2.waitKey(1)  # 确保窗口更新
        key = cv2.waitKey(0) & 0xFF

        # 处理按键
        if key == ord('1'):
            print(f"保留图片: {filename}")
        elif key == ord('q'):
            print("用户中断程序")
            break
        else:
            # 移动文件
            src_mask = os.path.join(MASKS_DIR, filename)
            dst_mask = os.path.join(TARGET_FOLDER, 'masks', filename)
            shutil.copy(src_mask, dst_mask)

            src_image = os.path.join(IMAGES_DIR, filename)
            dst_image = os.path.join(TARGET_FOLDER, 'images', filename)
            shutil.copy(src_image, dst_image)

            src_lm = os.path.join(IMAGES_DIR, filename.replace('.png', '.json'))
            dst_lm = os.path.join(TARGET_FOLDER, 'labelme', filename.replace('.png', '.json'))
            shutil.copy(src_image, dst_image)

            print(f"已移动: {filename} -> 新数据集")

    except Exception as e:
        print(f"处理文件 {filename} 时出错: {e}")
        continue

# 清理
cv2.destroyAllWindows()
print(f"\n处理完成！共处理 {len(image_files)} 张图片")

# 统计结果
if os.path.exists(os.path.join(TARGET_FOLDER, 'images')):
    moved_count = len(os.listdir(os.path.join(TARGET_FOLDER, 'images')))
    kept_count = len(image_files) - moved_count
    print(f"移动到新数据集: {moved_count} 张")
    print(f"保留在原数据集: {kept_count} 张")