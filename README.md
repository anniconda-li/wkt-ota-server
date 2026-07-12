# wkt-ota-server

面向 ESP32-S3 / ESP-IDF 5.3.4 的独立 OTA 后端。服务提供 Wi-Fi HTTPS 流式下载、HTTP Range 和 ML307C 小响应分片下载；发布仅通过服务器本地 CLI 完成，不暴露公网固件上传接口。

## 快速开始

要求 Python 3.12：

```bash
python -m venv .venv
python -m pip install -e ".[test]"
copy .env.example .env
python -m app
```

服务监听 `0.0.0.0:8000`，健康检查为 `GET /health`。完整接口契约见 [docs/ota-api-contract.md](docs/ota-api-contract.md)。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OTA_PUBLIC_BASE_URL` | `http://localhost:8000` | 返回给设备的公网基础 URL；生产必须是 HTTPS |
| `OTA_DATA_DIR` | `data` | SQLite 和固件持久化目录 |
| `OTA_DEVICE_TOKEN` | 空 | 可选共享设备 Token；设置后保护全部 `/api/v1/ota/*` 接口 |
| `OTA_ALLOW_TOKEN_QUERY` | `false` | 是否允许 `?token=`，仅为不能设置请求头的 ML307C 固件启用 |
| `OTA_MAX_CHUNK_SIZE` | `49152` | 分片上限，范围 1–65535 |
| `OTA_LOG_LEVEL` | `INFO` | 日志等级 |

优先通过 `X-Device-Token` 传 Token。服务关闭 Uvicorn access log，避免可选查询参数 Token 出现在请求日志。不要将 `.env` 提交到 Git。

## 发布管理

OTA 服务只保存外部构建流程生成的 `.bin`，不保存固件签名私钥，也不负责构建或签名固件。

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

发布会流式计算大小和 SHA-256，将文件原子复制到 `data/firmware/{hardware}/{version}/firmware.bin`，然后写 SQLite。相同 hardware/version 不会被覆盖。因为 `data` 是 Volume，新固件发布不需要重建镜像。

## Docker Compose

```bash
copy .env.example .env
# 修改 .env，尤其是正式 HTTPS 域名和随机 Token
docker compose up -d --build
docker compose ps
```

Compose 服务名为 `ota`，镜像名为 `wkt-ota-server`，宿主仅监听 `127.0.0.1:18082`，容器监听 `8000`，持久化挂载为 `./data:/app/data`。容器使用非 root 用户并带健康检查。

Linux 主机首次启动前需让容器内的非 root 用户可写持久化目录：`sudo install -d -o 10001 -g 10001 ./data`。Docker Desktop 通常会自动处理 bind mount 权限。

生产环境必须由外部 Nginx 在 HTTPS 上终止 TLS，并将请求反向代理到 `127.0.0.1:18082`。不要将 OTA HTTP 明文端口直接暴露到公网；若开启查询参数 Token，还应确保 Nginx 不记录查询字符串。

在 Compose 环境发布时，可先把固件放入挂载目录，再执行：

```bash
docker compose exec ota python -m app.cli publish \
  --hardware walkie-v1 --version 0.12.0 --channel stable \
  --file /app/data/incoming/firmware.bin --notes "首次OTA版本"
```

## 测试

```bash
python -m pip install -e ".[test]"
pytest
docker build -t wkt-ota-server .
docker compose config
```

数据库与固件均被 `.gitignore` 和 `.dockerignore` 排除。仓库只包含 OTA 服务自身，不依赖或修改其他 WKT 子项目。
