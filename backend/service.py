import asyncio
import time
from .config import Settings
from .models import DeviceState, Filter, FilterCommand, SystemEvent, FrameMetadata, UserIntent, Decision, uid
from .frames import LatestFrames, Frame
from .events import EventStore
from .decision import DecisionEngine
from .vision import validate_analysis
from .vlm import create_vision
from .transport import MockTransport
from .intents import parse_intent


class Controller:
    def __init__(self, config: Settings, vision=None):
        self.config = config
        self.state = DeviceState(simulated=config.transport == 'mock')
        self.frames = LatestFrames()
        self.vision = vision or create_vision(config)
        self.engine = DecisionEngine(config)
        self.store = EventStore(config)
        self.intent = UserIntent()
        self.last_analysis = None
        self.last_decision = None
        self.analysis_meta = None
        self.transport = None
        self.source = dict(kind='none', status='stopped', session_id=uid(), sequence=-1, simulated=False, label='尚未选择画面源')
        self.snapshots = {}
        self.capture_after = False
        self.query_id = None
        self.last_seen = time.time()
        self.query_started_at = 0
        self.last_intent_text = ''
        self.last_intent_at = 0
        self.tasks = []
        self.model_latency_ms = None
        self.model_status = 'idle'
        self.recording_updated_at = 0

    def event(self, kind, message, **kwargs):
        self.store.add(SystemEvent(type=kind, message=message, **kwargs))

    def invalidate(self):
        self.state.state_version += 1
        self.engine.reset()
        self.frames.pending = None

    async def start(self):
        if self.config.transport == 'mock':
            await self.connect(MockTransport(self))
        self.tasks = [asyncio.create_task(self.analysis_loop()), asyncio.create_task(self.watchdog())]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.transport:
            await self.transport.close()
        self.store.close()

    async def connect(self, transport):
        self.transport = transport
        self.state.connection_session_id = uid()
        self.state.simulated = transport.simulated
        self.state.recording = 'unknown'
        self.state.recording_source = 'unknown'
        self.last_seen = time.time()
        self.state.pending = None
        self.state.target_filter = None
        self.state.command_status = 'none'
        await self.resync('连接后查询实际槽位')

    async def resync(self, reason):
        self.invalidate()
        self.state.connection = 'synchronizing'
        self.state.motion = 'error' if self.state.error else 'idle'
        self.state.actual_filter = self.state.actual_slot = None
        self.state.position_verified = False
        self.query_id = uid()
        self.query_started_at = time.time()
        self.event('synchronizing', reason)
        if self.transport:
            try:
                await self.transport.send(dict(type='query_position', query_id=self.query_id,
                                              connection_session_id=self.state.connection_session_id))
            except Exception:
                self.disconnect('位置查询发送失败')

    def disconnect(self, message='设备连接已断开'):
        self.invalidate()
        self.state.connection = 'disconnected'
        self.state.connection_session_id = None
        self.query_id = None
        self.state.motion = 'error'
        self.state.actual_filter = self.state.actual_slot = None
        self.state.position_verified = False
        self.state.recording = 'unknown'
        if self.state.pending:
            self.state.command_status = 'unknown'
        self.state.pending = None
        self.state.error = message
        self.transport = None
        self.event('disconnected', message)

    async def position(self, session, query_id, slot, verified):
        if session != self.state.connection_session_id or query_id != self.query_id or self.state.pending:
            return
        reverse = {v: k for k, v in self.config.slots.items()}
        if not verified or slot not in reverse:
            self.state.error = '未验证到位：需要可信的位置同步反馈'
            self.state.motion = 'error'
            return
        self.query_id = None
        self.invalidate()
        self.state.connection = 'connected'
        self.state.actual_slot, self.state.actual_filter = slot, reverse[slot]
        self.state.position_verified = True
        self.state.motion = 'settling'
        self.state.settled_until = time.time() + self.config.settling_seconds
        self.state.last_completed_at = time.time()
        self.state.error = None
        self.event('position', '模拟位置已同步' if self.state.simulated else '收到可信位置同步反馈')

    def switch_source(self, kind, label, simulated=False):
        self.invalidate()
        self.frames.clear()
        self.source = dict(kind=kind, label=label, simulated=simulated, status='running', session_id=uid(), sequence=-1)
        self.last_analysis = self.analysis_meta = self.last_decision = None
        self.snapshots.clear()
        self.capture_after = False
        self.event('source', '画面源已切换：' + label)
        return self.source['session_id']

    def ingest(self, jpeg, session, sequence, captured_at, capture_version=-1):
        if session != self.source['session_id'] or sequence <= self.source['sequence']:
            raise ValueError('旧画面会话或重复序号')
        if self.source['status'] != 'running':
            raise ValueError('画面源未运行')
        now = time.time()
        eligible = self.state.connection == 'connected' and self.state.motion == 'idle' and now >= self.state.settled_until
        # -1 is reserved for backend local capture, never accepted by the HTTP API.
        capture_verified = eligible and (capture_version == -1 or capture_version == self.state.state_version)
        if capture_version is not None and not capture_verified:
            eligible = False
        meta = FrameMetadata(source_session_id=session, sequence=sequence, captured_at=captured_at, source=self.source['kind'],
                             actual_filter=self.state.actual_filter if capture_verified else None, capture_lens_verified=capture_verified,
                             state_version=self.state.state_version,
                             eligible=eligible, simulated=self.source['simulated'])
        frame = Frame(meta, jpeg)
        self.source['sequence'] = sequence
        self.frames.put(frame)
        if self.capture_after and eligible and capture_verified:
            if self.config.snapshot_count >= 2:
                self.snapshots['after'] = frame
            self.capture_after = False
        return meta

    def set_mode(self, action):
        self.invalidate()
        if action == 'pause':
            self.state.auto = False
        elif action == 'lock':
            self.state.locked = True
        elif action == 'unlock':
            self.state.locked = False
        elif action == 'auto':
            self.state.locked, self.state.auto = False, True
            self.intent = UserIntent()
        self.event('mode', {'pause': '自动分析已暂停', 'lock': '拍摄锁定已开启', 'unlock': '拍摄锁定已解除', 'auto': '已恢复自动与默认偏好'}[action])

    def set_recording(self, value, source):
        self.recording_updated_at = time.time()
        if value != self.state.recording or source != self.state.recording_source:
            self.invalidate()
            self.state.recording, self.state.recording_source = value, source
            self.event('recording', '录像状态更新：' + value + '（' + source + '）')

    def gate(self, automatic):
        s = self.state
        if s.connection != 'connected' or not s.position_verified:
            return '设备未同步实际位置'
        if s.pending or s.motion != 'idle':
            return '设备正在运动、稳定或异常'
        if s.locked:
            return '拍摄锁定生效，请先解锁'
        if automatic:
            if not s.auto:
                return '自动模式已暂停'
            if s.recording == 'recording' and not self.config.allow_auto_while_recording:
                return '录像中，已阻止自动切换'
            if s.recording == 'unknown' and not self.config.allow_auto_recording_unknown:
                return '录像状态未知，请确认未录像或使用手动选择'
        return None

    async def execute(self, decision: Decision, automatic=False):
        s = self.state
        if decision.target == Filter.KEEP:
            return '保持当前状态'
        if decision.target not in self.config.slots:
            raise ValueError('未配置该镜片或空位')
        if reason := self.gate(automatic):
            raise ValueError(reason)
        if decision.target == s.actual_filter:
            return '当前已是所选镜片'
        if automatic and time.time() - s.last_completed_at < max(self.config.min_hold_seconds, self.config.cooldown_seconds):
            raise ValueError('切换保持与冷却时间未结束')
        self.invalidate()
        command = FilterCommand(decision_id=decision.decision_id, frame_id=decision.frame_id, device_id=s.device_id,
                                connection_session_id=s.connection_session_id, target_filter=decision.target,
                                target_slot=self.config.slots[decision.target], expires_at=time.time() + self.config.command_timeout,
                                ttl_ms=int(self.config.command_timeout * 1000))
        s.pending, s.target_filter, s.motion, s.command_status = command, decision.target, 'switching', 'pending'
        self.snapshots.clear()
        frame = self.frames.latest
        if self.config.snapshot_count and frame and frame.meta.eligible and frame.meta.actual_filter == s.actual_filter and time.time() - frame.meta.received_at <= self.config.max_frame_age:
            self.snapshots['before'] = frame
        self.capture_after = False
        self.event('command', '模拟设备切换请求' if s.simulated else '已发送镜片切换请求', command_id=command.command_id,
                   decision_id=command.decision_id, frame_id=command.frame_id)
        try:
            await self.transport.send(dict(type='command', command=command.model_dump(mode='json')))
        except Exception:
            self.disconnect('指令发送失败，位置未知；不会自动重发')
            raise ValueError('指令发送失败，需重新同步位置')
        return '切换指令已提交，等待到位反馈'

    async def manual(self, target):
        decision = Decision(target=target, reason='用户手动选择', actionable=target != Filter.KEEP)
        result = await self.execute(decision)
        self.last_decision = decision
        self.set_mode('lock')
        return result

    async def feedback(self, feedback):
        s, cmd = self.state, self.state.pending
        if not cmd or feedback.connection_session_id != s.connection_session_id or feedback.command_id != cmd.command_id:
            return
        if time.time() > cmd.expires_at:
            await self.command_unknown('指令超时，忽略迟到反馈')
            return
        if feedback.status in ('accepted', 'moving'):
            if s.command_status != 'moving':
                s.command_status = feedback.status
            return
        if feedback.status == 'completed' and feedback.position_verified and feedback.actual_slot == cmd.target_slot:
            self.invalidate()
            s.actual_filter, s.actual_slot, s.position_verified = cmd.target_filter, cmd.target_slot, True
            s.pending, s.motion, s.command_status = None, 'settling', 'completed'
            s.last_completed_at = time.time()
            s.settled_until = time.time() + self.config.settling_seconds
            self.capture_after = True
            self.event('completed', '模拟执行到位（非真实硬件）' if s.simulated else '收到可信的到位反馈', command_id=cmd.command_id,
                       decision_id=cmd.decision_id, frame_id=cmd.frame_id,
                       metrics={'completion_ms': (time.time() - cmd.issued_at) * 1000})
        else:
            await self.command_unknown('未验证到位或执行失败，需要位置查询', failed=feedback.status == 'failed')

    async def command_unknown(self, reason, failed=False):
        cmd = self.state.pending
        self.state.pending = None
        self.state.command_status = 'failed' if failed else 'unknown'
        self.state.error = reason
        self.state.auto = False
        self.event('command_unknown', reason, command_id=cmd.command_id if cmd else None)
        await self.resync(reason + '；自动模式已暂停，不重发运动')

    async def submit_intent(self, text):
        intent = parse_intent(text)
        if intent.kind == 'ignored':
            return intent
        if intent.text == self.last_intent_text and time.time() - self.last_intent_at < 3:
            return intent.model_copy(update={'kind': 'ignored', 'scope': '重复输入已忽略'})
        if intent.kind == 'select':
            await self.manual(intent.target)
        elif intent.kind == 'lock':
            self.set_mode('lock')
        elif intent.kind == 'auto':
            self.set_mode('auto')
        else:
            self.invalidate()
        self.intent = intent
        self.last_intent_text, self.last_intent_at = intent.text, time.time()
        self.event('intent', '文本测试意图已更新：' + intent.kind)
        return intent

    async def analyze_once(self, frame):
        s = self.state
        if not frame or not frame.meta.eligible or self.gate(True):
            return
        version, session = s.state_version, self.source['session_id']
        if frame.meta.state_version != version or frame.meta.source_session_id != session or time.time() - frame.meta.received_at > self.config.max_frame_age:
            return
        s.analyzing = True
        self.model_status = 'analyzing'
        start = time.time()
        try:
            context = dict(actual_filter=frame.meta.actual_filter, supported_filters=list(self.config.slots),
                           capabilities={'supports_clear': self.config.supports_clear, 'demo_distance_verified': self.config.demo_distance_verified},
                           intent=self.intent.model_dump(), recent_state={'last_completed_at': s.last_completed_at, 'state_version': version})
            raw = await asyncio.wait_for(self.vision.analyze(frame, context), timeout=self.config.model_timeout)
            analysis = validate_analysis(raw, frame, self.config)
            self.model_status = 'ready'
            self.model_latency_ms = (time.time() - start) * 1000
            if version != s.state_version or session != self.source['session_id'] or (frame.meta.capture_lens_verified and frame.meta.actual_filter != s.actual_filter) or time.time() - frame.meta.received_at > self.config.max_frame_age or self.gate(True):
                self.engine.reset()
                self.event('stale_result', '已丢弃过期或状态变化前的分析', frame_id=frame.meta.frame_id)
                return
            self.last_analysis, self.analysis_meta = analysis, frame.meta
            decision = self.engine.evaluate(analysis, s, self.intent)
            if not frame.meta.capture_lens_verified:
                self.engine.reset()
                decision = Decision(frame_id=frame.meta.frame_id, reason='图片采集时镜片未经确认，仅展示分析，不自动切换。')
            self.last_decision = decision
            self.event('analysis', decision.reason, frame_id=frame.meta.frame_id, decision_id=decision.decision_id,
                       metrics={'model_ms': self.model_latency_ms, 'frame_age_ms': (time.time() - frame.meta.received_at) * 1000})
            if decision.actionable:
                await self.execute(decision, automatic=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.model_status = 'error'
            self.engine.reset()
            # Do not log provider exception bodies, which may contain request contents or keys.
            self.event('analysis_error', '分析失败或校验未通过，不执行运动（' + type(exc).__name__ + '）', frame_id=frame.meta.frame_id)
        finally:
            s.analyzing = False

    async def analysis_loop(self):
        while True:
            await asyncio.sleep(self.config.sample_seconds)
            await self.analyze_once(self.frames.take())

    async def watchdog(self):
        while True:
            await asyncio.sleep(0.1)
            now, s = time.time(), self.state
            if s.pending and now > s.pending.expires_at:
                await self.command_unknown('指令超时，实际位置未知')
            if s.motion == 'settling' and now >= s.settled_until:
                s.motion = 'idle'
                self.invalidate()
            if not s.simulated and s.connection != 'disconnected' and now - self.last_seen > self.config.heartbeat_timeout:
                self.disconnect('设备心跳超时')
            if self.query_id and now - self.query_started_at > self.config.command_timeout and not s.error:
                s.error = '位置同步超时：未验证到位，请检查装置后重新查询'
                s.motion = 'error'
                self.event('sync_timeout', s.error)
            if s.recording != 'unknown' and s.recording_source.startswith('相机桥接') and now - self.recording_updated_at > self.config.heartbeat_timeout:
                self.set_recording('unknown', '相机桥接录像报告已过期')
            for key, frame in list(self.snapshots.items()):
                if now - frame.meta.received_at > self.config.snapshot_ttl_seconds:
                    self.snapshots.pop(key, None)

    def snapshot(self):
        s = self.state
        s.phase = s.connection if s.connection != 'connected' else s.motion if s.motion != 'idle' else 'locked' if s.locked else 'analyzing' if s.analyzing else 'observing'
        return dict(device=s.model_dump(mode='json'), source=self.source.copy(), model={'provider': self.config.provider, 'model': self.config.model, 'simulated': self.config.provider == 'mock', 'status': self.model_status, 'scenario': self.vision.scenario if hasattr(self.vision, 'scenario') else self.config.model, 'latency_ms': self.model_latency_ms},
                    frame=self.frames.latest.meta.model_dump(mode='json') if self.frames.latest else None,
                    analysis=self.last_analysis.model_dump(mode='json') if self.last_analysis else None,
                    analysis_frame=self.analysis_meta.model_dump(mode='json') if self.analysis_meta else None,
                    decision=self.last_decision.model_dump(mode='json') if self.last_decision else None,
                    intent=self.intent.model_dump(mode='json'), events=self.store.recent(),
                    snapshots={k: f.meta.model_dump(mode='json') for k, f in self.snapshots.items()},
                    automatic_block=self.gate(True), server_time=time.time())
