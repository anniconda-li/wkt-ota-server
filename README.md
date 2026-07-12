# wkt-ota-server

面向 ESP32-S3 的独立 OTA 后端。第一阶段仅支持设备通过 Wi-Fi 和公网 IP + 端口，以 HTTP 检查更新、流式下载 application `.bin` 并上报结果。固件只能用服务器本地 CLI 发布，不提供公网上传接口，也不依赖 Nginx、域名或其他 WKT 服务。

> 这是实验室阶段的明文 HTTP 方案。HTTP 无法防止中间人替换固件；SHA-256 只能检查传输和文件一致性，不能替代固件签名或 TLS。后续可以切换 HTTPS，但本阶段不实现。

## 快速开始

要求 Python 3.12：

```bash
python -m venv .venv
python -m pip install -e ".[test]"
copy .env.example .env
python -m app
```

服务监听 `0.0.0.0:8000`，健康检查为 `GET /health`，公共基础地址默认 `http://139.129.17.67:18082`。第一阶段设备 API 不要求认证。完整契约见 [docs/ota-api-contract.md](docs/ota-api-contract.md)。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OTA_PUBLIC_BASE_URL` | `http://139.129.17.67:18082` | 检查更新响应中的公共 HTTP 基础地址 |
| `OTA_DATA_DIR` | `data` | SQLite 与固件持久化目录；容器内为 `/app/data` |
| `OTA_LOG_LEVEL` | `INFO` | 日志等级 |

## 发布管理

日常 OTA 只发布外部构建流程生成的 application `.bin`。服务不保存签名私钥，也不构建固件。第一次把设备改造成双 OTA 分区仍需通过 USB 完整烧录分区表、bootloader 和应用。

```bash
python -m app.cli publish \
  --hardware walkie-v1 \
  --version 0.12.0 \
  --channel stable \
  --file firmware.bin \
  --notes "首次OTA版本"

python -m app.cli list
python -m app.cli disable --hardware walkie-v1 --version 0.12.0
python -m app.cli enable  --hardware walkie-v1 --version 0.12.0
```

发布命令流式计算大小和 SHA-256，将文件原子复制到 `data/firmware/{hardware}/{version}/firmware.bin`，再把元数据写入 `data/ota.db`。相同 hardware/version 会被拒绝，不会静默覆盖。固件文件不存为 SQLite BLOB，也不打入镜像。

## Docker Compose

```bash
copy .env.example .env
docker compose up -d --build
docker compose ps
```

容器内监听 `8000`，Compose 映射为 `18082:8000`，并通过 `./data:/app/data` 持久化 SQLite 和固件。容器以 UID/GID `10001` 的非 root 用户运行，具有健康检查和 `restart: unless-stopped`。镜像和 Compose 均不包含数据库、固件或 `.env`。

Linux 主机首次启动前需让容器用户可写目录：

```bash
sudo install -d -o 10001 -g 10001 ./data
```

在 Compose 环境发布时，可先把固件放入挂载目录，再执行本地管理命令：

```bash
docker compose exec ota python -m app.cli publish \
  --hardware walkie-v1 --version 0.12.0 --channel stable \
  --file /app/data/incoming/firmware.bin --notes "首次OTA版本"
```

## 设备安全要求

ESP32-S3 必须使用 `ota_0`、`ota_1` 和 `otadata`，把镜像流式写入非当前分区，并在重启前验证完整 SHA-256 和镜像格式。新固件自检失败时必须由 bootloader 回滚。明文 HTTP 仅适用于当前实验室阶段；公网使用风险需要由部署方明确接受。

## 验证

```bash
python -m pip install ".[test]"
pytest
python -m compileall app tests
docker build --tag wkt-ota-server:ci .
docker compose config --quiet
git diff --check
```

仓库只包含 OTA 服务自身，不依赖或修改 AI、对讲、部署或固件仓库。
