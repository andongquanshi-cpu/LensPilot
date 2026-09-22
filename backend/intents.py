from .models import UserIntent, Filter


def parse_intent(text: str):
    text = text.strip().rstrip('。.!！')
    commands = {
        '保持当前镜片': dict(kind='lock', scope='持续到解锁或恢复自动'),
        '恢复自动': dict(kind='auto', scope='清除锁定并恢复默认偏好'),
        '我要星芒效果': dict(kind='style', preference='star'),
        '拍近一点的细节': dict(kind='style', preference='detail'),
        '保留倒影': dict(kind='style', preference='preserve_reflections'),
        '我要清晰细节': dict(kind='style', preference='sharp'),
        '我要柔和效果': dict(kind='style', preference='soft'),
        '切到黑柔': dict(kind='select', target=Filter.BLACK_MIST, scope='单次选择并锁定'),
        '切到星光': dict(kind='select', target=Filter.STAR, scope='单次选择并锁定'),
        '切到偏振镜': dict(kind='select', target=Filter.CPL, scope='单次选择并锁定'),
        '切到近摄镜': dict(kind='select', target=Filter.CLOSE_UP, scope='单次选择并锁定'),
    }
    return UserIntent(text=text, **commands.get(text, dict(kind='ignored', scope='未生效：仅接受明确的已支持表达')))
