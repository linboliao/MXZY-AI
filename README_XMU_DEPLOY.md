# 厦大校园 GPU 服务器 + 手机热点本机 UI 部署

## 1. 部署结构

```text
本机浏览器
    |
    v
本机 Windows UI / Tailscale 100.x 地址
    ^
    |  校园 Worker 主动轮询、下载 SVS、回传结果
    |  Tailscale 加密网络，不需要公网 IP 或端口映射
    |
厦大 GPU 服务器 172.27.127.195 / Tailscale 100.x 地址
```

`172.27.127.195` 是校园网内部地址，手机热点下不能直接访问。两端安装 Tailscale
并登录同一个 tailnet 后，使用稳定的 Tailscale `100.x` 地址通信。UI 不主动连接
校园服务器；校园 Worker 主动连接 UI，因此校园服务器无需开放公网入站端口。

本方案适合功能和跨网传输模拟。当前 UI 没有最终用户登录系统，不应直接发布到公网。

## 2. 首次准备 Tailscale

### 本机 Windows

1. 从 <https://tailscale.com/download/windows> 安装并登录。
2. 在 PowerShell 查询本机地址：

```powershell
tailscale ip -4
tailscale status
```

记下输出的 `100.x.x.x`，下文称为 `UI_TAILSCALE_IP`。

### 厦大服务器

先在能访问 `172.27.127.195` 的环境中登录服务器，然后安装 Tailscale：

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4
tailscale status
```

浏览器完成登录授权，确保服务器与本机出现在同一个 tailnet。随后即使本机切换到
手机热点，也可使用服务器的 Tailscale 地址 SSH 登录，不再依赖 `172.27.127.195`。

## 3. 本机部署 UI

在项目目录执行：

```powershell
git switch dev
git pull --ff-only origin dev
D:\anaconda3\envs\maixin\python.exe -m pip install -r requirements-web.txt
Copy-Item .env.local-ui.example .env.local-ui.local
```

生成两个不同的随机密钥：

```powershell
D:\anaconda3\envs\maixin\python.exe -c "import secrets; print(secrets.token_urlsafe(48)); print(secrets.token_urlsafe(48))"
```

编辑 `.env.local-ui.local`：

- `WEBVIEWER_HOST` 改成 `UI_TAILSCALE_IP`；
- `WEBVIEWER_SECRET_KEY` 填第一个随机值；
- `WEBVIEWER_WORKER_TOKEN` 填第二个随机值；
- 确认 `WEBVIEWER_DATA_DIR` 所在磁盘有足够空间保存原始 SVS。

启动 UI：

```powershell
.\deploy\windows\start_ui.ps1
```

浏览器访问 `http://UI_TAILSCALE_IP:5000`。如果 Windows 防火墙首次弹窗，仅允许专用
网络。若被防火墙拦截，可在管理员 PowerShell 中只允许 Tailscale 地址段：

```powershell
New-NetFirewallRule -DisplayName "MXZY-AI Tailscale UI" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000 -RemoteAddress 100.64.0.0/10
```

## 4. 准备 Git 未包含的 YOLO 权重

四个 YOLO 权重位于 `ultralytics/runs/`，受上游 `.gitignore` 规则影响，不在 GitHub
仓库中。先在当前这台已有完整权重的本机检查并打包：

```powershell
D:\anaconda3\envs\maixin\python.exe tools\model_assets.py check
D:\anaconda3\envs\maixin\python.exe tools\model_assets.py package --output D:\mxzy-yolo.model-assets.zip
```

Tailscale 连通后把模型包传给校园服务器：

```powershell
scp D:\mxzy-yolo.model-assets.zip <服务器用户>@<服务器TAILSCALE_IP>:/tmp/
```

模型包包含 SHA-256 清单，服务器安装时会自动校验。

## 5. 厦大服务器部署 Worker

