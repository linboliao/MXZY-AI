# MXZY-AI 海外 Web Viewer + 国内 GPU Worker

本项目采用双服务器架构：

- 海外服务器运行 `run_webviewer.py`，负责 UI、用户上传、原始切片存储、任务状态、切片浏览和结果展示。
- 国内高校 GPU 服务器运行 `run_remote_worker.py`，主动连接海外服务器领取任务，下载 SVS，调用 `run_medical_image_pipeline.py` 推理，再把精简结果包传回海外服务器。

海外服务器不需要模型、CUDA 或完整推理代码；国内服务器不需要开放入站端口。所有 Worker 请求都应通过 HTTPS，并使用共享的 Bearer Token 鉴权。

## 数据流

1. 用户通过海外 UI 上传 `.svs`。
2. 海外网关保存切片并建立 `queued` 任务。
3. 国内 Worker 轮询 `/api/worker/jobs/lease` 并取得有时限的任务租约。
4. Worker 使用支持 HTTP Range 的接口断点下载切片，并定期发送心跳续租。
5. Worker 在本地调用 `run_medical_image_pipeline.py`。
6. Worker 只压缩回传 `exist_cancer.json`、GeoJSON、面积和分类 CSV、流水线日志，不回传特征、坐标或切块中间文件。
7. 海外网关校验并解压结果，UI 随后使用海外保存的原始 SVS 和回传的 GeoJSON 展示结果。

## 海外服务器部署

安装 Web 端依赖：

```bash
pip install -r requirements-web.txt
```

根据 `.env.singapore.example` 配置环境变量。关键项：

```text
WEBVIEWER_DATA_DIR=/data
WEBVIEWER_PIPELINE_MODE=real
WEBVIEWER_EXECUTION_BACKEND=remote
WEBVIEWER_WORKER_TOKEN=<高强度随机密钥>
WEBVIEWER_WORKER_LEASE_SECONDS=300
WEBVIEWER_RESULT_BUNDLE_MAX_MB=512
```

启动：

```bash
python run_webviewer.py
```

生产环境应使用 Gunicorn/Waitress 等进程管理器，并放在 HTTPS 反向代理后。SQLite 和上传文件必须位于持久化磁盘。当前程序不会自动读取 `.env` 文件，使用 systemd `EnvironmentFile`、容器环境变量或 shell 导出变量。

反向代理至少需要：

- 允许最大 20 GB（或与 `WEBVIEWER_MAX_UPLOAD_GB` 一致）的请求体；
- 上传请求关闭代理缓冲，避免先占用一份临时磁盘；
- 为大文件上传、Worker 结果回传设置足够的读写超时；
- 保留 `Range` 请求头，方便国内 Worker 断点续传；
- 全站强制 HTTPS。

## 国内 GPU 服务器部署

先保证以下命令可在国内服务器本地正常运行：

```powershell
python run_medical_image_pipeline.py --wsi_dir <输入目录> --output_dir <输出目录>
```

再安装 Worker 额外依赖：

```powershell
pip install -r requirements-worker.txt
```

根据 `.env.china.example` 配置环境变量，`WEBVIEWER_WORKER_TOKEN` 必须与海外网关完全一致：

```text
WEBVIEWER_GATEWAY_URL=https://viewer.example.com
WEBVIEWER_WORKER_TOKEN=<与海外一致的密钥>
WEBVIEWER_WORKER_ID=china-gpu-01
WEBVIEWER_WORKER_DATA_DIR=D:\MXZY-AI-worker-data
WEBVIEWER_WORKER_POLL_SECONDS=10
WEBVIEWER_WORKER_HEARTBEAT_SECONDS=30
WEBVIEWER_VERIFY_TLS=true
HF_TOKEN=<如模型缓存不完整则配置>
```

持续运行 Worker：

```powershell
python run_remote_worker.py
```

只领取一次任务并退出，适合联调：

```powershell
python run_remote_worker.py --once
```

Worker 下载使用 `.part` 文件，连接中断后会从已有字节继续。任务超过租约时间且没有心跳时，会被后续 Worker 重新领取。国内 `worker_data/jobs` 会保留切片、推理中间结果和日志，应配置定期清理策略。

## 本地联调与测试

不运行真实模型的 UI 测试：

```powershell
$env:WEBVIEWER_PIPELINE_MODE = "mock"
$env:WEBVIEWER_EXECUTION_BACKEND = "local"
python run_webviewer.py
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 安全与医疗数据

- `WEBVIEWER_WORKER_TOKEN`、`HF_TOKEN` 和真实域名密钥不得提交到 Git。
- Worker API 不应绕过 HTTPS 暴露；建议额外使用 IP 白名单、VPN 或 mTLS。
- 病理切片属于敏感医疗数据，应落实访问认证、操作审计、磁盘加密、备份和数据保留/删除策略。
- 当前 UI 仍需增加面向最终用户的登录鉴权，Worker Token 不能替代用户认证。
- 系统输出仅用于科研和辅助阅片，不能替代执业病理医师诊断。
