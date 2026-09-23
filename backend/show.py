"""Latest received batch, for the local suggestion page."""
import json
from pathlib import Path


def batch_roots(repo: Path):
    return [
        repo / 'AcePro2-Handoff-0.7.1-20260922' / 'runtime' / 'received_batches',
        repo / 'runtime' / 'received_batches',
    ]


def latest_directory(roots):
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for directory in root.iterdir():
            manifest = directory / 'manifest.json'
            if directory.is_dir() and manifest.is_file():
                found.append((manifest.stat().st_mtime, directory))
    if not found:
        return None
    found.sort(key=lambda item: item[0])
    return found[-1][1]


def _inside(path: Path, roots):
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in roots if root.exists())


def lens_link(connection: str, simulated: bool) -> str:
    """Public lens-board status. A mock transport is not a connected ESP32."""
    if simulated:
        return 'waiting'
    if connection == 'connected':
        return 'connected'
    if connection == 'synchronizing':
        return 'synchronizing'
    return 'waiting'


def show_state(roots):
    directory = latest_directory(roots)
    if directory is None:
        return {'stage': 'waiting', 'count': 0, 'requestId': None, 'target': None, 'reason': '', 'subject': ''}
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    frames = manifest.get('frames') if isinstance(manifest.get('frames'), list) else []
    photos = frames or list(directory.glob('frame-*.jpg'))
    payload = {
        'stage': 'received',
        'count': len(photos),
        'requestId': manifest.get('requestId') if isinstance(manifest.get('requestId'), str) else directory.name,
        'target': None,
        'reason': '',
        'subject': '',
    }
    result_path = directory / 'result.json'
    if not result_path.is_file():
        return payload
    result = json.loads(result_path.read_text(encoding='utf-8'))
    decision = result.get('decision') if isinstance(result.get('decision'), dict) else {}
    analysis = result.get('analysis') if isinstance(result.get('analysis'), dict) else {}
    payload['stage'] = 'ready'
    payload['target'] = decision.get('target') or 'KEEP'
    payload['reason'] = decision.get('reason') or analysis.get('reason') or ''
    payload['subject'] = analysis.get('subject') or ''
    return payload


def frame_file(roots, request_id: str, index: int = 1):
    if not 1 <= index <= 32:
        return None
    directory = latest_directory(roots)
    if directory is None:
        return None
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    current = manifest.get('requestId') if isinstance(manifest.get('requestId'), str) else directory.name
    if request_id != current:
        return None
    path = directory / f'frame-{index:02d}.jpg'
    if not path.is_file() or not _inside(path, roots):
        return None
    return path
