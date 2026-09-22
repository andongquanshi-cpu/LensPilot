"""Analyze the first frame of a received Ace batch. Does not move the lens."""
import asyncio
import json
import threading
from pathlib import Path

from .config import load_settings
from .decision import DecisionEngine
from .models import DeviceState, UserIntent
from .vision import validate_analysis
from .vlm import create_vision, frame_from_jpeg

_lock = threading.Lock()
_seen = set()


def analyze_received_batch(directory, settings=None, vision=None):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    request_id = manifest.get('requestId')
    if not isinstance(request_id, str) or not request_id:
        raise ValueError('批次缺少 requestId')
    result_path = directory / 'result.json'
    with _lock:
        if request_id in _seen or result_path.exists():
            return None
        _seen.add(request_id)
    settings = settings or load_settings()
    vision = vision or create_vision(settings)
    jpeg_path = directory / 'frame-01.jpg'
    try:
        frame = frame_from_jpeg(jpeg_path.read_bytes(), request_id)
        context = {'supported_filters': list(settings.slots), 'installed_filter': None}
        raw = vision.analyze_sync(frame, context) if hasattr(vision, 'analyze_sync') else asyncio.run(vision.analyze(frame, context))
        analysis = validate_analysis(raw, frame, settings)
        decision = DecisionEngine(settings).evaluate(analysis, DeviceState(), UserIntent())
        payload = {
            'requestId': request_id,
            'file': 'frame-01.jpg',
            'analysis': analysis.model_dump(mode='json'),
            'decision': {
                'target': decision.target,
                'reason': decision.reason,
                'actionable': False,
            },
            'motion': 'not_sent',
        }
    except Exception as exc:
        payload = {
            'requestId': request_id,
            'file': 'frame-01.jpg',
            'error': type(exc).__name__,
            'decision': {'target': 'KEEP', 'reason': '分析失败，不发送切镜指令。', 'actionable': False},
            'motion': 'not_sent',
        }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload
