# MXZY-AI 公网部署：海外 VPS 入口 + 厦大 GPU 服务器

这个方案让普通用户只访问一个 HTTPS 域名，不安装 Tailscale 或其他客户端。海外 VPS 负责公网入口、TLS 和登录验证；上传数据通过 Tailscale 私网转发到厦大服务器，由同一台厦大服务器运行 Web Viewer 和医疗图像 pipeline。

```text
用户浏览器
    |
    | HTTPS 443（域名 + Basic Auth）
    v
海外 VPS：Caddy
    |
    | Tailscale 私网（100.x.x.x:5000）
    v
厦大 GPU 服务器：Waitress + Web Viewer
    |
    +-- WEBVIEWER_EXECUTION_BACKEND=local
    +-- run_medical_image_pipeline.py
    +-- GPU / 模型 / 结果目录
```

> 重要：医疗切片和结果可能属于敏感数据。上线前需要确认患者授权、数据出境/跨境传输、日志留存和访问控制要求。若不能让原始数据经过海外 VPS，应改用境内合规公网入口或专线；单纯使用 HTTPS 并不会消除合规问题。

## 1. 准备信息

需要准备：

- 一个域名，例如 `ai.example.com`，A/AAAA 记录指向海外 VPS；
- 海外 VPS 放行公网 TCP 80、443；
- VPS 和厦大服务器加入同一个 tailnet；
- 厦大服务器的 `tailscale ip -4`，下文用 `100.64.0.20` 举例；
- 厦大服务器上的项目目录、Conda Python 路径和大容量数据目录；
- 有权限访问 `bioptimus/H-optimus-1` 的 Hugging Face token。

不要把厦大校园网地址（例如 `172.x`/`10.x`）填给 VPS。`MXZY_CAMPUS_UPSTREAM` 必须使用厦大服务器的 Tailscale `100.x` 地址。

## 2. 厦大 GPU 服务器部署一体化服务

以下示例假设项目位于 `/opt/MXZY-AI`，服务用户为 `mxzy`，Conda 环境 Python 为 `/opt/conda/envs/maixin/bin/python`。路径不一致时修改 service 文件。

### 2.1 安装环境和系统库

```bash
cd /opt/MXZY-AI

conda create -n maixin python=3.10 -y
conda activate maixin

# Ubuntu/Debian；OpenSlide 的 Python 包仍需要系统动态库。
sudo apt-get update
sudo apt-get install -y openslide-tools libopenslide0 libgl1 libglib2.0-0

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-server-cu118.txt
```

确认解释器、CUDA 和依赖：

```bash
which python
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
python -c "import openslide, cv2, timm, geopandas, mmcv, mmengine; print('imports ok')"
```

`torch.version.cuda` 应显示 `11.8`，并且 `torch.cuda.is_available()` 应为 `True`。NVIDIA 驱动必须能够支持 CUDA 11.8；安装 PyTorch wheel 不会替代宿主机驱动。

### 2.2 创建运行配置

```bash
sudo install -d -m 0750 -o mxzy -g mxzy /etc/mxzy-ai
sudo install -d -m 0750 -o mxzy -g mxzy /data/mxzy-ai-ui
sudo install -m 0640 -o mxzy -g mxzy \
  /opt/MXZY-AI/.env.campus-server-ui.example \
  /etc/mxzy-ai/campus-server-ui.env

sudo nano /etc/mxzy-ai/campus-server-ui.env
```

至少修改：

- `WEBVIEWER_HOST`：厦大服务器执行 `tailscale ip -4` 得到的地址；
- `WEBVIEWER_SECRET_KEY`：使用模板注释里的命令生成；
- `HF_TOKEN`：填真实 token，或确认模型已经缓存在 `mxzy` 用户可访问的位置；
- `WEBVIEWER_DATA_DIR`：选择空间足够、仅服务用户可读写的磁盘。

配置里的 `WEBVIEWER_EXECUTION_BACKEND=local` 是关键：它会让 Web Viewer 直接启动 `run_medical_image_pipeline.py`，不再等待远程 Worker 轮询。

### 2.3 先以前台方式验证

```bash
cd /opt/MXZY-AI
sudo -u mxzy \
  MXZY_PYTHON=/opt/conda/envs/maixin/bin/python \
  MXZY_SERVER_UI_ENV=/etc/mxzy-ai/campus-server-ui.env \
  bash deploy/linux/start_server_ui.sh
```

从 VPS 测试私网连接：

```bash
curl --fail --show-error http://100.64.0.20:5000/api/health
```

期望返回包含 `"status":"ok"` 和 `"executionBackend":"local"` 的 JSON。如果系统 `curl` 被第三方动态库污染，可用：

```bash
python3 -c "import urllib.request; print(urllib.request.urlopen('http://100.64.0.20:5000/api/health', timeout=15).read().decode())"
```

### 2.4 注册 systemd 服务

前台验证成功后按实际路径检查模板，再安装：

```bash
sudo install -m 0644 \
  /opt/MXZY-AI/deploy/linux/mxzy-server-ui.service.example \
  /etc/systemd/system/mxzy-server-ui.service

sudo systemctl daemon-reload
sudo systemctl enable --now mxzy-server-ui
sudo systemctl status mxzy-server-ui --no-pager
sudo journalctl -u mxzy-server-ui -n 100 --no-pager
```

防火墙只应允许 Tailscale 接口访问 5000，不要向校园网或公网开放该端口。若使用 UFW：

```bash
sudo ufw allow in on tailscale0 to any port 5000 proto tcp
```

