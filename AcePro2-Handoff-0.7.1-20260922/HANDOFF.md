# 开发交接

## 目标与边界

Ace Pro 2 → Android 手机 → 电脑 → 场景分析 agent，推荐偏振镜（反光）、近摄镜、黑柔镜（人像高光）、星光镜（夜景点光）。用户要求保留完整画面比例，不主动改相机模式、分辨率或录像参数，不为了触发测试自动操作相机快门。

## 当前已完成

- Android App 0.7.1 / versionCode 9 / com.river.acewireless；Camera SDK 2.2.0；真机红米 K40 Gaming / Android 13。
- 前台手动触发按需取预览、等比显示、采集 JPEG；数量 5/10/15/20，间隔 100/200/500ms，默认 10/200。
- 采集完停止相机连接并释放网络绑定，走手机热点向电脑发送。ZIP + manifest，8KB 分块、偏移确认、SHA-256 与重试。图片是真机预览取图，历史批次 970×546，非相机原始照片。
- 手机相机 Wi-Fi + 手机热点 → 电脑的拓扑已传输成功；电脑直接加入相机热点的旧拓扑出现严重停滞，因此不能以 /health 通作为大文件成功依据。
- 电脑接收程序落盘成功；接口 on_batch 目前只打印，没有调用模型。
- 有拍摄事件诊断模式及短按、长按两份日志。两次都是 PHOTO_NORMAL / WORKING，无法据此区分机身快门长按。日志时间是监听启动后的时间，不是按住时长。

## 当前尚未完成（不要在新电脑上误当成回归）

1. 机身长按触发没有可靠公共事件证据。监听模式与采集模式互斥，采集后会断开；锁屏/后台也会停止。
2. agent 服务、异步队列、推理与结果返回手机尚未实现。
3. 失败批次本地持久化/重发入口未实现；4 个未完成上传可暂时占满接收槽位。
4. 接收去重只在内存，重启或 hook 失败后可重复落盘；直接在 hook 中同步调用模型会阻塞全局上传锁。
5. 当前 JPEG 分辨率受预览控件大小影响。完整问题证据见 PROJECT_REVIEW.md。

## 下一步建议

优先实现“机身普通拍照 → 识别新增 JPG → 下载 → 上传”。这不需要视频预览，适合镜片分析，但会响应普通短按，不能声称是长按。SDK 有文件列表/下载入口，reference 中有旧项目代码；旧代码按列表最后一个 JPG 回退可能取错旧照片，必须改成触发前后文件集差异及就绪检测。当前实测只有 WORKING，不应只等 FINISH。

先验证单张原照片下载，然后拆分控制连接/事件监听/取图/上传状态；修复持久化去重和失败重发；接收成功立即返回 received，将模型任务交给独立 worker，以 requestId 查结果。用实际准确率比较单张照片与多帧，别默认十张相似图最好。

若必须长按实体按钮，可以另外验证手机音量键或连接手机的 BLE/HID 按钮；相机自身长按需要厂商确认能力。以上替代方式都还没有实现或实机验证。

## 代码导航（android/ 内）

- app/src/main/java/com/river/acewireless/MainActivity.kt：界面、状态与采集任务编排。
- CameraSession.kt：相机 Wi-Fi、SDK 控制/监听、会话释放。
- AspectPreview.kt：等比显示。
- stream/VideoFrame.kt、VideoDecoder.kt：组帧、硬解码；VideoForwarder.kt 为预留接口。
- analysis/SceneSampler.kt、SceneBatch.kt：抽帧、JPEG、批次。
- analysis/LanBatchSink.kt：网络选择、打包、分块发送。
- analysis/SceneAnalysis.kt：单帧分析预留接口，当前主批次链路未使用。
- desktop/receiver.py：HTTP 接收、校验、落盘、on_batch hook。
- desktop/chunk_upload.py：分块状态、校验与内存去重。

本包保留当前源码、测试、文档和实际 SDK 构件；settings.gradle.kts 改成本地影石仓库。没有改变运行功能。未打包原电脑缓存、IDE 状态、SDK 安装目录、Maven 凭据和签名私钥。旧 vertical-demo 仅保留相关摘录；Linux SDK 不属于当前 Android 构建，未重复塞入包。原始大包和旧工程仍在原电脑。

接收端目前用于可信局域网调试；不是已部署的公网服务。新电脑重新核对热点 IPv4 和端口，不沿用旧电脑 IP。
