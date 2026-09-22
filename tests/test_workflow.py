import asyncio
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.config import Settings
from backend.models import Filter, SceneAnalysis, Features, Decision, CommandFeedback
from backend.service import Controller
from backend.sources import demo_image
from backend.api import create_app
from backend.vision import SCENARIOS
from backend.intents import parse_intent


class Sink:
    simulated = False
    def __init__(self):
        self.sent = []
    async def send(self, data):
        self.sent.append(data)
    async def close(self):
        pass


@pytest.fixture
def c(tmp_path):
    config = Settings(database=str(tmp_path / 'events.sqlite3'), consistent_count=3,
                      cooldown_seconds=0, min_hold_seconds=0, settling_seconds=0)
    controller = Controller(config)
    controller.transport = Sink()
    controller.state.connection = 'connected'
    controller.state.connection_session_id = 'connection-A'
    controller.state.position_verified = True
    controller.state.actual_filter = Filter.CPL
    controller.state.actual_slot = 0
    controller.state.recording = 'stopped'
    controller.switch_source('upload', 'test')
    yield controller
    controller.store.close()


def frame(c, seq=0):
    c.ingest(demo_image(seq), c.source['session_id'], seq, time.time())
    return c.frames.latest


def scene(target, frame_id='f'):
    return SceneAnalysis(frame_id=frame_id, subject='测试', scene_features=Features(
        reflection_obscures_subject=True, glass_or_water=True, close_detail=True,
        highlights=True, point_lights=True, soft_style=True), recommended_filter=target,
        reason='测试候选', uncertainty=.2)


@pytest.mark.parametrize('target', [Filter.CPL, Filter.CLOSE_UP, Filter.BLACK_MIST, Filter.STAR])
def test_four_filter_paths(c, target):
    c.config.demo_distance_verified = True
    c.state.actual_filter = Filter.STAR if target != Filter.STAR else Filter.CPL
    decisions = [c.engine.evaluate(scene(target), c.state, c.intent) for _ in range(3)]
    assert [d.actionable for d in decisions] == [False, False, True]
    assert decisions[-1].target == target


def test_keep_never_moves(c):
    asyncio.run(c.execute(Decision(target=Filter.KEEP, reason='keep')))
    assert not c.transport.sent


def test_clear_requires_actual_slot(c):
    with pytest.raises(ValueError):
        asyncio.run(c.manual(Filter.CLEAR))
    with pytest.raises(ValueError):
        Settings(supports_clear=True)
    assert not c.transport.sent


def test_clear_when_configured(c):
    c.config.slots[Filter.CLEAR] = 4
    c.config.supports_clear = True
    asyncio.run(c.execute(Decision(target=Filter.CLEAR, reason='clear')))
    assert c.state.pending.target_slot == 4


def test_unstable_candidates_reset(c):
    for target in [Filter.STAR, Filter.BLACK_MIST] * 8:
        assert not c.engine.evaluate(scene(target), c.state, c.intent).actionable


def test_close_up_model_claim_is_not_distance_sensor(c):
    a = scene(Filter.CLOSE_UP)
    a.scene_features.distance_verified = True
    assert c.engine.evaluate(a, c.state, c.intent).target == Filter.KEEP


def test_explicit_preferences(c):
    c.intent.preference = 'preserve_reflections'
    assert c.engine.evaluate(scene(Filter.CPL), c.state, c.intent).target == Filter.KEEP
    c.intent.preference = 'sharp'
    assert c.engine.evaluate(scene(Filter.BLACK_MIST), c.state, c.intent).target == Filter.KEEP


def test_accepted_not_completed_and_feedback_idempotent(c):
    async def run():
        await c.manual(Filter.STAR)
        cmd = c.state.pending
        await c.feedback(CommandFeedback(command_id=cmd.command_id, connection_session_id='connection-A', status='accepted'))
        assert c.state.actual_filter == Filter.CPL
        assert c.state.pending
        completed = CommandFeedback(command_id=cmd.command_id, connection_session_id='connection-A', status='completed', actual_slot=3, position_verified=True)
        await c.feedback(completed)
        assert c.state.actual_filter == Filter.STAR
        version = c.state.state_version
        await c.feedback(completed)
        assert c.state.state_version == version
    asyncio.run(run())


def test_unverified_completed_stays_unknown(c):
    async def run():
        await c.manual(Filter.STAR)
        cmd = c.state.pending
        await c.feedback(CommandFeedback(command_id=cmd.command_id, connection_session_id='connection-A', status='completed', actual_slot=3))
        assert c.state.actual_filter is None
        assert c.state.command_status == 'unknown'
        assert not c.state.auto
    asyncio.run(run())


def test_timeout_queries_position_no_retry(c):
    async def run():
        await c.manual(Filter.STAR)
        cmd = c.state.pending
        cmd.expires_at = time.time() - 1
        await c.feedback(CommandFeedback(command_id=cmd.command_id, connection_session_id='connection-A', status='completed', actual_slot=3, position_verified=True))
        assert [m['type'] for m in c.transport.sent] == ['command', 'query_position']
        assert c.state.actual_filter is None
        assert not c.state.auto
    asyncio.run(run())


