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
    uncertainty = raw.get('uncertainty', 1)
    if isinstance(uncertainty, str):
        try:
            uncertainty = float(uncertainty.strip())
        except ValueError:
            pass  # Invalid values remain subject to strict schema validation.
    return {
        'frame_id': echoed,
        'subject': subject,
        'scene_features': features,
        'recommended_filter': raw.get('recommended_filter') or 'KEEP',
        'reason': reason,
        'uncertainty': uncertainty,
    }


def features_match(recommended, features):
    """The suggested filter must be backed by the checked scene facts."""
    if recommended == 'CPL':
        return features['glass_or_water'] and features['reflection_obscures_subject']
    if recommended == 'STAR':
        return features['point_lights']
    if recommended == 'BLACK_MIST':
        return features['highlights'] and (features['portrait'] or features['soft_style'])
    if recommended == 'CLOSE_UP':
        return features['close_detail']
    return recommended in ('KEEP', 'CLEAR')


def settle_mismatch(scene):
    scene['recommended_filter'] = 'KEEP'
    scene['reason'] = '建议镜片和场景特征不一致，保持当前镜片。'
    try:
        scene['uncertainty'] = max(float(scene.get('uncertainty') or 0), 0.7)
    except (TypeError, ValueError):
        scene['uncertainty'] = 0.7
    return scene


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
            + ' 任务是为摄影爱好者推荐值得尝试的实体滤镜表达，不是只在照片有缺陷时才修复。画面已经清晰、曝光正常，并不是 KEEP 的理由。'
            + ' 先独立填写可见场景特征，再选与特征匹配的一片镜；不要为了 KEEP 把实际看见的特征全部填 false。'
            + ' point_lights：画面中可分辨的小亮点或局部强光，如路灯、车灯、装饰灯珠、串灯、嵌入式小灯。'
            + ' 不要求光源在远处、独立安装或已经产生星芒；透过纱网仍可分辨的小亮点也可成立。只有大片均匀发光面或无法分辨的弥散光团不算。存在明确点状亮光可推荐 STAR 来创造星芒。'
            + ' close_detail：取景明显围绕小物件、花朵、饰品、纹理等局部细节，期望放大细节时可推荐 CLOSE_UP。'
            + ' 普通房间全景或仅有一张桌子不算细节特写。推荐近摄不等于确认距离，距离与焦点由拍摄者实测调整，不因无法从图像测距而否决候选。'
            + ' highlights：可见明亮高光或灯光。portrait：人像是画面主体。soft_style：暖灯、逆光或灯光氛围适合尝试柔和晕光，不要求用户先说要柔光。'
            + ' 有高光且有人像或柔和灯光氛围，可推荐 BLACK_MIST；无需限制为正脸。黑柔不能修复过曝。'
            + ' 玻璃或水面的反光遮挡主体、影响观察细节时可推荐 CPL；不把普通发光灯当反光。'
            + ' 多种条件成立时优先照顾主体：小物细节可近摄，人像配高光可黑柔，灯光为主可星光。理由写明可见依据和预期表达。'
            + ' 确实没有相关特征，或画面看不清、依据不可靠时才 KEEP。不要强制每张图都换镜；不确定时如实提高 uncertainty。'
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
            content = self._complete(client, body['messages'])
            scene = normalize_scene(content, frame_id)
            if features_match(scene['recommended_filter'], scene['scene_features']):
                return scene
            body['messages'].append({'role': 'assistant', 'content': content})
            body['messages'].append({'role': 'user', 'content': [
                {'type': 'text', 'text': '建议镜片和 scene_features 对不上。请重填同一份 JSON：建议 CPL 时玻璃和反光遮挡都必须为 true；建议 STAR 时点状亮光必须为 true；建议 BLACK_MIST 时必须有高光，并且有人脸或柔和风格；建议 CLOSE_UP 时近景细节必须为 true。做不到就改 recommended_filter 为 KEEP。frame_id 仍是 ' + frame_id + '。'},
            ]})
            scene = normalize_scene(self._complete(client, body['messages']), frame_id)
        finally:
            if owns:
                client.close()
        if features_match(scene['recommended_filter'], scene['scene_features']):
            return scene
        return settle_mismatch(scene)

    def _complete(self, client, messages):
        response = client.post(
            self.settings.base_url.rstrip('/') + '/chat/completions',
            json={'model': self.settings.model, 'temperature': 0, 'messages': messages},
            headers={'Authorization': 'Bearer ' + self.settings.api_key},
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']


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
