import os


from webviewer import create_app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("WEBVIEWER_HOST", "127.0.0.1")
    port = int(os.getenv("WEBVIEWER_PORT", "5000"))
    debug = os.getenv("WEBVIEWER_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)
