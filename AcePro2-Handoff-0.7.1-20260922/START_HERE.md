# Ace Pro 2 无线项目迁移包 · 0.7.1

2026-09-22 整理。先完整解压，再操作。本包是可继续开发的当前原型，不代表快门长按或 agent 已完成。

## 先跑通手机到电脑

1. 新电脑安装 Python 3.10 或以上。接收程序仅用标准库，不用 pip 安装依赖。
2. 手机连接 Ace Pro 2 的 Wi-Fi，并开启手机个人热点；电脑连接手机热点。当前红米 K40 Gaming 已验证可同时使用这两条链路。电脑如需联网调用模型，可另接有线网络。不要让电脑也接相机热点来复用之前不稳定的传输路径。
3. macOS 在终端运行 `bash start_receiver.command`；Windows 双击 `start_receiver.bat`，或在终端运行 `py -3 android/desktop/receiver.py --output runtime/received_batches`。允许 Python 在当前受信任局域网接收入站连接。
4. 查看电脑**连接手机热点的网卡 IPv4**：Mac 用 `ifconfig`，Windows 用 `ipconfig`。历史地址 192.168.179.80 只是示例，换电脑后必须重新确认，不能填有线网卡地址。
5. 手机浏览器打开 `http://电脑热点网卡IP:8765/health`，应得到成功回应。App 接收地址填写 `http://电脑热点网卡IP:8765/batch`。端口统一为 **8765**，不是 8796。
6. 手机已有 0.7.1 可继续使用；如需安装，将 `artifacts/AceWireless-0.7.1.apk` 复制到手机，在文件管理器手动安装。当前手机 USB 安装受限，USB 调试不代表可以 adb 安装。
7. 保持 App 前台，退出“监听拍摄事件”模式，再使用界面中的批次采集按钮。先测试默认 10 帧 / 200ms；等待采集、停止相机连接、上传完成。
8. 新图片在本包的 `runtime/received_batches/batch-*/`，每批有 manifest 和 JPEG。接收端出现 `RECEIVED` 且 commit completed=true 才表示整批收到；GET /health 成功只证明连通。

脚本启动时若提示端口已占用，先确认是否已有接收端运行，不能重复启动同一端口。Ctrl+C 停止。直接运行 android/desktop/receiver.py 而不传 --output 时，默认保存到**当前工作目录**的 received_batches。

## 在 Android Studio 继续开发

- Open 选择本包 `android/` 文件夹；不是包根目录，也不是 android/app 子目录。
- 使用 JDK 21，安装 Android SDK Platform 36 与 Gradle 提示的 Build Tools。项目已固定 Gradle 8.13、AGP 8.12.3、Kotlin 2.3.20，不必先升级所有依赖。
- Android Studio 通常会生成本机 local.properties；命令行开发可按 android/local.properties.example 配置 sdk.dir。原电脑路径和 Maven 密码没有打包。
- 当前影石 Camera SDK 2.2.0 及相关私有构件在 android/vendor-maven。已修改**迁移副本**的 settings.gradle.kts 使用该仓库；不需要旧电脑的 Maven 凭据。公共依赖、Gradle 和 Android SDK 首次仍需联网获取。
- Mac/Linux：`cd android`，`chmod +x gradlew`，`./gradlew :app:assembleDebug :app:testDebugUnitTest`。
- Windows：在 android 目录运行 `gradlew.bat :app:assembleDebug :app:testDebugUnitTest`。
- 新构建 APK：android/app/build/outputs/apk/debug/app-debug.apk。

**签名提醒：**本包不含旧电脑的 debug.keystore。随包 APK 可以继续按原签名安装；新电脑默认生成的调试签名不同，可能不能覆盖手机上的旧版。需要保留旧版数据时应另行安全迁移调试签名；不需要保留时可由你手动卸载旧版再装新构建，卸载会清除 App 数据及设置。不要把该问题误判成代码编译失败。

## 交接资料

- HANDOFF.md：当前链路、关键代码、下一步工作。
- android/PROJECT_REVIEW.md：完整审阅及已复现问题。
- android/TRIGGER_BATCH.md、SCENE_ANALYSIS.md、FORWARDING.md：采集与接口说明。
- reference/：快门短按/长按日志和旧照片下载代码摘录，仅供参考。
- sample-data/：已有 5 批实机图片，不是本次启动接收端的新数据。
- sdk/：SDK 构件清单和范围说明。
- validation/：迁移副本构建与测试记录。

可在首次运行前执行 `python3 verify_package.py`（Windows 用 `py -3 verify_package.py`）检查随包文件是否完整。开发改动后校验变化是正常的。
