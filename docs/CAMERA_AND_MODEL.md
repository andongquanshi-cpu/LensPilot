# 画面与视觉模型接入

## 已实现画面方式

- 单张图片：页面上传 JPEG/PNG/WebP，像素上限 1600 万，默认原始上传上限 8 MB；剥除 EXIF、转 RGB、压缩为 JPEG。真实图片 + 模拟模型 + 模拟设备是合法组合，页面分别标记。
- 视频：在本机 config.json 的 media_files 配置 `{"trip":"C:/用户选择的路径/trip.mp4"}`。页面只选 ID，没有任意服务器路径接口。安装 requirements-camera.txt。到文件末尾停止，不重放整个视频给模型。
- 普通摄像头：安装相同可选依赖，从 camera_indices 中选择。是否能打开由系统权限和摄像头驱动决定。
- Ace Pro 2：选择“桥接上传”取得 source session；将团队确认的 SDK 或画面接口输出 JPEG 接到下述 Uploader。仓库不包含 Ace Pro 2 专有 SDK 调用，也不保证相机能当普通 USB 摄像头。
- HTTP 图片流：另一台电脑运行 bridge.camera，或自己调用 POST /api/frames。预览是受控轮询 JPEG，和 AI 抽样独立。

控制凭证创建会话 `POST /api/source {"kind":"ace_bridge"}`；设备凭证或控制凭证上传二进制图片至 POST /api/frames：

```
Authorization: Bearer <设备凭证>
Content-Type: image/jpeg
X-Source-Session: <后端创建的当前画面会话>
X-Sequence: <单调递增非负整数>
X-Captured-At: <Unix 秒，仅作为来源采集时间记录>
```

后端还记录自身 received_at、frame_id、采集镜片与 state_version。同一会话只接受递增序号；源切换/暂停使在途分析失效。普通历史图片没有可信采集镜片，记录 actual_filter=null、capture_lens_verified=false，仅展示分析，不自动运动。

实时电脑桥接先 GET /api/capture-context（设备凭证）取得 state_version 与 capture_allowed，随后采集新画面，在上传中带 `X-Capture-State-Version`。只有上传时状态版本仍一致且设备稳定，才关联当前实际镜片；否则画面不能用于自动决策。bridge.camera 已实现该顺序。团队接 Ace Pro 2 时必须确保回调图像确实是在取得上下文后曝光的新图，而不是相机内部历史缓存；此版本没有专有 SDK 曝光时间同步能力，无法替固件证明这点。切换途中开始采集或延迟到新状态的帧会被版本校验排除。

本地演示视频配模拟设备时，镜片关联是模拟位置，不代表历史录像真的经过对应滤镜。真实设备模式下的历史视频或未带采集状态的上传只能分析，不能驱动自动切镜。两种模式都不生成滤镜效果图。

```powershell
$env:OPTIC_DEVICE_TOKEN = '<设备凭证>'
.\.venv\Scripts\python -m bridge.camera --session <控制台联调详情中的源会话> --camera 0
# 本地视频桥接也可指定 --video "C:/media/demo.mp4"
```

Uploader 只有一个最新待上传缓存、一个 HTTP 请求在途；源会话失效或请求异常会停止程序，需创建/选择新会话后重启。OpenCV 捕获为本地实现，首版桥接预览约 5 FPS；没有实现 Ace Pro 2 SDK 或相机录制状态自动检测。

## 采样与边界

后端只有一个分析任务，在途时新帧覆盖 pending。默认分析完成后再等待 2 秒采样，不承诺精确每秒吞吐。单张图片只分析一次，连续一致默认三次，所以只传一张不会自动切镜。预览继续显示最后一帧并标记年龄；不能把静止预览当成设备仍在线。

运动期间和默认 2 秒稳定期间接入的帧不能用于新自动判断。每次分析返回还检查来源会话、接收年龄、实际镜片、状态版本、锁定、录像和连接状态。阈值为初始参数，需实拍调整。

快照仅内存保存最近一组，默认 2 张、10 分钟过期，可通过 snapshot_count 和 snapshot_ttl_seconds 调整；重启清空。它们是原始输入画面，不合成滤镜效果。合成演示源的快照仍是合成画面。

## 模型配置与未完成项

当前没有选定真实视觉模型供应商、官方接口资料和密钥，因此只实现 `backend.vision.MockVision`。这符合缺少供应商时先模拟的范围；真实模型 API **未完成、未验证**。非 mock provider 启动时报错，不静默降级。不要只修改 base_url 后假设适用所有服务。

配置字段：provider、base_url、api_key、model、image_input、model_timeout；密钥从后端 OPTIC_API_KEY 或 .env 读取，排除在 API 配置和日志之外。image_input 当前为 jpeg_bytes。

确定供应商后需要：

1. 阅读供应商官方图像输入、模型名称、认证、超时及结构化输出文档。
2. 在 backend/vision.py 同级新增独立供应商模块，实现 VisionAdapter.analyze(frame, context)。使用 backend.vision.SYSTEM_RULES，传递实际镜片、支持槽位/能力、有效意图、近期状态。画中文字不能改规则。
3. 按该供应商要求处理二进制、Base64 或文件上传，不能套用猜测的 OpenAI 兼容格式。映射供应商响应为 SceneAnalysis，不把任意 reason 当控制指令。
4. 在 config 和 Controller 的工厂中显式注册供应商，给前端返回真实 simulated 标记，并补充请求/响应契约测试与脱敏错误处理。
5. 使用真实密钥验证至少一次成功、超时、异常、非法结构、错误 frame_id，再进行真实图片场景测试。

模型 uncertainty 只辅助保守过滤，不表示校准正确率。模型声称 distance_verified 不能开启近摄自动触发；目前只有团队实测后显式启用 demo_distance_verified 的演示约束生效。

## 可选语音

ASR 未实现，不阻塞闭环。页面仅有文本测试入口，只接受白名单明确表达；否定、模糊表达、画面文字不能直接触发运动。支持“我要星芒效果”“拍近一点的细节”“保持当前镜片”“恢复自动”“切到黑柔”等，详见 backend/intents.py。相同输入 3 秒内去重；锁定直到解锁，偏好直到更新或恢复默认。手动选择自动锁定。

未来 ASR 输出文本仍需走相同 submit_intent 和 execute 入口。浏览器麦克风需用户授权与 localhost 或 HTTPS 安全上下文；首版没有持续监听、多轮指导或对话 Agent。
