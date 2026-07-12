# ESP32 OTA API 契约

基础 URL 示例：`https://ota.example.com`。生产通信必须使用 HTTPS。若配置了设备 Token，所有 `/api/v1/ota/*` 请求携带 `X-Device-Token: <token>`；仅在 `OTA_ALLOW_TOKEN_QUERY=true` 时可改用 `?token=<token>`。`GET /health` 不鉴权。

标识符约束：`hardware` 为 1–64 位 ASCII 字母、数字、下划线或连字符且首位为字母/数字；`version` 必须是 SemVer 2.0；`channel` 为 1–32 位小写字母、数字或连字符。服务按 SemVer 优先级比较版本，构建元数据不影响优先级。

## 检查更新

`GET /api/v1/ota/check`

查询参数：

- `device_id`：设备唯一 ID。
- `hardware`：硬件型号，如 `walkie-v1`。
- `current_version`：当前 SemVer，如 `0.11.2`。
- `network`：`wifi` 或 `ml307c`。
- `channel`：可选，默认 `stable`。

无更新响应为 `200 application/json`：

```json
{"update": false}
```

有更新响应：

```json
{
  "update": true,
  "version": "0.12.0",
  "hardware": "walkie-v1",
  "channel": "stable",
  "size": 4876816,
  "sha256": "64位小写十六进制SHA-256",
  "mandatory": false,
  "min_battery": 40,
  "release_notes": "首次OTA版本",
  "firmware_url": "https://ota.example.com/api/v1/ota/firmware/walkie-v1/0.12.0",
  "chunk_url": "https://ota.example.com/api/v1/ota/chunk/walkie-v1/0.12.0",
  "chunk_size": 49152
}
```

设备应在下载前检查硬件、版本、剩余 OTA 分区容量和电量门槛。下载结束后必须对整个镜像计算 SHA-256 并与响应值做常量时间比较，然后再设置启动分区。

## Wi-Fi 固件流

`GET /api/v1/ota/firmware/{hardware}/{version}`

不带 `Range` 时返回 `200`；单段字节 Range（例如 `Range: bytes=0-65535`）返回 `206`。响应包含：

- `Content-Type: application/octet-stream`
- `Content-Length`
- `Accept-Ranges: bytes`
- `Content-Range: bytes start-end/total`（仅 206）

支持闭区间、开放末尾和后缀 Range。多段、语法错误或越界 Range 返回 `416`，并带 `Content-Range: bytes */total`。文件通过流式迭代读取，不会整体载入内存。

ESP-IDF Wi-Fi 侧建议使用 `esp_https_ota` 或 `esp_http_client` 流式写入非当前 OTA 分区，校验证书主机名和可信 CA，不得跳过 TLS 校验。网络中断后可用 Range 从已确认写入的偏移恢复。

## ML307C 分片

`GET /api/v1/ota/chunk/{hardware}/{version}?offset=0&length=49152`

`offset` 从 0 开始，`length` 必须在 1 到服务器返回的 `chunk_size` 之间，默认最大 49152，确保单次响应低于 ML307C 的 65535 字节限制。响应体是原始二进制，不是 JSON/Base64。响应头：

- `Content-Length`：本次实际字节数。
- `X-Firmware-Size`：完整固件字节数。
- `X-Chunk-Offset`：本片起始偏移。
- `X-Chunk-Length`：本片实际字节数。

最后一片可短于请求 `length`。`offset >= X-Firmware-Size` 返回 `416`，非法或超限参数返回 `422`。设备只在收到的偏移、长度与预期一致后写入，并在每片成功写入后推进偏移；最终写入量必须等于检查接口的 `size`，随后校验完整 SHA-256。

## 结果上报

`POST /api/v1/ota/report`，JSON 请求体：

```json
{
  "device_id": "esp32-001",
  "hardware": "walkie-v1",
  "from_version": "0.11.2",
  "to_version": "0.12.0",
  "network": "ml307c",
  "status": "success",
  "bytes_written": 4876816,
  "error_code": null,
  "error_message": null
}
```

`status` 可为 `download_started`、`verified`、`rebooting`、`success`、`failed`、`rolled_back`。`bytes_written`、`error_code`、`error_message` 可选；错误信息仅用于 `failed` 或 `rolled_back`。成功写入返回 `201`：

```json
{"accepted": true, "report_id": 123}
```

服务器使用 UTC 时间落库。设备报告中不得包含 Wi-Fi 密码、Token、私钥或其他秘密。

## 设备状态机建议

ESP32-S3 的 16MB 分区表应包含 `ota_0`、`ota_1` 和 `otadata`，且每个 OTA app 分区需大于固件最大预期尺寸（当前约 4.65MB，还要预留增长空间）。推荐流程：检查 → 电量判断 → `download_started` → 写非当前分区 → SHA-256/镜像校验 → `verified` → 设置启动分区 → `rebooting` → 新固件自检后标记有效并报 `success`。若新固件未在回滚窗口内确认有效，由 bootloader 回滚并报 `rolled_back`。

## 错误约定

- `401`：Token 缺失或不正确。
- `404`：release 未启用、元数据不存在或固件文件不存在。
- `416`：Range 或分片偏移越界。
- `422`：参数、标识符、SemVer 或报告体不合法。
- `500`：固件文件大小与发布元数据不一致；设备应停止升级并稍后重试。
