"""Latest received batch, for the local suggestion page."""
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path


def batch_roots(repo: Path):
    return [
        repo / 'AcePro2-Handoff-0.7.1-20260922' / 'runtime' / 'received_batches',
        repo / 'runtime' / 'received_batches',
    ]


def directories(roots):
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for directory in root.iterdir():
            manifest = directory / 'manifest.json'
            if directory.is_dir() and manifest.is_file() and not directory.name.startswith('.'):
                try:
                    metadata = json.loads(manifest.read_text(encoding='utf-8'))
                    if isinstance(metadata, dict) and _inside(manifest, roots):
                        found.append((manifest.stat().st_mtime, directory, metadata))
                except (OSError, ValueError):
                    continue
    return sorted(found, key=lambda item: (item[0], str(item[1])))


def is_capture(metadata):
    return metadata.get('source') == 'CAMERA_PHOTO' and metadata.get('contentKind') == 'CAMERA_ORIGINAL_JPEG'


def latest_directory(roots):
    found = [item for item in directories(roots) if not is_capture(item[2])]
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


def show_state(roots, directory=None):
    directory = directory or latest_directory(roots)
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
    payload['commandTarget'] = decision.get('commandTarget') or payload['target']
    payload['executionNote'] = decision.get('executionNote') or ''
    payload['reason'] = decision.get('reason') or analysis.get('reason') or ''
    payload['subject'] = analysis.get('subject') or ''
    return payload


def frame_file(roots, request_id: str, index: int = 1):
    if not 1 <= index <= 32:
        return None
    for _, directory, manifest in reversed(directories(roots)):
        current = manifest.get('requestId') if isinstance(manifest.get('requestId'), str) else directory.name
        if request_id == current:
            path = directory / f'frame-{index:02d}.jpg'
            if path.is_file() and _inside(path, roots):
                return path
    return None


def capture_time(metadata):
    # Phone monotonic triggeredAtMs is NOT an exposure timestamp.
    match = re.search(r'IMG_(\d{8})_(\d{6})_', str(metadata.get('cameraPath', '')))
    if match:
        try:
            return datetime.strptime(''.join(match.groups()), '%Y%m%d%H%M%S').timestamp()
        except ValueError:
            pass
    return None


class ShowFlow:
    """Single local demo round. Timer advances presentation, never hardware position."""
    def __init__(self, roots, clock=time.time):
        self.roots, self.clock = roots, clock
        self.lock = threading.RLock()
        self.pinned = None
        self.arm_at = None
        self.delay = 3.0
        self.photo = None
        self.ignored = set()
        self.photo_baseline = set()

    def state(self):
        with self.lock:
            items = directories(self.roots)
            if self.pinned is None:
                candidates = [x for x in items if not is_capture(x[2]) and x[2].get('requestId', x[1].name) not in self.ignored]
                if candidates:
                    self.pinned = candidates[-1][1]
            if self.pinned is None:
                return dict(stage='waiting', count=0, requestId=None, target=None, reason='', subject='')
            payload = show_state(self.roots, self.pinned)
            if self.arm_at is None:
                return payload
            waiting_at = self.arm_at + self.delay
            payload['delaySeconds'] = self.delay
            if self.clock() < waiting_at:
                return payload
            payload['stage'] = 'capture'
            if self.photo is None:
                for received, directory, metadata in items:
                    if not is_capture(metadata) or received < waiting_at:
                        continue
                    keys = {metadata.get('requestId'), metadata.get('cameraPath')} - {None, ''}
                    if keys & self.photo_baseline:
                        continue
                    if metadata.get('roundId') not in (None, payload['requestId']):
                        continue
                    taken = capture_time(metadata)
                    if taken is None or taken < waiting_at or taken > self.clock() + 5:
                        continue
                    path = directory / 'frame-01.jpg'
                    if path.is_file() and _inside(path, self.roots):
                        self.photo = metadata['requestId']
                        break
            if self.photo:
                payload['stage'] = 'complete'
                payload['photoRequestId'] = self.photo
            return payload

    def arm(self, request_id, delay):
        with self.lock:
            payload = self.state()
            if payload['requestId'] != request_id or payload['stage'] not in ('ready', 'capture', 'complete'):
                raise ValueError('本轮分析尚未完成或轮次已经改变')
            if self.arm_at is None:
                self.photo_baseline = {value for _, _, m in directories(self.roots) if is_capture(m)
                                       for value in (m.get('requestId'), m.get('cameraPath')) if value}
                self.arm_at, self.delay = self.clock(), delay
            return self.state()

    def reset(self):
        with self.lock:
            self.ignored = {m.get('requestId', d.name) for _, d, m in directories(self.roots)}
            self.pinned = self.arm_at = self.photo = None
            self.photo_baseline = set()
            return self.state()