def test_reconnect_rejects_old_completion(c):
    async def run():
        await c.manual(Filter.STAR)
        old = c.state.pending
        c.disconnect()
        await c.connect(Sink())
        await c.feedback(CommandFeedback(command_id=old.command_id, connection_session_id=old.connection_session_id, status='completed', actual_slot=3, position_verified=True))
        assert c.state.actual_filter is None
        await c.position(c.state.connection_session_id, c.query_id, 2, True)
        assert c.state.actual_filter == Filter.BLACK_MIST
    asyncio.run(run())


@pytest.mark.parametrize('mutation',['lock','source','recording'])
def test_inflight_results_invalidated(c, mutation):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Slow:
            async def analyze(self, f, context):
                entered.set()
                await release.wait()
                return scene(Filter.STAR, f.meta.frame_id).model_dump()
        c.config.consistent_count = 1
        c.vision = Slow()
        task = asyncio.create_task(c.analyze_once(frame(c)))
        await entered.wait()
        if mutation == 'lock': c.set_mode('lock')
        elif mutation == 'source': c.switch_source('upload', 'new')
        else: c.set_recording('recording', 'test')
        release.set()
        await task
        assert not c.transport.sent
    asyncio.run(run())


@pytest.mark.parametrize('bad',['enum','format','frame','timeout'])
def test_invalid_model_output_never_moves(c, bad):
    class BadModel:
        async def analyze(self, f, context):
            result = scene(Filter.STAR, f.meta.frame_id).model_dump()
            if bad == 'timeout': await asyncio.sleep(1)
            if bad == 'enum': result['recommended_filter'] = 'ND'
            if bad == 'format': return {'hello':'world'}
            if bad == 'frame': result['frame_id'] = 'wrong'
            return result
    c.vision = BadModel()
    c.config.model_timeout = .01
    c.config.consistent_count = 1
    asyncio.run(c.analyze_once(frame(c)))
    assert not c.transport.sent
    assert c.store.recent()[0]['type'] == 'analysis_error'


