# ESP32-S3 Wi-Fi OTA API 契约

第一阶段基础 URL 为 `http://139.129.17.67:18082`，仅支持 Wi-Fi 和 HTTP，设备接口不要求认证。这是实验室方案：HTTP 不能防止中间人替换固件；SHA-256 只能检查传输和文件一致性，不能代替固件签名或 TLS。后续可迁移到 HTTPS，本阶段不实现。

`hardware` 为 1–64 位 ASCII 字母、数字、下划线或连字符且首位为字母或数字；`version` 必须是 SemVer 2.0；`channel` 为 1–32 位小写字母、数字或连字符。版本严格按 SemVer 优先级比较，不能按字符串排序。

## 电气硬件版本隔离契约

`device_id` 是具体设备身份，`hardware` 是固件兼容的电气硬件版本。当前统一标识为：

| 设备 | `device_id` | `hardware` |
| --- | --- | --- |
| device/001 | `walkie-01` | `walkie-v1-rev-1` |
| device/002 | `walkie-02` | `walkie-v1-rev-2` |

服务将请求中的 `device_id` 和 `hardware` 作为相互独立的字段处理：不得根据 `device_id` 推断、覆盖或改写 `hardware`。检查更新只精确查询请求的 `hardware + channel`；没有匹配项就返回 `{"update": false}`，不得回退到另一个 rev 或旧 `walkie-v1`。响应中的 `hardware` 及 `firmware_url` 硬件路径必须与匹配的发布记录一致。

release 数据库唯一键保持为 `UNIQUE(hardware, version)`，当前只使用 `stable` 频道。同一 `0.11.7` 可以分别为 rev-1 和 rev-2 保存不同文件、大小与 SHA-256，同一 hardware/version 的重复发布必须拒绝。下载 URL 不含 channel，因此不得将唯一键改为 `hardware + channel + version`。旧 `walkie-v1` release 和固件仍合法，但不会成为新 rev 的回退项。

发布 rev-1：

```bash
python -m app.cli publish \
  --hardware walkie-v1-rev-1 \
  --channel stable \
  --version 0.11.7 \
  --file /app/data/incoming/walkie-v1-rev-1-0.11.7.bin \
  --notes "一号硬件更新说明"
```

发布 rev-2：

```bash
python -m app.cli publish \
  --hardware walkie-v1-rev-2 \
  --channel stable \
  --version 0.11.7 \
  --file /app/data/incoming/walkie-v1-rev-2-0.11.7.bin \
  --notes "二号硬件更新说明"
```

## 健康检查

`GET /health` 返回服务名、版本和健康状态，不返回配置、秘密或文件路径。

## 检查更新

`GET /api/v1/ota/check`

查询参数：

- `device_id`：设备唯一 ID。
- `hardware`：硬件型号，如 `walkie-v1`。
- `current_version`：当前 SemVer，如 `0.11.2`。
- `network`：必须为 `wifi`。
- `channel`：可选，默认 `stable`。

无更新返回：

```json
{"update": false}
```

有更新返回：

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
  "firmware_url": "http://139.129.17.67:18082/api/v1/ota/firmware/walkie-v1/0.12.0"
}
```

## 固件下载

`GET /api/v1/ota/firmware/{hardware}/{version}`

不带 `Range` 时返回 `200` 和完整文件；单段字节 Range 返回 `206`。文件从磁盘流式读取，不会整体载入内存。响应头契约：

- 所有成功响应设置 `Content-Type: application/octet-stream`、正确的 `Content-Length` 和 `Accept-Ranges: bytes`。
- `206` 额外设置 `Content-Range: bytes start-end/total`。
- 支持闭区间、开放末尾和后缀 Range。
- 多段、语法错误或越界 Range 返回 `416`，设置 `Content-Range: bytes */total` 和 `Accept-Ranges: bytes`。

release 未启用、元数据不存在或固件文件缺失返回 `404`；路径参数非法返回 `422`；文件实际大小与 SQLite 元数据不一致返回 `500`。

下载处理严格按 URL 中的 `{hardware}/{version}` 查询元数据并读取 `/app/data/firmware/{hardware}/{version}/firmware.bin`。例如 rev-1 URL 只能读取 rev-1 目录；即使 rev-2 存在相同版本号，也不能跨目录或回退读取。

## 结果上报

`POST /api/v1/ota/report`

```json
{
  "device_id": "esp32-001",
  "hardware": "walkie-v1",
  "from_version": "0.11.2",
  "to_version": "0.12.0",
  "network": "wifi",
  "status": "success",
  "bytes_written": 4876816,
  "error_code": null,
  "error_message": null
}
```

`status` 可为 `download_started`、`verified`、`rebooting`、`success`、`failed`、`rolled_back`。`bytes_written`、`error_code` 和 `error_message` 可选；错误详情只允许用于 `failed` 或 `rolled_back`。成功写入 SQLite 后返回 `201`：

```json
{"accepted": true, "report_id": 123}
```

Report 按请求原样保存 `device_id` 与 `hardware`，不维护二者之间的静默映射。device/001 应报告 `walkie-01` 与 `walkie-v1-rev-1`，device/002 应报告 `walkie-02` 与 `walkie-v1-rev-2`。

## 存储与设备状态机

SQLite 元数据和升级报告位于 `/app/data/ota.db`；固件文件位于 `/app/data/firmware/{hardware}/{version}/firmware.bin`，不存入 SQLite BLOB。日常 OTA 只传 application `.bin`。

设备必须使用双 OTA app 分区和 `otadata`：检查更新 → 判断电量和空间 → 上报 `download_started` → 流式写非当前分区 → 校验完整 SHA-256 与镜像 → 上报 `verified` → 设置启动分区 → 上报 `rebooting` → 新固件自检并标记有效 → 上报 `success`。自检失败必须回滚并上报 `rolled_back`。第一次双 OTA 分区改造仍需 USB 完整烧录。
