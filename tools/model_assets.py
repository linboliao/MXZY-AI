"""Check, package, and install the YOLO weights excluded from Git."""

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
YOLO_ASSETS = (
    "ultralytics/runs/detect/yolo11s_0512/weights/last.pt",
    "ultralytics/runs/detect/yolo11s_0702/weights/last.pt",
    "ultralytics/runs/detect/cbam/weights/best.pt",
    "ultralytics/runs/detect/pki/weights/best.pt",
)
MANIFEST = "MODEL_ASSETS.sha256"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_assets(root=PROJECT_ROOT):
    ok = True
    for relative in YOLO_ASSETS:
        path = root / relative
        present = path.is_file() and path.stat().st_size > 0
        print(f"[{'OK' if present else 'MISSING'}] {relative}")
        ok = ok and present
    return ok


def package_assets(output):
    if not check_assets():
        raise RuntimeError("模型权重不完整，无法打包")
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_lines = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for relative in YOLO_ASSETS:
            path = PROJECT_ROOT / relative
            digest = sha256(path)
            manifest_lines.append(f"{digest}  {relative}")
            archive.write(path, relative)
        archive.writestr(MANIFEST, "\n".join(manifest_lines) + "\n")
    print(f"模型包已生成: {output} ({output.stat().st_size} bytes)")


def install_assets(archive_path):
    archive_path = Path(archive_path).expanduser().resolve()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        expected = set(YOLO_ASSETS) | {MANIFEST}
        if names != expected:
            raise RuntimeError("模型包文件清单不符合预期")
        manifest = {}
        for line in archive.read(MANIFEST).decode("utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            manifest[relative] = digest
        if set(manifest) != set(YOLO_ASSETS):
            raise RuntimeError("模型包校验清单不完整")

        for relative in YOLO_ASSETS:
            target = PROJECT_ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".part")
            with archive.open(relative) as source, temporary.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=8 * 1024**2)
            if sha256(temporary) != manifest[relative]:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"模型权重校验失败: {relative}")
            temporary.replace(target)
            print(f"[OK] 已安装 {relative}")


def main():
    parser = argparse.ArgumentParser(description="MXZY-AI YOLO 模型资产工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="检查本机模型权重")
    package_parser = subparsers.add_parser("package", help="打包 Git 未包含的模型权重")
    package_parser.add_argument("--output", required=True)
    install_parser = subparsers.add_parser("install", help="安装并校验模型权重包")
    install_parser.add_argument("--archive", required=True)
    args = parser.parse_args()

    if args.command == "check":
        return 0 if check_assets() else 1
    if args.command == "package":
        package_assets(args.output)
    else:
        install_assets(args.archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
