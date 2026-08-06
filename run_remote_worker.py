"""Run the domestic GPU worker that polls the overseas Web Viewer gateway."""

import argparse
import sys
import time

import requests

from webviewer.remote_worker import RemoteWorker, RemoteWorkerConfig


def main():
    parser = argparse.ArgumentParser(description="MXZY-AI 国内 GPU Worker")
    parser.add_argument("--once", action="store_true", help="最多领取一个任务后退出")
    args = parser.parse_args()
    config = RemoteWorkerConfig.from_environment()
    worker = RemoteWorker(config)
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
