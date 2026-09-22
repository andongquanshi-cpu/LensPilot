import time
from .models import Filter, Decision


class DecisionEngine:
    def __init__(self, config):
        self.config = config
        self.candidate = Filter.KEEP
        self.count = 0
        self.last_observation = 0

    def reset(self):
        self.candidate, self.count = Filter.KEEP, 0

    def evaluate(self, analysis, state, intent):
        if time.time() - self.last_observation > self.config.max_frame_age:
            self.reset()
        self.last_observation = time.time()
        f, p = analysis.scene_features, intent.preference
        target = analysis.recommended_filter
        reason = analysis.reason
        if p == 'star' and f.point_lights:
            target, reason = Filter.STAR, '星芒偏好生效，画面存在点状亮光。'
        elif p == 'soft' and f.highlights:
            target, reason = Filter.BLACK_MIST, '柔和偏好生效，画面存在高光依据。'
        elif p == 'detail' and f.close_detail and self.config.demo_distance_verified:
            target, reason = Filter.CLOSE_UP, '近摄偏好与已配置实测演示距离约束生效。'
        # The model suggests; explicit observable prerequisites constrain actuation.
        if target == Filter.CPL and (not (f.glass_or_water and f.reflection_obscures_subject) or p == 'preserve_reflections'):
            target, reason = Filter.KEEP, '反光依据不足，或用户希望保留倒影。'
        if target == Filter.CLOSE_UP and not ((f.close_detail or p == 'detail') and self.config.demo_distance_verified):
            target, reason = Filter.KEEP, '没有经实测确认的近摄距离约束，保持当前镜片。'
        if target == Filter.BLACK_MIST and (p == 'sharp' or not (f.highlights and (f.portrait or f.soft_style or p == 'soft'))):
            target, reason = Filter.KEEP, '尊重清晰细节偏好，或缺少柔和创作依据。'
        if target == Filter.STAR and not f.point_lights:
            target, reason = Filter.KEEP, '没有适合星芒的点状亮光。'
        if target in (Filter.STAR, Filter.BLACK_MIST):
            if p == 'star' and f.point_lights:
                target = Filter.STAR
            elif p == 'soft' and f.highlights:
                target = Filter.BLACK_MIST
            elif p == 'sharp':
                target, reason = Filter.KEEP, '清晰细节偏好生效，保持当前状态。'
            elif f.portrait and f.point_lights and self.config.portrait_prefers_mist:
                target = Filter.BLACK_MIST
        if target not in self.config.slots and target != Filter.KEEP:
            target, reason = Filter.KEEP, '硬件未配置该镜片或空位。'
        if analysis.uncertainty > 0.65:
            target, reason = Filter.KEEP, '分析不确定性较高，保持当前状态。'
        if target in (Filter.KEEP, state.actual_filter):
            self.reset()
            return Decision(frame_id=analysis.frame_id, reason=reason if target == Filter.KEEP else '当前已是所需镜片。')
        if target != self.candidate:
            self.candidate, self.count = target, 0
        self.count += 1
        ready = self.count >= self.config.consistent_count
        hold = time.time() - state.last_completed_at
        if hold < max(self.config.min_hold_seconds, self.config.cooldown_seconds):
            ready, reason = False, '等待最短保持时间与切换冷却。'
        elif not ready:
            reason = f'候选连续一致 {self.count}/{self.config.consistent_count} 次。'
        return Decision(frame_id=analysis.frame_id, target=target, reason=reason, actionable=ready)
