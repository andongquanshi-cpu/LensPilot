import json
import os
from datetime import datetime

from fastapi.testclient import TestClient

from backend.show import ShowFlow, frame_file, show_state
from backend.batch_job import analyze_received_batch
from backend.config import Settings
from backend.api import create_app


def batch(root, name, received, *, photo=False, taken=None, round_id=None):
    directory = root / name
    directory.mkdir()
    metadata = dict(requestId=name, frames=[{'file': 'frame-01.jpg'}])
    if photo:
        metadata.update(source='CAMERA_PHOTO', contentKind='CAMERA_ORIGINAL_JPEG',
                        cameraPath='/DCIM/Camera01/IMG_' + datetime.fromtimestamp(taken).strftime('%Y%m%d_%H%M%S') + '_001.jpg')
    if round_id is not None:
        metadata['roundId'] = round_id
    manifest = directory / 'manifest.json'
    manifest.write_text(json.dumps(metadata), encoding='utf-8')
    os.utime(manifest, (received, received))
    (directory / 'frame-01.jpg').write_bytes(name.encode())
    if not photo:
        (directory / 'result.json').write_text(json.dumps({'decision': {'target': 'STAR', 'reason': '点光源'}}))
    return directory


def test_timed_round_waits_for_new_camera_photo_and_pins_analysis(tmp_path):
    now = [1_790_000_000.0]
    batch(tmp_path, 'preview', now[0])
    batch(tmp_path, 'old-photo', now[0], photo=True, taken=now[0] - 20)
    flow = ShowFlow([tmp_path], clock=lambda: now[0])
    assert flow.state()['requestId'] == 'preview'
    flow.arm('preview', 3)
    now[0] += 2
    assert flow.state()['stage'] == 'ready'
    # A later preview does not end or replace the active round.
    batch(tmp_path, 'preview-2', now[0])
    now[0] += 2
    assert flow.state()['stage'] == 'capture'
    batch(tmp_path, 'late-old-photo', now[0], photo=True, taken=now[0] - 30)
    batch(tmp_path, 'wrong-round', now[0], photo=True, taken=now[0], round_id='other')
    assert flow.state()['stage'] == 'capture'
    batch(tmp_path, 'new-photo', now[0], photo=True, taken=now[0])
    state = flow.state()
    assert (state['stage'], state['requestId'], state['photoRequestId']) == ('complete', 'preview', 'new-photo')
    assert frame_file([tmp_path], 'preview').read_bytes() == b'preview'
    assert frame_file([tmp_path], 'new-photo').read_bytes() == b'new-photo'
    now[0] += 2
    batch(tmp_path, 'another-photo', now[0], photo=True, taken=now[0])
    assert flow.state()['photoRequestId'] == 'new-photo'
    assert flow.reset()['stage'] == 'waiting'
    now[0] += 1
    batch(tmp_path, 'next-preview', now[0])
    assert flow.state()['requestId'] == 'next-preview'


def test_early_capture_duplicate_arm_and_untyped_upload_do_not_complete(tmp_path):
    now = [1_790_000_000.0]
    batch(tmp_path, 'preview', now[0])
    flow = ShowFlow([tmp_path], clock=lambda: now[0])
    flow.arm('preview', 3)
    now[0] += 1
    batch(tmp_path, 'too-early', now[0], photo=True, taken=now[0])
    flow.arm('preview', 10)
    now[0] += 3
    batch(tmp_path, 'web-upload', now[0])
    assert flow.state()['stage'] == 'capture'
    assert flow.delay == 3


def test_camera_photo_never_calls_model(tmp_path):
    directory = batch(tmp_path, 'photo', 1_790_000_000, photo=True, taken=1_790_000_000)
    class UnexpectedModel:
        def analyze_sync(self, *args):
            raise AssertionError('Photo must not be analyzed')
    assert analyze_received_batch(directory, vision=UnexpectedModel()) is None
    assert not (directory / 'result.json').exists()
    assert show_state([tmp_path])['stage'] == 'waiting'


def test_flow_control_api_and_origin_guard(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.api.batch_roots', lambda repo: [tmp_path])
    batch(tmp_path, 'preview', 1_790_000_000)
    config = Settings(database=str(tmp_path / 'test.sqlite3'), control_token='control', device_token='device')
    with TestClient(create_app(config)) as client:
        assert client.get('/api/show').json()['stage'] == 'ready'
        assert client.post('/api/show/arm', json={'requestId': 'wrong'}).status_code == 409
        assert client.post('/api/show/arm', json={'requestId': 'preview', 'delaySeconds': 0}).status_code == 422
        assert client.post('/api/show/reset', headers={'Origin': 'https://outside.example'}).status_code == 403
        assert client.post('/api/show/arm', json={'requestId': 'preview'}).status_code == 200
        assert client.post('/api/show/reset').json()['stage'] == 'waiting'
