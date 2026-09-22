# 迁移验证 · 2026-09-22

- 在迁移副本运行 assembleDebug 和 testDebugUnitTest：成功，11 项 Android 测试通过。
- 私有构件使用随包 vendor-maven；临时 local.properties 仅有 sdk.dir，无 Maven 凭据。
- 构建使用本机已缓存的公共依赖，--offline 成功；不能据此宣称新电脑完全离线可构建。
- 在迁移副本运行 python3 -m unittest discover -s desktop -v：8 项通过（包括真实本地 HTTP 分块、重复 commit、整包和非法请求）。
- 5 批共 50 张 JPEG 全部通过 sips 解码转 PNG；接收端独立端口启动 /health 通过。见 samples-and-startup.json。
- 没有在新电脑上测试，也没有新增相机长按或 agent 功能。
