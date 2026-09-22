import asyncio
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import secrets
import time
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from .config import load_settings
from .models import StrictModel, Filter, CommandFeedback
from .service import Controller
from .sources import SourceManager
from .frames import normalize_image
from .transport import BridgeTransport


class SourceRequest(StrictModel):
    kind: Literal['demo', 'video', 'camera', 'upload', 'ace_bridge']
    media_id: str | None = None
    camera_index: int = 0


class ModeRequest(StrictModel):
    action: Literal['auto', 'pause', 'lock', 'unlock']


class SelectRequest(StrictModel):
    target: Filter


class TextRequest(StrictModel):
    text: str = Field(min_length=1, max_length=160)


class RecordingRequest(StrictModel):
    value: Literal['unknown', 'recording', 'stopped']


class ScenarioRequest(StrictModel):
    scenario: Literal['reflection', 'detail', 'portrait', 'lights', 'neutral']


class BridgeMessage(StrictModel):
    type: Literal['heartbeat', 'position', 'feedback', 'recording']
    connection_session_id: str
    query_id: str | None = None
    actual_slot: int | None = None
    position_verified: bool = False
    feedback: CommandFeedback | None = None
    recording: Literal['unknown', 'recording', 'stopped'] | None = None


def create_app(config=None):
    config = config or load_settings()
    if not config.control_token or not config.device_token:
        path = Path(config.database).parent / 'local-access.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = json.loads(path.read_text()) if path.exists() else {}
        saved.setdefault('control_token', secrets.token_urlsafe(32))
        saved.setdefault('device_token', secrets.token_urlsafe(32))
        path.write_text(json.dumps(saved, indent=2), encoding='utf-8')
        try:
            path.chmod(0o600)
        except OSError:
            pass
        config.control_token = config.control_token or saved['control_token']
        config.device_token = config.device_token or saved['device_token']

    @asynccontextmanager
    async def lifespan(app):
        app.state.controller = Controller(config)
        app.state.sources = SourceManager(app.state.controller)
        await app.state.controller.start()
        yield
        await app.state.sources.stop()
        await app.state.controller.close()

    app = FastAPI(title='光屿 · AI 光学创作助手', version='0.1.0', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.allowed_origins, allow_methods=['GET', 'POST'],
                       allow_headers=['Authorization', 'Content-Type', 'X-Source-Session', 'X-Sequence', 'X-Captured-At', 'X-Capture-State-Version'])

    def auth(authorization: str = Header(default='')):
        if not hmac.compare_digest(authorization, 'Bearer ' + config.control_token):
            raise HTTPException(401, '请输入本机控制凭证')

    def upload_auth(authorization: str = Header(default='')):
        if not any(hmac.compare_digest(authorization, 'Bearer ' + key) for key in (config.control_token, config.device_token)):
            raise HTTPException(401, '上传凭证无效')

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'version': '0.1.0', 'deployment': 'single-process'}

    @app.get('/api/state', dependencies=[Depends(auth)])
    async def state():
        return app.state.controller.snapshot()

    @app.get('/api/config', dependencies=[Depends(auth)])
    def public_config():
        data = config.model_dump(mode='json')
        # Do not expose backend locations or optional provider URLs to browsers.
        for key in ('base_url', 'database'):
            data.pop(key, None)
        data['media_files'] = list(config.media_files)
        return data

    @app.post('/api/source', dependencies=[Depends(auth)])
    async def source(body: SourceRequest):
        return {'source_session_id': await app.state.sources.start(**body.model_dump())}

    @app.post('/api/source/{action}', dependencies=[Depends(auth)])
    async def source_control(action: Literal['pause', 'resume']):
        c = app.state.controller
        if c.source['status'] not in ('running', 'paused'):
            raise ValueError('输入源已结束或断开，请重新选择')
        c.invalidate()
        c.source['status'] = 'paused' if action == 'pause' else 'running'
        return c.source

    @app.post('/api/frames', dependencies=[Depends(upload_auth)])
    async def upload(request: Request, x_source_session: str = Header(), x_sequence: int = Header(ge=0), x_captured_at: float = Header(), x_capture_state_version: int | None = Header(default=None, ge=0)):
        import math
        c = app.state.controller
        if c.source['kind'] not in ('upload', 'ace_bridge'):
            raise ValueError('请先启动图片上传或相机桥接会话')
        if not math.isfinite(x_captured_at):
            raise ValueError('采集时间无效')
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > config.upload_max_bytes:
                raise HTTPException(413, '图片过大')
        jpeg = normalize_image(bytes(content), config)
        return c.ingest(jpeg, x_source_session, x_sequence, x_captured_at, x_capture_state_version)

    @app.get('/api/capture-context', dependencies=[Depends(upload_auth)])
    async def capture_context():
        c = app.state.controller
        return {'source_session_id': c.source['session_id'], 'state_version': c.state.state_version,
                'capture_allowed': c.state.connection == 'connected' and c.state.motion == 'idle',
                'actual_filter': c.state.actual_filter}

    @app.get('/api/preview', dependencies=[Depends(auth)])
    async def preview():
        frame = app.state.controller.frames.latest
        if not frame:
            return Response(status_code=204)
        return Response(frame.jpeg, media_type='image/jpeg', headers={'Cache-Control': 'no-store', 'X-Frame-Id': frame.meta.frame_id})

    @app.get('/api/snapshots/{name}', dependencies=[Depends(auth)])
    async def snapshot_image(name: Literal['before', 'after']):
        frame = app.state.controller.snapshots.get(name)
        if not frame or time.time() - frame.meta.received_at > config.snapshot_ttl_seconds:
            raise HTTPException(404, '暂无有效快照')
        return Response(frame.jpeg, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.post('/api/mode', dependencies=[Depends(auth)])
    async def mode(body: ModeRequest):
        app.state.controller.set_mode(body.action)
        return app.state.controller.snapshot()

    @app.post('/api/select', dependencies=[Depends(auth)])
    async def select(body: SelectRequest):
        return {'message': await app.state.controller.manual(body.target)}

    @app.post('/api/intent', dependencies=[Depends(auth)])
    async def intent(body: TextRequest):
        return await app.state.controller.submit_intent(body.text)

    @app.post('/api/recording', dependencies=[Depends(auth)])
    async def recording(body: RecordingRequest):
        app.state.controller.set_recording(body.value, '用户手动声明，非相机检测')
        return app.state.controller.state

    @app.post('/api/demo/scenario', dependencies=[Depends(auth)])
    async def scenario(body: ScenarioRequest):
        c = app.state.controller
        c.invalidate()
        c.vision.scenario = body.scenario
        c.event('demo', '模拟分析预设已切换；不代表真实画面识别')
        return {'scenario': body.scenario}

    @app.post('/api/device/sync', dependencies=[Depends(auth)])
    async def sync():
        c = app.state.controller
        if c.state.pending or not c.transport:
            raise ValueError('设备运动中或未连接，暂不能同步')
        await c.resync('用户请求查询实际位置')
        return {'message': '已请求位置同步'}

    async def ws_auth(ws, token):
        origin = ws.headers.get('origin')
        if origin and origin not in config.allowed_origins:
            await ws.close(code=1008)
            return False
        await ws.accept()
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=5)
            if len(raw) > 2048:
                raise ValueError()
            obj = json.loads(raw)
            if obj.get('type') != 'auth' or not hmac.compare_digest(str(obj.get('token', '')), token):
                raise ValueError()
            return True
        except Exception:
            await ws.close(code=1008)
            return False

    @app.websocket('/ws/events')
    async def events(ws: WebSocket):
        if not await ws_auth(ws, config.control_token):
            return
        try:
            while True:
                await asyncio.wait_for(ws.send_json(app.state.controller.snapshot()), timeout=2)
                await asyncio.sleep(0.5)
        except (WebSocketDisconnect, RuntimeError, TimeoutError):
            pass

    @app.websocket('/ws/device')
    async def device(ws: WebSocket):
        if not await ws_auth(ws, config.device_token):
            return
        c = app.state.controller
        if config.transport != 'bridge' or c.state.connection != 'disconnected':
            await ws.close(code=1008, reason='bridge disabled or device occupied')
            return
        transport = BridgeTransport(ws)
        try:
            await c.connect(transport)
            session = c.state.connection_session_id
            while True:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=config.heartbeat_timeout)
                if len(raw) > 8192:
                    raise ValueError('message too large')
                message = BridgeMessage.model_validate_json(raw, strict=True)
                if c.transport is not transport or message.connection_session_id != c.state.connection_session_id:
                    continue
                c.last_seen = time.time()
                if message.type == 'position':
                    await c.position(session, message.query_id, message.actual_slot, message.position_verified)
                elif message.type == 'feedback' and message.feedback:
                    await c.feedback(message.feedback)
                elif message.type == 'recording' and message.recording:
                    c.set_recording(message.recording, '相机桥接报告（可信度取决于适配器）')
        except (WebSocketDisconnect, ValueError, RuntimeError, TimeoutError):
            pass
        finally:
            if c.transport is transport:
                c.disconnect()

    dist = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
    if dist.exists():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

        @app.get('/')
        def index():
            return FileResponse(dist / 'index.html')
    return app
