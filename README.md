# 光屿 · AI 光学创作助手

可运行的本地优先影石黑客松原型：画面 → 可替换视觉适配器 → 规则校验与防抖 → 设备状态机 → 到位反馈 → 中文控制台。

当前工作区原先为空，采用 Python/FastAPI + React/TypeScript/Vite + WebSocket + SQLite。支持 CPL、CLOSE_UP、BLACK_MIST、STAR；无 ND。默认没有空位。**相机、模型、设备三部分独立标记模拟状态，模拟不代表真实硬件验证。**

## 本机立即运行

本次开发已在工作区安装 `.venv` 和前端依赖，并生成前端构建。Windows PowerShell 在项目目录执行：

```powershell
.\scripts\start.ps1
```

打开 http://127.0.0.1:8000。首次启动自动生成 `data/local-access.json`，用文本编辑器打开，将 `control_token` 粘贴到页面连接。该文件包含本机凭证，已排除 Git，请勿分享。前端不接收模型 API 密钥，控制凭证只保留在页面内存，刷新需重新输入。不要把 control_token 和 device_token 混用。

若端口已启动，直接打开网页，不要重复启动。当前使用单后端进程；Ctrl+C 停止。

如果电脑的 PowerShell 策略不允许执行脚本，无需修改系统策略，可直接执行 `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 8192 --no-access-log`。

## 从干净环境安装

建议 Python 3.13 或 3.14、Node.js 22.12+ LTS。此次验证环境为 Windows / Python 3.14.3 / Node 25.9.0。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-camera.txt
Copy-Item .env.example .env
Set-Location frontend
npm ci
npm run build
Set-Location ..
.\scripts\start.ps1
```

基础依赖使用 requirements.txt；测试依赖 requirements-dev.txt；视频/摄像头依赖 requirements-camera.txt 可选。直接依赖固定版本；requirements-lock.txt 是本次干净虚拟环境完整解析快照（包含视频和测试依赖），同环境可 `pip install -r requirements-lock.txt`。其他平台应在其独立虚拟环境安装直接依赖、运行测试并 `pip freeze > requirements-lock.<platform>.txt`，不要假设 Windows 锁定快照是跨平台验证。前端使用提交的 package-lock.json 与 npm ci。

开发时可分别运行后端及 `frontend` 下 `npm run dev`，浏览器访问 http://127.0.0.1:5173；Vite 将 /api 和 /ws 代理到本地后端。生产预览由 FastAPI 直接提供编译页面。依赖配置参照 [Vite 官方指南](https://vite.dev/guide/) 与 [FastAPI WebSocket 文档](https://fastapi.tiangolo.com/advanced/websockets/)。

## 3 分钟模拟演示

1. 连接控制台，点击“演示画面”。预览是明确标记的合成山水画面，不是 Ace Pro 2 实拍。
2. 在录像状态选择“我确认当前未录像（手动声明）”。默认未知状态禁止自动切换；这是用户声明，不是假装读取到相机状态。
3. 打开底部“联调详情与演示设置”，选“点状亮光 · 星光”。默认约三次连续判断后出现运动请求，再等待模拟到位和稳定时间。
4. 观察当前实际镜片由 CPL 到 STAR，目标与实际分开显示，事件时间线记录过程，切换前/稳定后画面各保存一张。
5. 切换预设为人像高光演示黑柔，反光遮挡演示偏振；一般场景 KEEP 不运动。
6. “拍摄锁定”阻止后续自动/手动运动；“解除锁定”或“恢复自动”解锁。点击镜片是单次手动选择并锁定，再次选择前需解锁。
7. 文本输入“保留倒影”“我要清晰细节”“我要星芒效果”等，查看有效意图；“不要切到黑柔”等不会被误识别为动作。

近摄自动策略默认保守，只有完成实测并配置 `demo_distance_verified=true` 才开启固定演示距离约束。没有自动测距。也可以通过手动选择演示 CLOSE_UP 槽位运动。

单张图片只分析一次，采集时镜片未知时仅展示分析；不能将同一张图重复计数制造自动切换。真实视频文件可以在模拟设备下演示完整工作流；此时镜片关联为模拟位置，不表示录像被真实滤镜改变。真实设备模式下历史视频只分析，不自动驱动硬件。

## 模块与接口

- backend/models.py：稳定数据模型；config.py：配置校验与后端凭证。
- sources.py / frames.py：受控画面源、JPEG 标准化、最新帧缓存。
- vision.py：模型边界、预设模拟分析、严格结果校验。
- decision.py：四种创作策略、意图优先级、连续判断、保持与冷却。
- service.py：单设备状态机、统一执行入口、失效控制、到位反馈与快照。
- transport.py：模拟设备与双向桥接传输；events.py：有界日志与 SQLite。
- api.py：鉴权 HTTP、前端事件 WebSocket、设备 WebSocket。
- frontend/src：中文控制台；bridge：电脑端画面与固件协议插件桥接。

主要 HTTP：GET /api/health、/api/state、/api/config、/api/preview、/api/capture-context、/api/snapshots/{before|after}；POST /api/source、/api/source/{pause|resume}、/api/frames、/api/mode、/api/select、/api/intent、/api/recording、/api/device/sync、/api/demo/scenario。除健康检查外需 Bearer 鉴权；上传与采集上下文允许设备凭证。WebSocket /ws/events 与 /ws/device 在首条消息鉴权，不将凭证放 URL。详细请求模型见本地 `/docs` OpenAPI。

默认控制、预览和设备接口监听本机，凭证不写应用日志。模型错误只记录异常类型，不记录图片、密钥、完整提供商错误响应。JSON 日志关联 frame_id / decision_id / command_id；记录模型耗时、帧年龄、指令耗时。SQLite 默认最多 1000 条事件、7 天；JSON 日志单文件 1 MB、2 个备份。配置快照不保存密钥，实际位置永不从数据库恢复。

## 接真实设备前阅读

- [设备协议与通信团队资料清单](docs/PROTOCOL.md)
- [相机/图片桥接、模型接入与语音边界](docs/CAMERA_AND_MODEL.md)
- [单进程部署与可选 ECS](docs/DEPLOYMENT.md)
- [验证记录和剩余限制](docs/VALIDATION.md)

真实视觉供应商尚未指定，因此真实 API 适配器未实现；非 mock provider 会清晰报错。Ace Pro 2 专有画面接口、ESP32 固件协议及到位可信度等待团队资料。软件接口、桥接程序和模拟链路已经实现，可以在资料到齐后逐项联调，不需要购买云服务器。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
Set-Location frontend
npm run build
npm audit
```

测试覆盖模型非法值/超时、四镜片、KEEP/CLEAR、抖动、录像保护、旧结果失效、接收与到位区别、去重、重连、最新帧、重启同步、HTTP/WS 闭环和真实视频文件解码。模拟契约测试通过不等于设备实测通过。
