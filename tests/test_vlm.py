import json
from pathlib import Path

import pytest

from backend.batch_job import analyze_received_batch
from backend.config import Settings
from backend.frames import Frame
from backend.models import FrameMetadata
from backend.vision import validate_analysis
from backend.vlm import DashScopeVision, normalize_scene


def settings(tmp_path):
    return Settings(
        provider='dashscope', api_key='test-key', model='qwen3-vl-plus',
        base_url='https://example.invalid/compatible-mode/v1',
        database=str(tmp_path / 'events.sqlite3'),
    )


def frame():
    meta = FrameMetadata(
        frame_id='frame-1', source_session_id='s', sequence=0, captured_at=0,
        source='test', actual_filter=None, state_version=0, eligible=False,
    )
    return Frame(meta, b'jpeg')


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        Settings(provider='openai')


def test_dashscope_requires_key():
    with pytest.raises(ValueError):
        Settings(provider='dashscope', base_url='https://example.invalid/compatible-mode/v1', model='qwen3-vl-plus')


def test_flat_model_json_becomes_scene_analysis():
    raw = normalize_scene(
        {'subject': '纱帘', 'glass_or_water': 'neither', 'point_lights': True, 'recommended_filter': 'STAR', 'reason': '点状亮光', 'uncertainty': 0.1},
        'frame-1',
    )
    analysis = validate_analysis(raw, frame(), Settings())
    assert analysis.recommended_filter == 'STAR'
    assert analysis.scene_features.point_lights is True
    assert analysis.scene_features.glass_or_water is False
    assert analysis.scene_features.distance_verified is False


class Client:
    def __init__(self, content):
        self.content = content

    def post(self, url, json, headers):
        assert url.endswith('/chat/completions')
        assert headers['Authorization'] == 'Bearer test-key'
        self.body = json
        return self

    def raise_for_status(self):
        return None

    def json(self):
        return {'choices': [{'message': {'content': self.content}}]}


def test_dashscope_rejects_wrong_frame_id(tmp_path):
    vision = DashScopeVision(settings(tmp_path), client=Client(json.dumps({
        'frame_id': 'other', 'subject': '灯', 'scene_features': {'point_lights': True},
        'recommended_filter': 'STAR', 'reason': '点状亮光', 'uncertainty': 0.2,
    })))
    with pytest.raises(ValueError):
        validate_analysis(vision.analyze_sync(frame(), {}), frame(), settings(tmp_path))


def _batch(tmp_path, request_id='req-1'):
    directory = tmp_path / 'batch'
    directory.mkdir()
    (directory / 'manifest.json').write_text(json.dumps({'requestId': request_id, 'frames': []}), encoding='utf-8')
    (directory / 'frame-01.jpg').write_bytes(b'jpeg')
    return directory


class StarVision:
    calls = 0

    def analyze_sync(self, frame, context):
        StarVision.calls += 1
        return {
            'frame_id': frame.meta.frame_id, 'subject': '纱帘',
            'scene_features': {'point_lights': True}, 'recommended_filter': 'STAR',
            'reason': '点状亮光', 'uncertainty': 0.1,
        }


def test_batch_writes_suggestion_without_motion(tmp_path):
    StarVision.calls = 0
    directory = _batch(tmp_path)
    payload = analyze_received_batch(directory, settings(tmp_path), StarVision())
    assert payload['decision']['target'] == 'STAR'
    assert payload['decision']['actionable'] is False
    assert payload['motion'] == 'not_sent'
    assert analyze_received_batch(directory, settings(tmp_path), StarVision()) is None
    assert StarVision.calls == 1


class CloseVision:
    def analyze_sync(self, frame, context):
        return {
            'frame_id': frame.meta.frame_id, 'subject': '线缆',
            'scene_features': {'close_detail': True}, 'recommended_filter': 'CLOSE_UP',
            'reason': '离镜头很近', 'uncertainty': 0.3,
        }


def test_unverified_close_up_stays_keep(tmp_path):
    directory = _batch(tmp_path, 'req-close')
    payload = analyze_received_batch(directory, settings(tmp_path), CloseVision())
    assert payload['analysis']['recommended_filter'] == 'CLOSE_UP'
    assert payload['decision']['target'] == 'KEEP'
