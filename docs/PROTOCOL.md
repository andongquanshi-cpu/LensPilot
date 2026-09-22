# ESP32 应用层对接契约 v0.1（待团队确认）

这里定义的是我们后端与电脑桥接程序之间的协议，不代表 ESP32 已实现，也不是 Ace Pro 2 SDK。首版只采用 WebSocket 设备桥接，不叠加 MQTT 或串口实现。实际串口、网络或其他固件协议由通信团队提供插件映射。

## 连接与同步

后端 `OPTIC_TRANSPORT=bridge`，连接 `/ws/device`。WebSocket 建连后 5 秒内发送 `{"type":"auth","token":"设备凭证"}`。凭证不能放 URL；不要将控制凭证用于设备。当前只支持设备 `lens-01`，一个设备连接，一个后端进程。

后端发送：

```json
{"type":"query_position","query_id":"随机查询标识","connection_session_id":"后端签发的新连接会话"}
```

设备回复（actual_slot 仅为示例，必须来自硬件）：

```json
{"type":"position","connection_session_id":"本次连接会话","query_id":"对应查询标识","actual_slot":0,"position_verified":true}
```

桥接插件只有在可靠到位传感或团队确认的等价证据存在时才能声明 position_verified=true。只有接收 ACK、预计电机走完、保存的最后指令均不足以声明可信位置。运动尚未结束时返回 `actual_slot:null, position_verified:false`。启动/重连不读取数据库恢复实际镜片。槽位未知时同步状态保持，不能发新运动。

每 3 秒发送 `{"type":"heartbeat","connection_session_id":"本次连接会话"}`；默认 15 秒未收到合法消息断线。旧连接会话的反馈丢弃。每条输入消息不超过 8 KiB。

## 运动

```json
{
  "type":"command",
  "command":{
    "command_id":"唯一标识",
    "decision_id":"关联决策标识",
    "frame_id":"关联画面标识或 null",
    "device_id":"lens-01",
    "connection_session_id":"本次连接会话",
    "action":"select_filter",
    "target_filter":"STAR",
    "target_slot":3,
    "issued_at":1789990000.0,
    "expires_at":1789990008.0,
    "ttl_ms":8000
  }
}
```

槽位完全来自 config.json。默认 0–3 仅用于模拟，接硬件前必须替换。KEEP 没有槽位、不发送指令。只有 supports_clear=true 且 slots.CLEAR 存在才可 CLEAR。没有 ND，不控制偏振角度，不叠加镜片。

```json
{
  "type":"feedback",
  "connection_session_id":"本次连接会话",
  "feedback":{
    "command_id":"对应指令",
    "connection_session_id":"本次连接会话",
    "status":"completed",
    "actual_slot":3,
    "position_verified":true,
    "error_code":null
  }
}
```

status 可为 accepted / moving / completed / failed。accepted 不更新实际镜片。只有对应当前 pending 指令、当前连接会话、未过期、目标槽位相符、position_verified=true 的 completed 才算到位。重复/过期/上一会话反馈忽略。错误到位或超时会暂停自动、清除实际位置、查询位置，不重发运动；同步后需用户恢复自动。

## 时钟、去重和断线责任

后端使用接收时间、会话与序号做图像新鲜度判断，客户端采集时间仅展示。运动有效期则需要通信团队确认时钟策略：当前电脑桥接会按 expires_at 拒绝过期指令，要求电脑与后端 NTP 对时。ttl_ms 供固件接口映射使用，不能把收到旧指令时重新开始 TTL 当成安全过期校验。时钟不可靠时，团队需实现握手估算时差或挑战令牌的有效期约定后再启用真实运动。

后端从不自动重发运动。桥接内存缓存最近 1024 个 command_id 防止同次进程重复下发。固件必须最终去重，明确缓存窗口、重启恢复策略，保证重复 command_id 不重复驱动。断开连接只阻止新命令，不能声称撤销已经发送的机械运动；桥接重连查询必须等待装置停止并确认位置，不能用最后指令推断。若当前硬件不能满足，请保持 bridge 未启用。

## 电脑桥接插件

实现 `bridge.device.FirmwareAdapter.query_position()` 和异步生成器 `select(command)`；暴露可信本地 Python 工厂，例如 `team_protocol:create_adapter`。后端不会导入外部用户提供的代码路径，只有电脑启动命令选择团队插件。

```powershell
$env:OPTIC_DEVICE_TOKEN = '<设备凭证>'
.\.venv\Scripts\python -m bridge.device --adapter team_protocol:create_adapter --url ws://127.0.0.1:8000/ws/device
```

以上 team_protocol 是待团队提供的模块名示例，仓库不伪造它。示例基类不能驱动真实装置。

## 通信同学需提供

1. 已验证传输方式、连接配置、协议版本、编码及完整报文样例。
2. 四种镜片实际槽位、初始归位方法、是否真的有空位/移出能力。
3. 接收 ACK 与到位反馈区别；是否有传感器、位置查询、运动中位置语义。
4. 正常/极端移动耗时，错误码，电机卡住与掉电行为，超时后恢复步骤。
5. command_id 去重机制、持久化与重启行为、过期和时钟同步方案。
6. 断线后机械动作是否继续、重连是否可查询仍在运动、紧急停止是否真实可用。
7. 录像状态若可获取，来源、刷新间隔和断开后的失效规则。
8. Ace Pro 2 画面接口及许可文档；近摄镜可用距离范围及固定演示距离实测数据。
