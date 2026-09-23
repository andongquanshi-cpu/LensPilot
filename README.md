# 光屿 · AI 光学创作助手

本地优先的影石黑客松原型。它看一张画面，判断该用哪片滤镜，再决定要不要动镜片机构。

支持四片镜片：偏振 CPL、近摄 CLOSE_UP、黑柔 BLACK_MIST、星光 STAR。没有 ND，默认也没有空位。依据不足就 KEEP，保持当前镜片。

相机、模型和设备各自标明是不是模拟。模拟通过不等于硬件已经验证。

## 一次判断怎么走

```
画面 → 视觉模型填场景特征 → 规则校验 → 建议滤镜
```

模型只负责看图，输出主体、一组是否成立的特征、建议镜片、一句理由和不确定度。切不切由 `backend/decision.py` 决定，它只认这些特征，不认理由里的文字。

- 玻璃或水面，并且反光挡住主体：CPL。用户要保留倒影时保持。
- 有小而分开的点状亮光：STAR。大块发光面不算。
- 有人脸并且有高光：黑柔。用户要清晰细节时保持。
- 人像同时又有点状亮光：默认黑柔，除非用户明确要星芒。
- 近景可以标成候选。自动切近摄要等实测距离打开 `demo_distance_verified`。
- 不确定度高于 0.65，或同一建议还没连续出现约 3 次：KEEP。

## 现在有两条入口

**本机网页**只跟着最新一批照片走：收到多少张，分析时四片镜轮流亮，结论出来后建议的那一片撑满画面。

**实拍批次**走通讯同学的手机 App。Ace Pro 2 的预览图经手机发到这台电脑，落成一批 JPEG。程序只分析其中的 `frame-01.jpg`，把结果写成同目录的 `result.json`。这一步不发切镜指令，文件里的 `motion` 是 `not_sent`。镜片板还没接入。

## 打开控制台

在项目目录执行：

```powershell
.\scripts\start.ps1
```

浏览器打开 http://127.0.0.1:8000。页面读最新一批照片和分析结果，不用贴凭证。第一次启动仍会生成 `data/local-access.json`，里面的 `control_token` 和 `device_token` 留给其它接口，不要分享。

端口已经开着就直接打开网页，不要再启动一次。Ctrl+C 停止。

PowerShell 禁止运行脚本时，可以改为：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 8192 --no-access-log
```

一批照片到齐后，页面先写出张数，再进入分析，最后停在建议的镜片上。结果是保持时，四片都不放大，句子是「先不动」。镜片还没接入，页面没有上镜前后的对比图。

## 接收一批实拍

手机连相机 Wi-Fi，并打开个人热点。电脑只连手机热点，不要改走相机热点。

在交接包目录启动接收端（Python 3.10+，只用标准库）：

```powershell
py -3 android/desktop/receiver.py --port 8765 --output runtime/received_batches
```

交接包在 `AcePro2-Handoff-0.7.1-20260922`。看电脑连接热点那张网卡的 IPv4，不要填有线网地址。手机浏览器先打开 `http://该地址:8765/health`，应看到 `ace-batch-receiver`。App 里的接收地址填 `http://该地址:8765/batch`。

整批收到后，图片在：

```
AcePro2-Handoff-0.7.1-20260922/runtime/received_batches/batch-*/
```

每批有 `manifest.json`、`frame-01.jpg` 到后续帧，以及分析完成后的 `result.json`。接收窗口出现 `ANALYZED` 表示这一批已经分析完。同一 `requestId` 不会重复分析。

看图使用阿里云百炼的视觉模型。在项目根目录的 `.env` 里设置，不要写进 `config.json`，也不要提交 Git：

```
OPTIC_PROVIDER=dashscope
OPTIC_MODEL=qwen3-vl-plus
OPTIC_BASE_URL=https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
OPTIC_API_KEY=
```

`OPTIC_PROVIDER=mock` 时不调用真实模型，控制台仍用内置演示场景。

## 安装

建议 Python 3.13 或 3.14、Node.js 22.12+。当前验证环境是 Windows / Python 3.14.3 / Node 25.9.0。

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

`requirements.txt` 是运行依赖，`requirements-dev.txt` 是测试依赖，`requirements-camera.txt` 是可选的视频和摄像头依赖。前端用已提交的 `package-lock.json` 执行 `npm ci`。

开发时可以另开一个终端，在 `frontend` 里执行 `npm run dev`，浏览器访问 http://127.0.0.1:5173。Vite 会把 `/api` 和 `/ws` 转到本机后端。

## 代码在哪儿

| 文件 | 作用 |
| --- | --- |
| `backend/vlm.py` | 调用百炼视觉模型，整理成场景分析结果 |
| `backend/vision.py` | 模拟分析，以及结果校验 |
| `backend/decision.py` | 特征变成滤镜建议，含防抖和冷却 |
| `backend/batch_job.py` | 一批图只分析第一张，写出 `result.json` |
| `backend/service.py` | 控制台用的设备状态机 |
| `frontend/src` | 一批照片的建议页 |

更细的协议、相机接入和部署说明在 `docs/PROTOCOL.md`、`docs/CAMERA_AND_MODEL.md`、`docs/DEPLOYMENT.md`、`docs/VALIDATION.md`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
Set-Location frontend
npm run build
npm audit
```

这些测试覆盖规则和接口。通过不等于镜片机构已经实测。
