# 生产部署说明

本文档给出当前项目的正式部署方式。默认推荐 **user systemd + nginx 反向代理**，不要求 root 常驻应用进程，部署和回滚也更直接。

## 1. 推荐方案：user systemd 部署

适用场景：

- 应用代码由当前 Linux 用户维护
- nginx / Cloudflare 等入口已经准备好
- 希望应用进程不以 root 身份运行

### 1.1 前置条件

- Python 3.10+
- Node.js 18+
- npm 9+
- 当前用户可以执行 `systemctl --user`
- **建议开启 linger**，这样即使用户退出登录，user systemd 仍会在开机后自动拉起服务

```bash
sudo loginctl enable-linger $USER
```

### 1.2 部署目录准备

```bash
git clone https://github.com/longzhuzhu/quiz-app.git
cd quiz-app
cp .env.example .env
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build
cd ..
```

### 1.3 创建 user systemd 单元

创建目录：

```bash
mkdir -p ~/.config/systemd/user
```

创建 Web 服务 `~/.config/systemd/user/quiz-app.service`：

```ini
[Unit]
Description=CIPT Quiz App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/quiz-app
Environment=APP_HOST=0.0.0.0
Environment=APP_PORT=5003
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/path/to/quiz-app/.env
ExecStart=/bin/bash -lc 'exec scripts/start-prod.sh'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

创建 Worker 服务 `~/.config/systemd/user/quiz-app-worker.service`：

```ini
[Unit]
Description=CIPT Quiz App Worker
After=network-online.target quiz-app.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/quiz-app
Environment=PYTHONUNBUFFERED=1
Environment=JOB_WORKER_CONCURRENCY=2
EnvironmentFile=-/path/to/quiz-app/.env
ExecStart=/bin/bash -lc 'exec scripts/start-worker.sh'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

> `JOB_WORKER_CONCURRENCY=2` 是当前推荐值：不同任务作用域可以并行执行，同一作用域仍保持互斥。

### 1.4 启动服务

```bash
systemctl --user daemon-reload
systemctl --user enable --now quiz-app.service quiz-app-worker.service
```

检查状态：

```bash
systemctl --user status quiz-app
systemctl --user status quiz-app-worker
```

查看日志：

```bash
journalctl --user -u quiz-app -f
journalctl --user -u quiz-app-worker -f
```

### 1.5 反向代理

应用默认监听 `127.0.0.1/0.0.0.0:5003`。如果前面有 nginx，反代到：

```nginx
location / {
    proxy_pass http://127.0.0.1:5003;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}
```

### 1.6 更新流程

```bash
cd /path/to/quiz-app
git pull origin main
cd frontend && npm run build && cd ..
systemctl --user restart quiz-app quiz-app-worker
```

更新后建议执行：

```bash
systemctl --user status quiz-app
systemctl --user status quiz-app-worker
curl -I http://127.0.0.1:5003/
```

### 1.7 端口冲突排查

如果机器上同时存在旧的系统级 `quiz-app.service`，要先停掉或禁用，避免再次占用 `5003`：

```bash
sudo systemctl disable --now quiz-app.service
sudo systemctl disable --now quiz-app-worker.service
```

## 2. 可选方案：系统级 systemd 部署

如果你希望由 root 统一安装到 `/etc/systemd/system/`，项目也提供了安装脚本：

```bash
sudo bash scripts/install-systemd-service.sh
```

这个脚本会创建：

- `quiz-app.service`
- `quiz-app-worker.service`

适用场景：

- 机器本身就是统一由 root 管理的服务主机
- 希望用系统级 systemd 而不是 user systemd

## 3. 手动运行（不推荐长期使用）

仅用于临时排障或本机验证：

```bash
bash scripts/start-prod.sh
bash scripts/start-worker.sh
```

不建议长期依赖手动前台/后台 shell 进程，因为终端退出或会话回收时，服务可能被带掉。
