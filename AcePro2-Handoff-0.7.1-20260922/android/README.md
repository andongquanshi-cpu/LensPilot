# Ace Pro 2 无线视频 App

项目位置：`.`。
相机通过 Wi-Fi 连接手机；手机同时开启个人热点，电脑连接手机热点接收图片。USB 仅用于安装、操作调试及读取日志，不传输业务图片。

## 当前功能

- Android Camera SDK 2.2.0 初始化、手机已连接热点后的 Wi-Fi 会话。
- 开始/停止预览，连接失败、权限拒绝、断线及无视频数据提示。
- SDK 回调数据复制、有界缓冲、同时间戳片段组帧。
- H.264/H.265 参数集识别，MediaCodec 硬件解码并输出到手机 Surface。
- 接收帧数、渲染输出数、帧率、码率和丢片统计。
- 可插拔的 `VideoForwarder` 转发接口；尚未配置服务器，也没有自动上传。
- 离开页面或锁屏后停止预览并释放相机和网络。当前版本不支持后台推流。

## 使用

1. 红米开启 USB 调试及 USB 安装，连接 Mac，在手机上允许安装。
2. 打开 Ace Pro 2 的 Wi-Fi，手机连接其热点，退出影石官方 App。
3. 打开“ Ace 无线助手”，点“开始预览”，允许附近设备及精确位置权限。SDK 会读取热点名称识别机型；手机定位开关也需要开启。
4. 如机身出现连接授权提示，请允许。收到关键帧后显示画面。
5. 相机侧的预览流不是相机存储卡上的原始高分辨率录像。当前不包含音频转发。

## 开发环境

- Android Studio 2025.3.3 / JBR 21，无需升级 IDE。
- Gradle 8.13 / AGP 8.12.3 / Kotlin 2.3.20。
- compileSdk/targetSdk 36，minSdk 28；已连接测试机为红米 K40 Gaming，Android 13。
- Maven 凭据保存在被 Git 忽略的 `local.properties`，不要分享该文件。

```sh
JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home" ./gradlew :app:assembleDebug :app:testDebugUnitTest
```

APK：`app/build/outputs/apk/debug/app-debug.apk`。

## 转发接口

详见 [FORWARDING.md](FORWARDING.md)。入口：`CameraSession.startForwarding(sink)` / `stopForwarding()`。

## 验证状态

- 0.4.0 APK 编译通过；10 项 Android 单元测试及 2 项 Python 接收协议测试通过。
- 真机已通过 adb 识别。
- 0.2.0 已在红米安装并收到真实 H.264 视频、解码输出；旧版日志存在帧率波动。
- 0.3.0 优化解码排空、积压恢复，增加实际渲染指标及独立 JPEG 抽帧接口；编译与 6 项测试通过。该版流畅度、PixelCopy 抽帧仍待更新手机后验证。
- USB 安装被系统限制，更新通过 Download 中的 APK 手动覆盖安装。蜂窝转发和模型调用尚未实测。

SDK 官方参考：https://insta360develop.github.io/Insta360-Developer_Docs/en/x/android/camera-integration/

## 原始比例与机身使用要求

- 手机预览按照解码器报告的有效画面尺寸及像素比例居中等比显示，空余区域留黑边，不拉伸、不额外裁切。
- 本 App 不调用拍摄模式、拍照/录像启停、录像分辨率、帧率、编码或画面比例的设置接口；只建立预览会话。转发仍沿用相机原始编码画面。
- SDK/固件是否在预览期间限制机身某些操作、录像时预览是否连续，尚需实机验证；不能承诺零影响。
- 此次比例修正版 APK 已编译；实际画面比例仍需更新手机 App 后验证。

## 场景镜片分析（0.4.0）

按需采集默认 10 张原比例 JPEG，支持整组发往同局域网电脑。电脑无需影石 SDK；Python 接收端见 `desktop/receiver.py`。相机长按触发未确认，当前使用 App 测试按钮。操作和接口见 [TRIGGER_BATCH.md](TRIGGER_BATCH.md)。

## 0.7.0 两段无线连接

红米 K40 Gaming 已验证可以同时保持相机 Wi-Fi（wlan0）和个人热点（ap0）。电脑改连手机热点，避免经相机热点转发手机到电脑的数据。实测纯 TCP 1 MB 在约 0.29 秒完整收到；真实图片连续两批各 10 张均已接收、校验并逐张解码，详见 TRIGGER_BATCH.md。

手机上传根据相机接口地址判断目的地：相机网段显式使用相机 Network；其他目的地在停止相机会话并解除进程绑定后按系统路由发送。接收端 receiver.py 依赖同目录 chunk_upload.py，请一起复制。电脑可同时保留有线互联网用于后续 agent。
