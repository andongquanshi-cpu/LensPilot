from pathlib import Path
import hashlib, json, sys
root = Path(__file__).resolve().parent
manifest = json.loads((root / "CONTENTS.json").read_text(encoding="utf-8"))
failed = []
for item in manifest["files"]:
    path = root / item["path"]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        failed.append(item["path"])
if failed:
    print("Missing or changed files:\n" + "\n".join(failed))
    sys.exit(1)
print("Verified", len(manifest["files"]), "files")
