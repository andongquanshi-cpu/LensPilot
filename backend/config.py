import json
import os
from pathlib import Path
from pydantic import Field, model_validator
from .models import StrictModel, Filter


class Settings(StrictModel):
    provider: str = 'mock'
    base_url: str = ''
    api_key: str = Field(default='', exclude=True)
    model: str = 'deterministic-demo'
    image_input: str = 'jpeg_bytes'
    model_timeout: float = Field(default=12, gt=0, le=120)
    transport: str = 'mock'
    control_token: str = Field(default='', exclude=True)
    device_token: str = Field(default='', exclude=True)
    allowed_origins: list[str] = ['http://127.0.0.1:8000', 'http://localhost:8000', 'http://127.0.0.1:5173', 'http://localhost:5173']
    slots: dict[Filter, int] = {Filter.CPL: 0, Filter.CLOSE_UP: 1, Filter.BLACK_MIST: 2, Filter.STAR: 3}
    supports_clear: bool = False
    sample_seconds: float = Field(default=2, ge=0.05, le=60)
    max_frame_age: float = Field(default=10, gt=0, le=120)
    image_size: int = Field(default=1280, ge=128, le=1920)
    jpeg_quality: int = Field(default=80, ge=30, le=95)
    upload_max_bytes: int = Field(default=8_000_000, ge=1024, le=20_000_000)
    consistent_count: int = Field(default=3, ge=1, le=20)
    cooldown_seconds: float = Field(default=8, ge=0, le=120)
    min_hold_seconds: float = Field(default=8, ge=0, le=120)
    settling_seconds: float = Field(default=2, ge=0, le=30)
    command_timeout: float = Field(default=8, gt=0, le=60)
    heartbeat_timeout: float = Field(default=15, ge=2, le=120)
    portrait_prefers_mist: bool = True
    demo_distance_verified: bool = False
    allow_auto_while_recording: bool = False
    allow_auto_recording_unknown: bool = False
    media_files: dict[str, str] = {}
    camera_indices: list[int] = [0]
    snapshot_count: int = Field(default=2, ge=0, le=2)
    snapshot_ttl_seconds: float = Field(default=600, ge=1, le=86400)
    event_limit: int = Field(default=1000, ge=20, le=10000)
    event_ttl_seconds: float = Field(default=604800, ge=60)
    database: str = 'data/events.sqlite3'

    @model_validator(mode='after')
    def validate_settings(self):
        if self.provider == 'dashscope':
            if not self.api_key or not self.base_url or not self.model:
                raise ValueError('dashscope 需要 OPTIC_API_KEY、OPTIC_BASE_URL 和 OPTIC_MODEL')
            if not self.base_url.startswith('https://') or not self.base_url.rstrip('/').endswith('/compatible-mode/v1'):
                raise ValueError('dashscope 的 base_url 必须是百炼 compatible-mode/v1 地址')
        elif self.provider != 'mock':
            raise ValueError('尚未实现该模型供应商，不会静默回退模拟。')
        if self.transport not in ('mock', 'bridge'):
            raise ValueError('transport 仅支持 mock 或 bridge')
        if Filter.KEEP in self.slots or len(set(self.slots.values())) != len(self.slots):
            raise ValueError('槽位必须唯一，KEEP 不能映射到槽位')
        if any(v < 0 for v in self.slots.values()):
            raise ValueError('槽位必须为非负整数')
        if (Filter.CLEAR in self.slots) != self.supports_clear:
            raise ValueError('CLEAR 槽位与 supports_clear 必须一致')
        if not self.slots:
            raise ValueError('至少配置一片镜片')
        return self


ROOT = Path(__file__).resolve().parents[1]


def load_settings():
    # Optional .env, process environment always wins. Secrets are never serialized.
    from dotenv import load_dotenv
    if (ROOT / '.env').exists():
        load_dotenv(ROOT / '.env', override=False)
    elif Path('.env').exists():
        load_dotenv(override=False)
    path = Path(os.getenv('OPTIC_CONFIG', 'config.json'))
    if not path.is_absolute() and (ROOT / path).exists():
        path = ROOT / path
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for key in ('provider', 'base_url', 'api_key', 'model', 'transport', 'control_token', 'device_token', 'database'):
        if f'OPTIC_{key.upper()}' in os.environ:
            data[key] = os.environ[f'OPTIC_{key.upper()}']
    return Settings(**data)
