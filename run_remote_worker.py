"""Run the domestic GPU worker that polls the overseas Web Viewer gateway."""

import argparse
import os
import sys
import time

import requests

from webviewer.envfile import load_env_file
from webviewer.preflight import check_worker_runtime, print_checks
from webviewer.remote_worker import RemoteWorker, RemoteWorkerConfig


def main():
    parser = argparse.ArgumentParser(description="MXZY-AI 国内 GPU Worker")
    parser.add_argument("--once", action="store_true", help="最多领取一个任务后退出")
    parser.add_argument("--check", action="store_true", help="检查环境、模型资产和 UI 连通性后退出")
    parser.add_argument("--env-file", help="从指定 KEY=VALUE 文件加载部署配置")
    args = parser.parse_args()
    load_env_file(args.env_file or os.getenv("WEBVIEWER_ENV_FILE"))
    config = RemoteWorkerConfig.from_environment()
    worker = RemoteWorker(config)
    if args.check:
        runtime_ok = print_checks(check_worker_runtime())
        try:
            health = worker.client.health()
            print(f"[OK] UI 网关连接成功: {config.gateway_url} ({health.get('status', 'unknown')})")
            gateway_ok = True
        except Exception as error:
            print(f"[FAIL] UI 网关连接失败: {config.gateway_url}: {error}")
            gateway_ok = False
        return 0 if runtime_ok and gateway_ok else 1
    while True:
        try:
            worker.run_forever(once=args.once)
            return 0
        except (requests.RequestException, OSError) as error:
            if args.once:
                print(f"Worker 运行失败: {error}", file=sys.stderr)
                return 1
            print(f"Worker 与网关通信失败，稍后重试: {error}", file=sys.stderr)
            time.sleep(config.poll_seconds)
        except Exception as error:
            print(f"Worker 任务失败: {error}", file=sys.stderr)
            if args.once:
                return 1
            time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
