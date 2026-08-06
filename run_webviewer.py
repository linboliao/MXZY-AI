import argparse
import os

from webviewer import create_app
from webviewer.envfile import load_env_file


def main():
    parser = argparse.ArgumentParser(description="MXZY-AI 本机 Web Viewer")
    parser.add_argument("--env-file", help="从指定 KEY=VALUE 文件加载部署配置")
    args = parser.parse_args()
    load_env_file(args.env_file or os.getenv("WEBVIEWER_ENV_FILE"))

    app = create_app()
    host = os.getenv("WEBVIEWER_HOST", "127.0.0.1")
    port = int(os.getenv("WEBVIEWER_PORT", "5000"))
    server = os.getenv("WEBVIEWER_SERVER", "waitress").strip().lower()
    if server == "flask":
        debug = os.getenv("WEBVIEWER_DEBUG", "").lower() in {"1", "true", "yes"}
        app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)
        return
    if server != "waitress":
        raise RuntimeError("WEBVIEWER_SERVER 只能是 waitress 或 flask")

    from waitress import serve

    serve(
        app,
        host=host,
        port=port,
        threads=max(4, int(os.getenv("WEBVIEWER_SERVER_THREADS", "8"))),
        channel_timeout=3600,
        max_request_body_size=int(app.config["WEBVIEWER_MAX_UPLOAD_BYTES"]),
    )


if __name__ == "__main__":
    raise SystemExit(main())
else:
    load_env_file(os.getenv("WEBVIEWER_ENV_FILE"))
    app = create_app()