以下假设项目安装到 `/opt/MXZY-AI`。没有 `/opt` 权限时可换成用户目录，但 systemd
文件中的路径也要同步修改。

```bash
sudo git clone --branch dev git@github.com:linboliao/MXZY-AI.git /opt/MXZY-AI
cd /opt/MXZY-AI
git pull --ff-only origin dev
chmod +x deploy/linux/start_worker.sh
```

激活服务器上的 GPU 推理环境。PyTorch 必须按服务器 CUDA/驱动版本安装，不能直接照搬
本机 Windows 的 CUDA 版本：

```bash
conda activate maixin
python -m pip install -r requirements-worker.txt
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

安装此前传输的 YOLO 权重：

```bash
python tools/model_assets.py install --archive /tmp/mxzy-yolo.model-assets.zip
python tools/model_assets.py check
```

创建 Worker 配置：

```bash
cp .env.campus-worker.example .env.campus-worker.local
chmod 600 .env.campus-worker.local
```

编辑 `.env.campus-worker.local`：

- `WEBVIEWER_GATEWAY_URL=http://UI_TAILSCALE_IP:5000`；
- `WEBVIEWER_WORKER_TOKEN` 必须与本机 UI 完全一致；
- `WEBVIEWER_WORKER_DATA_DIR` 指向有足够空间的高速磁盘；
- 配置有权访问 `bioptimus/H-optimus-1` 的 `HF_TOKEN`。

先执行完整预检：

```bash
MXZY_PYTHON="$(which python)" ./deploy/linux/start_worker.sh --check
```

所有项目显示 `[OK]` 后，前台启动联调：

```bash
MXZY_PYTHON="$(which python)" ./deploy/linux/start_worker.sh
```

## 6. 配置 systemd 常驻运行（联调通过后）

复制并编辑服务模板：

```bash
sudo cp deploy/linux/mxzy-worker.service.example /etc/systemd/system/mxzy-worker.service
sudo mkdir -p /etc/mxzy-ai
sudo cp .env.campus-worker.local /etc/mxzy-ai/campus-worker.env
sudo chmod 600 /etc/mxzy-ai/campus-worker.env
sudo systemctl edit --full mxzy-worker.service
```

重点核对 `User`、`Group`、`WorkingDirectory`、`MXZY_PYTHON` 和 `MXZY_WORKER_ENV`。
然后启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mxzy-worker
sudo systemctl status mxzy-worker
journalctl -u mxzy-worker -f
```

## 7. 手机热点跨网验收

1. 本机断开校园 Wi-Fi，连接手机热点。
2. 确认 `tailscale status` 中校园服务器在线。
3. 启动本机 UI。
4. 校园服务器执行 Worker `--check`，确认 UI 网关连接成功。
5. 浏览器打开 UI，上传测试切片。
6. 观察 Worker 日志：任务领取、SVS 下载、推理、结果回传。
7. UI 任务应从“排队中”变为“执行中”，最终显示诊断和 GeoJSON 标注。

失败时按顺序检查：

```powershell
tailscale ping <服务器TAILSCALE_IP>
Test-NetConnection -ComputerName <UI_TAILSCALE_IP> -Port 5000
```

```bash
tailscale ping UI_TAILSCALE_IP
curl -H "Authorization: Bearer <WORKER_TOKEN>" http://UI_TAILSCALE_IP:5000/api/worker/health
journalctl -u mxzy-worker -n 200 --no-pager
```

## 8. 数据和安全

- 原始切片保存在本机 `WEBVIEWER_DATA_DIR`，校园服务器还会在 Worker 数据目录留一份。
- 推理结果回传本机；特征 PT、坐标和中间切块不会回传。
- 联调结束后应制定两端数据保留和安全删除策略。
- 不要提交 `.env.*.local`、`HF_TOKEN`、Worker Token 或真实患者数据。
- Tailscale 账号应启用 MFA，并用 ACL 只允许校园 Worker 访问本机 TCP 5000。
