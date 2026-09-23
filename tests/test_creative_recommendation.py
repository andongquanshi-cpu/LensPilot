import pytest
from backend.config import Settings
from backend.decision import DecisionEngine
from backend.models import SceneAnalysis, Features, Filter, DeviceState, UserIntent


@pytest.mark.parametrize('features,expected', [
    ({'point_lights': True}, 'STAR'),
    ({'portrait': True, 'highlights': True}, 'BLACK_MIST'),
    ({'soft_style': True, 'highlights': True}, 'BLACK_MIST'),
    ({'close_detail': True}, 'CLOSE_UP'),
    ({'glass_or_water': True, 'reflection_obscures_subject': True}, 'CPL'),
    ({}, 'KEEP'),
    ({'highlights': True}, 'KEEP'),
    ({'glass_or_water': True}, 'KEEP'),
])
def test_creative_candidate_requires_observed_features(features, expected):
    analysis = SceneAnalysis(frame_id='x', subject='scene', scene_features=Features(**features), recommended_filter=Filter.KEEP, reason='画面已经清晰', uncertainty=.2)
    decision = DecisionEngine(Settings()).evaluate(analysis, DeviceState(), UserIntent(), recommendation_only=True)
    assert decision.target == expected
    assert not decision.actionable


def test_uncertain_and_sharp_preference_are_not_forced_to_change():
    analysis = SceneAnalysis(frame_id='x', subject='lights', scene_features=Features(point_lights=True), recommended_filter=Filter.KEEP, reason='test', uncertainty=.9)
    engine = DecisionEngine(Settings())
    assert engine.evaluate(analysis, DeviceState(), UserIntent(), recommendation_only=True).target == 'KEEP'
    analysis.uncertainty = .2
    assert engine.evaluate(analysis, DeviceState(), UserIntent(preference='sharp'), recommendation_only=True).target == 'KEEP'


def test_distance_gate_remains_for_physical_actuation():
    analysis = SceneAnalysis(frame_id='x', subject='detail', scene_features=Features(close_detail=True), recommended_filter=Filter.CLOSE_UP, reason='细节', uncertainty=.2)
    engine = DecisionEngine(Settings())
    assert engine.evaluate(analysis, DeviceState(), UserIntent()).target == 'KEEP'
    recommendation = engine.evaluate(analysis, DeviceState(), UserIntent(), recommendation_only=True)
    assert recommendation.target == 'CLOSE_UP'
    assert not recommendation.actionable
