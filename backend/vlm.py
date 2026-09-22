"""DashScope OpenAI-compatible vision. Returns SceneAnalysis fields only."""
import asyncio
import json
import re

import httpx

from .frames import Frame
from .models import FrameMetadata
from .vision import SYSTEM_RULES

FEATURE_KEYS = (
    'reflection_obscures_subject', 'glass_or_water', 'close_detail', 'portrait',
    'highlights', 'point_lights', 'soft_style',
)


def create_vision(config):
    if config.provider == 'mock':
        from .vision import MockVision
        return MockVision()
    if config.provider == 'dashscope':
        return DashScopeVision(config)
    raise ValueError('尚未实现该模型供应商，不会静默回退模拟。')


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes')
    return False


def _json_object(text):
    text = text.strip()
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end < start:
        raise ValueError('模型未返回 JSON')
    return json.loads(text[start:end + 1])


def normalize_scene(raw, frame_id):
    if isinstance(raw, str):
        raw = _json_object(raw)
    if not isinstance(raw, dict):
        raise ValueError('模型结果不是对象')
    features = raw.get('scene_features')
    if not isinstance(features, dict):
        features = {key: raw.get(key, False) for key in FEATURE_KEYS}
    features = {key: _as_bool(features.get(key, False)) for key in FEATURE_KEYS}
    features['distance_verified'] = False
    echoed = raw.get('frame_id') or frame_id
    reason = str(raw.get('reason') or '模型未给出理由')[:250]
    subject = str(raw.get('subject') or '未命名')[:100]
    return {
        'frame_id': echoed,
        'subject': subject,
        'scene_features': features,
        'recommended_filter': raw.get('recommended_filter') or 'KEEP',
        'reason': reason,
        'uncertainty': raw.get('uncertainty', 1),
    }


class DashScopeVision:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client

    async def analyze(self, frame, context):
        return await asyncio.to_thread(self.analyze_sync, frame, context)

    def analyze_sync(self, frame, context):
        frame_id = frame.meta.frame_id
        prompt = (
            SYSTEM_RULES
            + ' 布尔字段只能是 true 或 false。distance_verified 必须是 false。'
            + ' 玻璃或水面反光挡住主体才建议 CPL。小而分开的点状光源才建议 STAR，大块发光面不算。'
            + ' 有人脸且有高光才建议 BLACK_MIST。看不清就 KEEP，并把 uncertainty 调高。'
            + f' frame_id 必须原样返回：{frame_id}。'
            + ' 输出字段：frame_id, subject, scene_features, recommended_filter, reason, uncertainty。'
        )
        body = {
            'model': self.settings.model,
            'temperature': 0,
            'messages': [
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + _b64(frame.jpeg)}},
                    {'type': 'text', 'text': '结合 context 判断滤镜。context=' + json.dumps(context, ensure_ascii=False)},
                ]},
            ],
        }
        owns = self.client is None
        client = self.client or httpx.Client(timeout=self.settings.model_timeout)
        try:
            response = client.post(
                self.settings.base_url.rstrip('/') + '/chat/completions',
                json=body,
                headers={'Authorization': 'Bearer ' + self.settings.api_key},
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
        finally:
            if owns:
                client.close()
        return normalize_scene(content, frame_id)


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode()


def frame_from_jpeg(jpeg: bytes, frame_id: str) -> Frame:
    meta = FrameMetadata(
        frame_id=frame_id, source_session_id='batch', sequence=0, captured_at=0,
        source='ace_batch', actual_filter=None, capture_lens_verified=False,
        state_version=0, eligible=False, simulated=False,
    )
    return Frame(meta, jpeg)