还应在 Tailscale Grants 中只允许海外 VPS 访问厦大服务器的 TCP 5000。仓库中的 `deploy/tailscale/grants.example.hujson` 提供了最小规则：在 Tailscale 管理后台给两台机器分别分配 `tag:mxzy-vps`、`tag:mxzy-campus`，再把示例的 `tagOwners` 和 `grants` 合并到现有 policy。不要覆盖现有规则。还要删除或收紧会对这两台机器产生“全部端口放行”效果的旧规则，否则更宽泛的规则仍会生效。

### 2.5 预计算服务端切片

把管理员维护的 `.svs` 文件放在独立切片库，并在服务配置中加入：

```text
WEBVIEWER_SERVER_SLIDE_ROOTS=Pathology=/data/slide_library
```

重启 Web Viewer 后先检查识别及缓存状态：

```bash
curl -s http://100.64.0.20:5000/api/server-slides | python -m json.tool
```

首次批量预计算使用管理员命令。建议先预览，再正式加入任务队列：

```bash
python precompute_server_slides.py --url http://100.64.0.20:5000 --dry-run
python precompute_server_slides.py --url http://100.64.0.20:5000
```

脚本仅提交 `not_analyzed` 和 `outdated` 切片，已经完成或正在处理的切片不会重复执行。失败任务需要确认原因后显式重试：

```bash
python precompute_server_slides.py \
  --url http://100.64.0.20:5000 \
  --include-failed
```

网页中的 `Ready` 切片会直接打开持久化结果；未预计算的切片不会由普通用户启动 GPU 任务。切片的大小或修改时间发生变化后，原结果会标记为 `Outdated`，由管理员重新预计算。

## 3. 海外 VPS 部署 Caddy 公网入口

先在 VPS 安装并登录 Tailscale，确认下面两项都成功：

```bash
tailscale status
curl --fail http://100.64.0.20:5000/api/health
```

然后通过 Caddy 官方软件源安装 Caddy。安装完成后创建配置：

```bash
sudo install -d -m 0750 -o root -g caddy /etc/caddy
sudo install -m 0644 deploy/vps/Caddyfile.example /etc/caddy/Caddyfile
sudo install -m 0640 -o root -g caddy deploy/vps/mxzy.env.example /etc/caddy/mxzy.env
sudo mkdir -p /etc/systemd/system/caddy.service.d
sudo install -m 0644 deploy/vps/caddy.service.override.example \
  /etc/systemd/system/caddy.service.d/mxzy.conf
```

如果 VPS 没有项目副本，可以只把 `deploy/vps/` 中这三个文件传到 VPS。

生成密码哈希，并编辑环境文件：

```bash
caddy hash-password --plaintext '请换成高强度密码'
sudo nano /etc/caddy/mxzy.env
```

修改 `/etc/caddy/mxzy.env` 中的域名、邮箱、用户名、密码哈希和厦大服务器 Tailscale 地址。然后让 systemd 读取环境文件并启动。Caddy 启动时会验证配置，验证失败时服务不会进入运行状态：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now caddy
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy -n 100 --no-pager
```

如果密码哈希包含 `$`，直接放在 systemd 的 `EnvironmentFile` 中即可，不要把它手工粘贴进 Caddyfile。Caddy 会自动申请并续期 HTTPS 证书，因此域名解析和 VPS 的 80/443 入站端口必须正确。

## 4. 端到端验收

在不安装 Tailscale 的外部电脑上执行：

```bash
curl -u mxzy:你的密码 https://ai.example.com/api/health
```

然后用浏览器访问 `https://ai.example.com`，依次验证：

1. 未登录时浏览器要求输入用户名和密码；
2. 登录后可以打开页面并上传一个非敏感测试切片；
3. 任务状态从排队/运行变为完成；
4. 结果图层可查看、结果文件可下载；
5. `journalctl -u mxzy-server-ui -f` 能看到 pipeline 运行日志；
6. 停止 VPS 的 Tailscale 后公网请求失败，说明没有误走校园公网地址。

当前任务执行器一次只运行一个本地 pipeline，其他任务会排队。这更适合单 GPU，也避免多个大切片同时挤爆显存。Waitress 的线程数只影响网页/API 并发，不会让 GPU pipeline 并行。

## 5. 从旧的 Worker 模式迁移

在新域名完成一次端到端测试之前，保留原来的 `mxzy-worker` 服务。验证新模式后再停止旧 Worker，避免同一个项目同时维护两套入口：

```bash
sudo systemctl disable --now mxzy-worker
```

旧的 `.env.campus-worker.*` 和 `run_remote_worker.py` 可继续留在仓库中作为回退方案；新的一体化服务不会读取 Worker token，也不会向 Windows 本机发起心跳。

## 6. 生产环境最低安全要求

- 只允许 HTTPS，不直接暴露厦大服务器的 5000；
- 使用 Tailscale ACL/Grants 把 VPS 到厦大服务器的访问限制在 TCP 5000；
- Basic Auth 只适合小规模受控用户；多人、审计或细粒度权限场景应换成 OIDC/SSO；
- 定期轮换公网密码、`WEBVIEWER_SECRET_KEY` 和 `HF_TOKEN`；
- 限制 `/data/mxzy-ai-ui` 权限，并制定上传文件、结果和日志的自动清理周期；
- 不在 Caddy access log、命令行或 Git 中记录患者标识、token 和密码；
- 对大文件先用测试数据压测。经过海外 VPS 中转会受两段公网链路中较慢的一段限制，断线续传需要后续单独实现分片上传。
