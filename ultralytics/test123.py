import h5py
import os


def quick_view_h5(file_path):
    """快速查看H5文件内容"""
    try:
        with h5py.File(file_path, 'r') as file:
            print("=== H5文件快速预览 ===")
            print("文件中的对象:")

            def quick_print(name, obj):
                if isinstance(obj, h5py.Dataset):
                    print(f"📊 {name}")
                    print(f"   形状: {obj.shape}, 类型: {obj.dtype}")

                    print(f"   数据: [显示前3个: {obj[:50]}...]")
                else:
                    print(f"📁 {name}/")

            file.visititems(quick_print)

    except Exception as e:
        print(f"错误: {e}")


dir = r'G:\1例SL20250912\123\patches_0_224\patches\202550016.11.12.h5'
quick_view_h5(dir)
