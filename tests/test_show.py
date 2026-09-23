import json
from backend.show import frame_file, lens_link, show_state


def test_lens_link_ignores_mock_and_reports_real_bridge():
    assert lens_link('connected', True) == 'waiting'
    assert lens_link('synchronizing', True) == 'waiting'
    assert lens_link('disconnected', False) == 'waiting'
    assert lens_link('synchronizing', False) == 'synchronizing'
    assert lens_link('connected', False) == 'connected'


def test_waiting_when_no_batch(tmp_path):
    assert show_state([tmp_path / 'missing'])['stage'] == 'waiting'


def test_ready_batch_reports_count_and_suggestion(tmp_path):
    batch = tmp_path / 'batch-1'
    batch.mkdir()
    (batch / 'manifest.json').write_text(json.dumps({
        'requestId': 'req-9',
        'frames': [{'file': 'frame-01.jpg'}, {'file': 'frame-02.jpg'}],
    }), encoding='utf-8')
    (batch / 'frame-01.jpg').write_bytes(b'jpeg')
    assert show_state([tmp_path])['stage'] == 'received'
    assert show_state([tmp_path])['count'] == 2
    (batch / 'result.json').write_text(json.dumps({
        'decision': {'target': 'STAR', 'reason': '点状亮光'},
        'analysis': {'subject': '灯'},
    }), encoding='utf-8')
    state = show_state([tmp_path])
    assert state['stage'] == 'ready'
    assert state['target'] == 'STAR'
    assert state['reason'] == '点状亮光'
    assert frame_file([tmp_path], 'req-9').name == 'frame-01.jpg'
    assert frame_file([tmp_path], 'other') is None
    (batch / 'frame-02.jpg').write_bytes(b'jpeg-2')
    assert frame_file([tmp_path], 'req-9', 2).name == 'frame-02.jpg'
    assert frame_file([tmp_path], 'req-9', 3) is None
    assert frame_file([tmp_path], 'req-9', 0) is None
    assert frame_file([tmp_path], 'req-9', 33) is None
