# 随包影石依赖

android/vendor-maven 包含当前运行依赖所需的影石 Maven 构件及元数据；settings.gradle.kts 对这些 group 使用本地仓库，不需要原电脑的 Maven 用户名和密码。DEPENDENCIES.json 为构件清单。

这不是完整 Android 离线开发环境。首次构建仍需联网下载 Gradle、AGP、Kotlin、AndroidX 等公共依赖，并安装 Android SDK 36/JDK 21。升级影石 SDK 需要重新取得对应版本构件或配置官方 Maven。

Linux CameraSDK/MediaSDK 大包不属于当前 Android App 的运行依赖，未重复放入本包。这里只迁移现有工程实际使用的 Android SDK；保留厂商原构件内容及许可信息，用于项目开发交接。
