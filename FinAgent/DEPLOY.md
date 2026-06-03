# FinAgent 本地环境迁移到服务器

代码已通过 Git 推送；**密钥与运行时数据不会进仓库**，需单独同步。

## 需要上传的内容

| 类型 | 本地路径 | 是否必须 | 说明 |
|------|----------|----------|------|
| 代码 | 仓库 `FinAgent/` | 是 | 服务器 `git pull` 即可 |
| 环境变量 | `FinAgent/.env` | 是 | **禁止** `git add`；用 `scp`/`rsync` |
| SQLite 数据 | `FinAgent/data_store/finagent.db` | 可选 | 已入库行情/年报/PIT |
| 对话与用户 | `FinAgent/chat_data/` | 可选 | 登录、会话、用户 API 设置 |
| 年报 PDF | `FinAgent/annual_reports/` | 可选 | 体积大，也可在服务器重新入库 |
| 研报输出 | `FinAgent/outputs/` | 可选 | 历史报告与图表 |

## 一、服务器准备（Linux 示例）

```bash
# 依赖
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip

# 克隆（若尚未克隆）
git clone https://github.com/firework2024/AI-for-Financial-Analysis-group-work.git
cd AI-for-Financial-Analysis-group-work/FinAgent

git pull origin main

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .

mkdir -p data_store chat_data annual_reports outputs
```

## 二、从 Windows 本机同步（PowerShell）

将 `USER`、`HOST`、`REMOTE` 换成你的 SSH 用户、服务器 IP/域名、服务器上的 FinAgent 绝对路径。

```powershell
$Local  = "D:\HuaweiMoveData\Users\du'zi'yi\Desktop\课程资料\人工智能与财务分析\AI-for-Financial-Analysis-group-work-1\FinAgent"
$Remote = "USER@HOST:/path/to/AI-for-Financial-Analysis-group-work/FinAgent"

# 1) 环境变量（必做）
scp "$Local\.env" "${Remote}/.env"

# 2) 数据库（若本地已入库，建议同步）
scp "$Local\data_store\finagent.db" "${Remote}/data_store/finagent.db"

# 3) 对话数据（若要保留账号与会话）
scp -r "$Local\chat_data" "${Remote}/"

# 4) 年报 PDF（可选，文件多时用 rsync 更快）
# 需安装 rsync（Git Bash / WSL）
rsync -avz --progress "$Local/annual_reports/" "${Remote}/annual_reports/"

# 5) 历史研报（可选）
rsync -avz --progress "$Local/outputs/" "${Remote}/outputs/"
```

仅用 `scp` 同步整个数据目录示例：

```powershell
scp -r "$Local\data_store" "$Local\chat_data" "${Remote}/"
```

## 三、启动 Web 服务

在服务器 `FinAgent` 目录、已 `source .venv/bin/activate`：

```bash
# 对外访问请用 0.0.0.0；生产建议在 Nginx 反代并配 HTTPS
finagent serve --host 0.0.0.0 --port 8765
```

或：

```bash
python -m finagent serve --host 0.0.0.0 --port 8765
```

后台常驻（systemd 示例，路径按实际修改）：

```ini
# /etc/systemd/system/finagent.service
[Unit]
Description=FinAgent Web
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/AI-for-Financial-Analysis-group-work/FinAgent
Environment=PATH=/path/to/AI-for-Financial-Analysis-group-work/FinAgent/.venv/bin
ExecStart=/path/to/AI-for-Financial-Analysis-group-work/FinAgent/.venv/bin/finagent serve --host 127.0.0.1 --port 8765
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now finagent
```

## 四、服务器 `.env` 注意项

- `OPENAI_*`、`TAVILY_API_KEY`、`FINAGENT_AUTH_SECRET` 与本地一致即可复用授权。
- 米筐二选一（见 `.env.example`）：
  - **账号直连**：`RQ_USER`、`RQ_PASSWORD`、`RQ_HOST`（如 `222.29.71.3:16010`），等价 `rqdatac.init(user, password, host)`
  - **License URI**：`RQDATAC2_CONF='tcp://...'`
  - 三者齐全时**优先账号直连**；请注释掉未用的 `RQDATAC2_CONF`。
- 服务器需能访问 `RQ_HOST` 所指地址（校园/内网网关需在安全组与白名单放行）。
- 若对外网开放 Web，务必设置强随机 `FINAGENT_AUTH_SECRET`，并考虑防火墙只放行内网或 VPN。

## 五、安全提醒

- **切勿**把 `.env` 提交到 Git（已在 `.gitignore`）。
- 同步后检查服务器文件权限：`chmod 600 .env`。
- 若 `.env` 曾泄露或提交过，请轮换 API Key、米筐 license、Tavily Key 与 `FINAGENT_AUTH_SECRET`。

## 六、域名 + HTTPS（宝塔 Nginx）

FinAgent 监听 `127.0.0.1:8765`（或 `0.0.0.0:8765`），对外由 Nginx 反代。参考配置见 [`deploy/nginx-pkufinagent.site.conf`](deploy/nginx-pkufinagent.site.conf)。

```bash
# 复制到宝塔 vhost 目录（路径按实际修改）
cp deploy/nginx-pkufinagent.site.conf /www/server/panel/vhost/nginx/pkufinagent.conf
chmod 600 /www/server/panel/vhost/cert/pkufinagent.site/privkey.pem
/www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload
```

- 证书：`/www/server/panel/vhost/cert/pkufinagent.site/fullchain.pem` 与 `privkey.pem`
- 安全组放行 **80**、**443**
- 新版 Nginx 使用 `listen 443 ssl;` + `http2 on;`（勿写已弃用的 `listen 443 ssl http2`）
- 宝塔 SSL「文件验证」失败时，可用手动部署证书 + 上述配置，或改用 DNS 验证

## 七、验证

```bash
curl -s http://127.0.0.1:8765/api/health
curl -sI https://pkufinagent.site | head -5
# 浏览器打开 https://pkufinagent.site
```

登录后新建对话，确认入库提示与股价查询正常；米筐异常时查看终端 `[rqdatac]` 日志。