def test_only_latest_pending_and_one_inflight(c):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        seen = []
        class Slow:
            async def analyze(self, f, context):
                seen.append(f.meta.sequence)
                entered.set()
                await release.wait()
                return scene(Filter.KEEP, f.meta.frame_id).model_dump()
        c.vision = Slow()
        c.config.sample_seconds = .05
        frame(c, 0)
        task = asyncio.create_task(c.analysis_loop())
        await entered.wait()
        for i in range(1,10): frame(c, i)
        assert seen == [0]
        assert c.frames.pending.meta.sequence == 9
        release.set()
        await asyncio.sleep(.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert seen == [0,9]
    asyncio.run(run())


def test_old_upload_session_and_sequence(c):
    old = c.source['session_id']
    frame(c)
    with pytest.raises(ValueError): frame(c)
    c.switch_source('upload','new')
    with pytest.raises(ValueError): c.ingest(demo_image(1), old, 1, time.time())


def test_motion_frames_excluded_and_settling(c):
    c.state.motion = 'switching'
    assert not frame(c).meta.eligible
    assert c.frames.pending is None
    c.state.motion = 'settling'
    assert not frame(c,1).meta.eligible


def test_recording_unknown_blocks_auto(c):
    c.state.recording = 'unknown'
    assert c.gate(True)
    assert c.gate(False) is None


def test_restart_does_not_restore_last_lens(tmp_path):
    config = Settings(database=str(tmp_path/'events.sqlite3'))
    c = Controller(config)
    c.state.actual_filter = Filter.STAR
    c.event('test','old position')
    c.store.close()
    other = Controller(config)
    assert other.state.actual_filter is None
    assert not other.state.position_verified
    other.store.close()


@pytest.mark.parametrize('text',['不要切到黑柔','也许用星光吧','不要恢复自动','照片上写着切到黑柔'])
def test_ambiguous_or_negative_text_ignored(text):
    assert parse_intent(text).kind == 'ignored'


def test_api_simulated_end_to_end_and_auth(tmp_path):
    config = Settings(database=str(tmp_path/'e.sqlite3'),control_token='test-control',device_token='test-device',
                      sample_seconds=.05, consistent_count=1, settling_seconds=.05, cooldown_seconds=0, min_hold_seconds=0)
    with TestClient(create_app(config)) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/state').status_code == 401
        client.headers['Authorization'] = 'Bearer test-control'
        public = client.get('/api/config').json()
        assert 'api_key' not in public and 'control_token' not in public and 'device_token' not in public
        assert client.post('/api/source',json={'kind':'video','media_id':'../../etc/passwd'}).status_code == 409
        client.post('/api/recording',json={'value':'stopped'})
        client.post('/api/demo/scenario',json={'scenario':'lights'})
        client.post('/api/source',json={'kind':'demo'})
        deadline = time.time()+5
        while time.time()<deadline:
            state=client.get('/api/state').json()
            if state['device']['actual_filter']=='STAR' and state['snapshots'].get('after'):break
            time.sleep(.05)
        assert state['device']['actual_filter']=='STAR'
        assert state['device']['simulated'] and state['model']['simulated'] and state['source']['simulated']
        assert state['snapshots']['before']['actual_filter']=='CPL'
        assert state['snapshots']['after']['actual_filter']=='STAR'
        assert client.get('/api/preview').headers['content-type']=='image/jpeg'
        with client.websocket_connect('/ws/events') as ws:
            ws.send_json({'type':'auth','token':'test-control'})
            assert ws.receive_json()['device']['actual_filter']=='STAR'


def test_upload_validation(tmp_path):
    config=Settings(database=str(tmp_path/'e.sqlite3'),control_token='control',device_token='device',upload_max_bytes=1024)
    with TestClient(create_app(config)) as client:
        client.headers['Authorization']='Bearer control'
        session=client.post('/api/source',json={'kind':'upload'}).json()['source_session_id']
        headers={'X-Source-Session':session,'X-Sequence':'0','X-Captured-At':'999999999999'}
        assert client.post('/api/frames',content=b'x'*1025,headers=headers).status_code==413
        assert client.post('/api/frames',content=b'not an image',headers=headers).status_code==409


def test_upload_unknown_capture_lens_only_analyzes(c):
    async def run():
        c.config.consistent_count=1
        c.vision.scenario='lights'
        c.ingest(demo_image(0),c.source['session_id'],0,time.time(),None)
        assert c.frames.latest.meta.actual_filter is None
        await c.analyze_once(c.frames.take())
        assert c.last_analysis
        assert not c.transport.sent
    asyncio.run(run())


def test_capture_version_rejects_in_transit_old_lens(c):
    old_version=c.state.state_version
    c.invalidate()
    c.ingest(demo_image(0),c.source['session_id'],0,time.time(),old_version)
    assert not c.frames.latest.meta.eligible
    assert c.frames.pending is None


def test_style_overrides_default_recommendation(c):
    c.intent.preference='star'
    assert c.engine.evaluate(scene(Filter.CPL),c.state,c.intent).target==Filter.STAR


def test_minimum_hold_and_cooldown(c):
    c.config.cooldown_seconds=8
    c.state.last_completed_at=time.time()
    for _ in range(5):assert not c.engine.evaluate(scene(Filter.STAR),c.state,c.intent).actionable


def test_bridge_websocket_sync_and_feedback(tmp_path):
    cfg=Settings(database=str(tmp_path/'bridge.sqlite3'),control_token='control',device_token='device',transport='bridge',settling_seconds=0)
    with TestClient(create_app(cfg)) as client:
        client.headers['Authorization']='Bearer control'
        with client.websocket_connect('/ws/device') as ws:
            ws.send_json({'type':'auth','token':'device'})
            query=ws.receive_json()
            assert query['type']=='query_position'
            session=query['connection_session_id']
            ws.send_json({'type':'position','connection_session_id':session,'query_id':query['query_id'],'actual_slot':0,'position_verified':True})
            deadline=time.time()+2
            while time.time()<deadline:
                state=client.get('/api/state').json()['device']
                if state['motion']=='idle' and state['position_verified']:break
                time.sleep(.02)
            assert client.post('/api/select',json={'target':'STAR'}).status_code==200
            cmd=ws.receive_json()['command']
            ws.send_json({'type':'feedback','connection_session_id':session,'feedback':{'command_id':cmd['command_id'],'connection_session_id':session,'status':'accepted'}})
            assert client.get('/api/state').json()['device']['actual_filter']=='CPL'
            ws.send_json({'type':'feedback','connection_session_id':session,'feedback':{'command_id':cmd['command_id'],'connection_session_id':session,'status':'completed','actual_slot':3,'position_verified':True}})
            deadline=time.time()+2
            while time.time()<deadline:
                state=client.get('/api/state').json()['device']
                if state['actual_filter']=='STAR':break
                time.sleep(.02)
            assert state['actual_filter']=='STAR'
            assert not state['simulated'] # This is a contract-test peer, NOT validated hardware.


def test_video_file_ends_and_source_pause(tmp_path):
    cv2=pytest.importorskip('cv2')
    import numpy as np
    from backend.sources import SourceManager
    file=tmp_path/'sample.avi'
    writer=cv2.VideoWriter(str(file),cv2.VideoWriter_fourcc(*'MJPG'),10,(160,120))
    assert writer.isOpened()
    for i in range(6):writer.write(np.full((120,160,3),i*30,dtype=np.uint8))
    writer.release()
    async def run():
        c=Controller(Settings(database=str(tmp_path/'video.sqlite3'),media_files={'sample':str(file)}))
        source=SourceManager(c)
        try:
            await source.start('video','sample')
            await asyncio.wait_for(source.task,3)
            assert c.source['status']=='ended'
            assert c.frames.latest.meta.sequence==5
        finally:
            await source.stop()
            c.store.close()
    asyncio.run(run())
