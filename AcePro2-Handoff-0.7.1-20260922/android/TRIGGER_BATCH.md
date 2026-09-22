# 已验证：手机热点中转（0.7.0）

2026-09-22 真机闭环完成，两次各 10 张，共 20 张 JPEG 均已落盘并成功解码。

- 相机热点 → 红米 Wi-Fi（192.168.42.2）；红米同时开个人热点 acepro。
- 电脑连接手机热点，当前地址 192.168.179.80。手机 App 当前地址 `http://192.168.179.80:8765/batch`。
- 电脑有线网络可保留供 agent 上网。USB 仅用于调试操作，业务图片全部经 Wi-Fi 传输。
- 第一批：batch-xn_lq9jw，10 张 970×546，采样跨度 2068 ms，ZIP 1,181,177 字节；第一块确认到整组确认约 13 秒。
- 第二批：batch-x6p6nrta，10 张，ZIP 1,176,028 字节；整组校验通过。两批图片均已逐张解码检查。
- 当前采用按需取流、默认 10 张/200 ms、停流后分块发送。未改相机拍摄参数、未额外裁剪画面。
- 长按相机快门仍未接入；agent 尚未对接，on_batch 仅保存和打印。
- 手机热点或电脑重新连接后 DHCP 地址可能变化，需要同步修改 App 中地址。

接收程序启动：在 desktop 目录执行 `python3 receiver.py`。必须保留同目录的 chunk_upload.py。
以下为早期相机热点直连的操作和排查记录，该拓扑在本次现场测试不稳定，优先采用以上已验证拓扑。

# 手机中转到电脑（0.4.0）

路径：Ace Pro 2 → 相机 Wi-Fi → Android SDK / 手机解码 → 一组 JPEG → 电脑接收端 → agent。
电脑只接收标准 JPEG，不需要影石 SDK。相机热点能否同时接纳两端、是否隔离客户端，尚待实机验证。

## 测试步骤

1. 将 desktop/receiver.py 拷到另一台有 Python 3 的电脑，连接相机热点。
2. 执行 `python3 receiver.py --output received_batches`（Windows 可用 `py -3`）。允许电脑防火墙接收该局域网的 TCP 8765。
3. 查看电脑在相机 Wi-Fi 下的 IPv4 地址。手机浏览器访问 `http://电脑IP:8765/health`，应出现服务名称。电脑 localhost 成功不能证明手机可达。
4. 手机 App 开始预览，填写 `http://电脑IP:8765/batch`，默认 10 张 / 200 ms，点「采集一组画面（测试触发）」。留空只采集，不上传。
5. 电脑 received_batches 下生成完整批次目录，含 manifest.json 和 frame-01.jpg 等。成功回执只表示接收完成，不代表 agent 已分析。
6. 在 receiver.py 的 on_batch(directory, metadata) 对接 agent 队列。整组一次提交，按 requestId 去重。电脑连接相机热点时通常还需要以太网/另一网卡上网，才能调用云端模型。

若手机无法访问 /health，检查两端地址、防火墙、第二设备能否加入热点及客户端隔离。不要先假设 SDK 不兼容；网络层需单独排查。该接收端用于受信任局域网调试，无鉴权，不应暴露到公网。

## 数据约定

POST /batch，Content-Type: application/zip，固定 Content-Length。
ZIP 内 manifest.json 包含 requestId、source、triggeredAtMs、intervalMs、frames。
每帧含 file、width、height、sampledAtMs、renderSerial、installedFilter（未知为 null）。
时间单位 ms，为手机单调时钟，不能与电脑墙上时间直接比较；不是相机曝光时间。
图片长边最多 1280，等比缩放，无额外裁剪；抽取显示预览，不是存储卡原始录像。
批次最多 20 张，原 JPEG 合计最多 20 MB；失败不发送部分批次；不自动重试上传以免重复分析。
局域网 HTTP 请求在后台线程使用进程绑定的相机 Wi-Fi。停止页面会取消任务；已发送到电脑的数据不会撤回，底层阻塞 IO 最迟依网络超时退出。

## 相机快门长按的限制

