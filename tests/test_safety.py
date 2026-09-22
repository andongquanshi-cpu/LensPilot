import asyncio
import time
import pytest
from backend.config import Settings
from backend.models import Filter, Decision
from backend.service import Controller
from backend.frames import normalize_image
from backend.sources import demo_image
from backend.vision import validate_analysis


def test_model_boolean_strings_rejected():
    from backend.frames import Frame
    from backend.models import FrameMetadata
    f=Frame(FrameMetadata(source_session_id='s',sequence=0,captured_at=time.time(),source='test',actual_filter=None,state_version=0,eligible=True),b'')
    with pytest.raises(ValueError):
        validate_analysis({'frame_id':f.meta.frame_id,'subject':'test','scene_features':{'point_lights':'true'},'recommended_filter':'STAR','reason':'test','uncertainty':.1},f,Settings())


def test_wrong_image_format_rejected():
    from PIL import Image
    from io import BytesIO
    b=BytesIO()
    Image.new('RGB',(20,20)).save(b,format='BMP')
    with pytest.raises(ValueError):normalize_image(b.getvalue(),Settings())


def test_device_heartbeat_disconnect_and_recording_expiry(tmp_path):
    async def run():
        c=Controller(Settings(database=str(tmp_path/'s.sqlite3'),heartbeat_timeout=2))
        c.state.simulated=False
        c.state.connection='connected'
        c.state.position_verified=True
        c.state.actual_filter=Filter.STAR
        c.last_seen=time.time()-3
        task=asyncio.create_task(c.watchdog())
        try:
            await asyncio.sleep(.15)
            assert c.state.connection=='disconnected'
            assert c.state.actual_filter is None
            c.state.connection='connected'
            c.last_seen=time.time()
            c.set_recording('stopped','相机桥接报告')
            c.recording_updated_at=time.time()-3
            await asyncio.sleep(.15)
            assert c.state.recording=='unknown'
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            c.store.close()
    asyncio.run(run())


def test_parallel_manual_commands_never_queue_two_moves(tmp_path):
    class DelayedTransport:
        simulated=True
        def __init__(self):self.sent=[]
        async def send(self,data):
            self.sent.append(data)
            await asyncio.sleep(.05)
    async def run():
        c=Controller(Settings(database=str(tmp_path/'s.sqlite3')))
        c.state.connection='connected'
        c.state.connection_session_id='session'
        c.state.position_verified=True
        c.state.actual_filter=Filter.CPL
        c.transport=DelayedTransport()
        try:
            results=await asyncio.gather(c.manual(Filter.STAR),c.manual(Filter.BLACK_MIST),return_exceptions=True)
            assert len(c.transport.sent)==1
            assert any(isinstance(r,ValueError) for r in results)
        finally:c.store.close()
    asyncio.run(run())
