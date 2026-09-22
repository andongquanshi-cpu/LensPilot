# 视频转发接入点

数据链路：SDK 视频片段 → 按时间戳组帧 → VideoFrame → 手机解码 + 独立转发队列。

## 对外协议

`stream/VideoForwarder.kt`：

```kotlin
interface VideoForwarder {
    suspend fun start(network: Network)
    suspend fun send(frame: VideoFrame)
    suspend fun stop()
}
```

实现此接口即可接 WebSocket、自定义 TCP 或其他协议。若使用 RTMP，需要复用 SDK 的直播 API 或正确封装；本接口的 Annex-B 数据不能直接当 RTMP/MP4 使用。

- `start`：初始化连接。传入明确的、已验证可联网的非 Wi-Fi Network，通常是蜂窝网络。
- `send`：单线程依次交付完整访问单元。调用方拥有字节数据，但实现不要修改 ByteArray。
- `stop`：清理连接。必须支持协程取消；网络操作应有自身的连接/写入超时。
- 在预览开启后调用 `session.startForwarding(yourSink)`，检查返回 Result。停止时调用挂起函数 `session.stopForwarding()`。
- 未提供服务端地址及鉴权配置，因此当前没有实际上传实现，也没有产生上传流量。

`VideoFrame` 字段：

| 字段 | 含义 |
| --- | --- |
| data | 完整访问单元，统一为 Annex-B（00 00 00 01 起始码） |
| ptsUs | 根据 SDK 文档将相机毫秒时间戳换算为微秒；不是 UTC 时间；新会话不保证连续 |
| mime | video/avc 或 video/hevc |
| width / height | SDK 预览参数；初始默认 1280×960，收到参数通知后更新 |
| keyFrame | AVC IDR，或 HEVC IRAP 类型 16–21 |
| codecConfig | AVC SPS/PPS；HEVC VPS/SPS/PPS，每项包含 Annex-B 起始码；未收齐时为空 |

接收端应按 mime 初始化解码器，使用 codecConfig，再从关键帧开始消费；参数变化时重建解码器。组帧在下一时间戳到来时提交，约增加一帧缓冲；停止时丢弃最后可能不完整的一帧。

## 限流与错误

- SDK 原始队列最多 64 片（或等待超过 250 ms），过载时清空不完整视频并请求关键帧恢复。
- 转发队列最多 8 帧，慢消费者不阻塞预览。过载后清空排队帧，等待新关键帧及参数集再继续。
- 初始化超时 10 秒，逐帧发送超时 5 秒；失败通过状态回调报告。失败后先 stopForwarding 再重新 startForwarding。
- 不应缓存整个直播历史。模型处理速度慢时建议后续从解码图像按 1–2 fps 抽帧，使用新增 SceneSampler / SceneAnalyzer JPEG 接口；不要把这里的 H.264/H.265 数据作为 JPEG 上传。

## 双网络

SDK 会话需要将 App 默认网络绑定到相机 Wi-Fi。转发必须显式使用传入 Network 的 `socketFactory`，并将 DNS 查询绑定到同一 Network（例如 OkHttp 自定义 Dns，调用 network.getAllByName），或者使用 `network.openConnection(url)`。

不得直接使用默认 HTTP 客户端，否则可能走相机热点而无法联网。当前仅选择已经存在的、验证通过的非 Wi-Fi 网络；如果手机没有可用蜂窝网络则明确报错，尚未实现主动申请蜂窝网络或自动网络切换。此行为仍需红米真机验证。