官方定义长按快门为取消并删除录像：
https://onlinemanual.insta360.com/acepro2/en-us/camera/basicuse/buttoninstructions
已检查的 Android SDK 2.2.0 公开接口尚未确认独立长按事件。捕获状态变化不等同于长按，不能可靠替代。
因此 CAMERA_SHUTTER_LONG_PRESS 仅保留为未启用入口。需向影石确认可用按键事件、固件行为及是否支持不影响拍摄的自定义触发；目前不要以录像时长按作为测试方式。

## 验证范围

编译、采集约束单元测试和电脑接收端本地协议测试可验证软件结构。相机热点双客户端互通、手机更新后抽帧/发送、agent 推理尚需实机联调。

## 0.5.0 按需模式

安装 AceWireless-0.5.0.apk 后无需先手动开始预览，点击「按需采集并发送」会启动短时预览、等待新画面、采集设定张数，随后停止会话再上传。首次权限授权仍需允许；准备阶段最多等待 35 秒。失败也会清理预览会话。
上传显式绑定相机 Wi-Fi Network，不依赖停止会话后的默认网络。未调整相机录像参数或画面比例。手动预览按钮保留用于调试。
电脑接收端增加 RECEIVING 日志区分连接已建立但正文未收完与完整 RECEIVED。修改 receiver.py 后需要 Ctrl+C 并重新启动。
当前尚未证实此前上传卡住由视频带宽造成，0.5.0 用于消除同时取流和上传并进一步定位。长按相机快门仍不支持，SDK/固件需确认。

## 0.6.0 分块传输

实测相机热点上 512 B、4 KB、16 KB 裸 TCP 成功，但 64 KB 有中断，不能证明具体驱动/路由故障。整包传输改为 8 KB 分块，每块等待电脑确认，网络异常最多重试 4 次，整个提交最多 180 秒。
接收端需要同时复制 receiver.py 和 chunk_upload.py。原 POST /batch 仍兼容；新版以查询参数 upload/total/sha256/offset/commit 发送分块。重发同一块不重复追加，完整 ZIP 校验 SHA-256 后才发布批次并触发 on_batch。
部分上传只暂存在内存，15 分钟无活动在后续请求时清理，最多 4 个未完成上传；接收端重启后手机可从 0 重新发送。完成请求缓存最多 64 个 / 15 分钟用于提交去重，持久化的 agent 去重仍需按 requestId 实现。
手机进度显示的是电脑确认收到的字节。数据校验失败不交给 agent。链路可靠性仍以实机完整批次结果为准。

### 0.6.1 连接复用

0.6.0 实机一组 1,307,496 字节，确认收到 319,488 字节后多次建连失败，尚未完成。0.6.1 改为 HTTP/1.1 持续连接，手机完整消费响应后保留连接供下一块复用，出错才关闭；接收端支持并发连接并对分块状态加锁。测试验证同一 TCP 连接可连续确认多个块。

## 0.7.1 只读拍摄事件诊断

新增「监听拍摄事件（不开视频流）」：连接 SDK 后读取当前 FunctionMode，记录 CaptureStatusListener 全部 8 类回调。没有按键按下/松开回调；CAPTURE_TIME 是 SDK 拍摄时间，不能解释成物理按键持续时长。连接初始化回调也不算用户按键。
该模式不启动预览、不调用 startCapture/stopCapture/setValue、不上传；与采集流程互斥，须先停止监听再开启预览/采集。仅前台保持监听，离开页面会断开。
日志在 App 私有 files/capture-events.log，每次监听重置并限制约 1 MB，同时写 logcat 标签 AceCaptureEvent。可以通过 adb exec-out run-as com.river.acewireless cat files/capture-events.log 读取。
需要机身处于拍照模式后实测短按、长按的事件差异；尚未完成物理按键验证，不表示已经支持识别长按。

### 2026-09-22 快门实测

用户在普通拍照模式分别完成短按、长按；两次日志均确认 PHOTO_NORMAL，均仅观察到一条 WORKING · PHOTO_NORMAL。两次是不同监听会话（短按会话 1790068415548，长按会话 1790068584106），原始记录保存在本机被忽略的 .sdk-inspect/short-press-events.log 与 long-press-events.log。
+18939 ms / +4942 ms 是从各自监听启动到回调的时间，不是按住快门时长。当前公开监听未观察到可以区分短按/长按的事件；不能据此启用“仅长按触发”。可以另行实现“收到普通拍照 WORKING 事件就触发”，但那会同时响应短按，尚未实施该替代交互。机身长按后实际拍摄张数未由用户确认。
