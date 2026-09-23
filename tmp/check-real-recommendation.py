import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from backend.config import load_settings
from backend.vlm import create_vision, frame_from_jpeg
from backend.vision import validate_analysis
from backend.decision import DecisionEngine
from backend.models import DeviceState, UserIntent
from backend.frames import normalize_image

settings = load_settings()
vision = create_vision(settings)
cases = [
    ('night-street', Path('C:/Users/35552/AppData/Local/Temp/codex-clipboard-ba6598b8-5586-4720-a50e-5a50bc5653ee.png')),
    ('ceiling-lights', root / 'AcePro2-Handoff-0.7.1-20260922/runtime/received_batches/batch-webupload/frame-01.jpg'),
    ('table-detail', root / 'AcePro2-Handoff-0.7.1-20260922/runtime/received_batches/batch-qrsaewlh/frame-01.jpg'),
]
results = []
for name, path in cases:
    try:
        frame = frame_from_jpeg(normalize_image(path.read_bytes(), settings), 'regression-' + name)
        raw = vision.analyze_sync(frame, {'supported_filters':list(settings.slots), 'installed_filter':None})
        analysis = validate_analysis(raw, frame, settings)
        decision = DecisionEngine(settings).evaluate(analysis, DeviceState(), UserIntent(), recommendation_only=True)
        result = dict(case=name, model=analysis.recommended_filter, target=decision.target, reason=decision.reason, features=analysis.scene_features.model_dump(), uncertainty=analysis.uncertainty)
    except Exception as exc:
        result = dict(case=name, error=type(exc).__name__, detail=exc.errors(include_input=False) if hasattr(exc, 'errors') else str(exc)[:250])
    results.append(result)
    print(json.dumps(result, ensure_ascii=True), flush=True)
(root / 'tmp/real-recommendation-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
