from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from uuid import uuid4
import time


def uid() -> str:
    return uuid4().hex


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Filter(StrEnum):
    CPL = 'CPL'
    CLOSE_UP = 'CLOSE_UP'
    BLACK_MIST = 'BLACK_MIST'
    STAR = 'STAR'
    KEEP = 'KEEP'
    CLEAR = 'CLEAR'


class FrameMetadata(StrictModel):
    frame_id: str = Field(default_factory=uid)
    source_session_id: str
    sequence: int = Field(ge=0)
    captured_at: float
    received_at: float = Field(default_factory=time.time)
    source: str
    actual_filter: Filter | None
    capture_lens_verified: bool = False
    state_version: int
    eligible: bool
    simulated: bool = False


class Features(StrictModel):
    reflection_obscures_subject: bool = False
    glass_or_water: bool = False
    close_detail: bool = False
    distance_verified: bool = False
    portrait: bool = False
    highlights: bool = False
    point_lights: bool = False
    soft_style: bool = False


class SceneAnalysis(StrictModel):
    frame_id: str
    subject: str = Field(max_length=100)
    scene_features: Features
    recommended_filter: Filter
    reason: str = Field(min_length=1, max_length=250)
    uncertainty: float = Field(ge=0, le=1)


class Decision(StrictModel):
    decision_id: str = Field(default_factory=uid)
    frame_id: str | None = None
    target: Filter = Filter.KEEP
    reason: str
    actionable: bool = False
    created_at: float = Field(default_factory=time.time)


class FilterCommand(StrictModel):
    command_id: str = Field(default_factory=uid)
    decision_id: str
    frame_id: str | None = None
    device_id: str
    connection_session_id: str
    action: Literal['select_filter'] = 'select_filter'
    target_filter: Filter
    target_slot: int
    issued_at: float = Field(default_factory=time.time)
    expires_at: float
    ttl_ms: int


class CommandFeedback(StrictModel):
    command_id: str
    connection_session_id: str
    status: Literal['accepted', 'moving', 'completed', 'failed']
    actual_slot: int | None = None
    position_verified: bool = False
    error_code: str | None = Field(default=None, max_length=100)


class UserIntent(StrictModel):
    intent_id: str = Field(default_factory=uid)
    text: str = Field(default='', max_length=160)
    kind: Literal['default', 'style', 'lock', 'auto', 'select', 'ignored'] = 'default'
    preference: Literal['default', 'star', 'soft', 'detail', 'preserve_reflections', 'sharp'] = 'default'
    target: Filter | None = None
    scope: str = '持续到更新偏好或恢复默认'
    source: Literal['text_test'] = 'text_test'


class DeviceState(StrictModel):
    device_id: str = 'lens-01'
    connection: Literal['disconnected', 'synchronizing', 'connected'] = 'disconnected'
    motion: Literal['idle', 'switching', 'settling', 'error'] = 'idle'
    phase: str = 'disconnected'
    connection_session_id: str | None = None
    actual_filter: Filter | None = None
    actual_slot: int | None = None
    target_filter: Filter | None = None
    position_verified: bool = False
    auto: bool = True
    locked: bool = False
    analyzing: bool = False
    recording: Literal['unknown', 'recording', 'stopped'] = 'unknown'
    recording_source: str = 'unknown'
    state_version: int = 0
    command_status: str = 'none'
    pending: FilterCommand | None = None
    last_completed_at: float = 0
    settled_until: float = 0
    simulated: bool = True
    error: str | None = None


class SystemEvent(StrictModel):
    event_id: str = Field(default_factory=uid)
    timestamp: float = Field(default_factory=time.time)
    type: str
    message: str
    frame_id: str | None = None
    decision_id: str | None = None
    command_id: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
