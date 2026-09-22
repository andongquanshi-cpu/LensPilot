"""LAN prototype: receive a whole batch, then hand its directory to your agent."""
import argparse
import io
import json
import sys
from pathlib import Path
import tempfile
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import threading
from zipfile import ZipFile, BadZipFile
from urllib.parse import urlsplit, parse_qs
from chunk_upload import Uploads, UploadConflict, CHUNK

UPLOAD_LOCK = threading.Lock()
LIMIT = 22 * 1024 * 1024

def save_batch(body, root):
    with ZipFile(io.BytesIO(body)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 21 or len(set(names)) != len(names):
            raise ValueError("invalid entries")
        if sum(e.file_size for e in entries) > LIMIT:
            raise ValueError("batch too large")
        metadata = json.loads(archive.read("manifest.json"))
        if not isinstance(metadata.get("requestId"), str) or not metadata["requestId"]:
            raise ValueError("missing requestId")
        frames = metadata["frames"]
        expected = [f"frame-{i:02d}.jpg" for i in range(1, len(frames)+1)]
        if not 1 <= len(frames) <= 20 or [f["file"] for f in frames] != expected:
            raise ValueError("invalid frames")
        if set(names) != set(expected + ["manifest.json"]):
            raise ValueError("unexpected files")
        # Read and validate all entries before publishing a complete directory.
        contents = {name: archive.read(name) for name in names}
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
    for name, data in contents.items():
        (staging / name).write_bytes(data)
    destination = staging.with_name(staging.name.replace(".pending-", "batch-", 1))
    staging.rename(destination)
    return destination, metadata


def on_batch(directory, metadata):
    """Enqueue one analysis of frame-01. Keep the model off this HTTP handler."""
    print(f"RECEIVED {directory} ({len(metadata['frames'])} frames)", flush=True)
    threading.Thread(target=_analyze_batch, args=(directory,), daemon=True).start()


def _analyze_batch(directory):
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from backend.batch_job import analyze_received_batch
        analyze_received_batch(directory)
        print(f"ANALYZED {directory}", flush=True)
    except Exception as exc:
        print(f"ANALYSIS FAILED {type(exc).__name__}", flush=True)


class Receiver(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_error(self, format, *args):
        # HTTP keep-alive idle expiry is normal. Upload timeouts are logged explicitly above.
        if format == "Request timed out: %r":
            return
        super().log_error(format, *args)

    def do_GET(self):
        self.reply(200 if self.path == "/health" else 404, {"service": "ace-batch-receiver"})

    def do_POST(self):
        route = urlsplit(self.path)
        if route.path == "/batch" and route.query:
            return self.receive_chunk(parse_qs(route.query))
        if self.path != "/batch":
            return self.reply(404, {"error": "use /batch"})
        stage = "headers"
        received = 0
        length = 0
        started = time.monotonic()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= LIMIT:
                raise ValueError("invalid size")
            self.connection.settimeout(15)
            print(f"RECEIVING {length} bytes from {self.client_address[0]}", flush=True)
            stage = "upload"
            body = bytearray()
            next_report = 256 * 1024
            while received < length:
                chunk = self.rfile.read1(min(64 * 1024, length - received))
                if not chunk:
                    raise ValueError("incomplete upload: peer closed connection")
                body.extend(chunk)
                received += len(chunk)
                if received >= next_report or received == length:
                    print(f"UPLOAD {received}/{length} bytes ({time.monotonic()-started:.1f}s)", flush=True)
                    next_report = received + 256 * 1024
            stage = "validate_and_save"
            directory, metadata = save_batch(body, self.server.output)
            stage = "agent_hook"
            on_batch(directory, metadata)
            stage = "reply"
            self.reply(200, {"status": "received", "requestId": metadata["requestId"]})
        except (ValueError, KeyError, TypeError, BadZipFile, OSError) as error:
            code = 408 if isinstance(error, TimeoutError) else 400
            if isinstance(error, OSError) and stage == "validate_and_save":
                code = 500
            detail = {
                "error": str(error) or type(error).__name__,
                "type": type(error).__name__, "stage": stage,
                "receivedBytes": received, "expectedBytes": length,
            }
            print(f"FAILED HTTP {code}: {json.dumps(detail, ensure_ascii=False)} "
                  f"elapsed={time.monotonic()-started:.1f}s", flush=True)
            try:
                self.reply(code, detail)
            except OSError as reply_error:
                print(f"REPLY FAILED: {reply_error}", flush=True)

    def receive_chunk(self, query):
        try:
            upload_id = query['upload'][0]
            total = int(query['total'][0])
            digest = query['sha256'][0]
            offset = int(query['offset'][0])
            commit = query.get('commit', ['0'])[0] == '1'
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= CHUNK:
                raise ValueError('chunk exceeds 8192 bytes')
            self.connection.settimeout(8)
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError('incomplete chunk')
            def publish(body):
                directory, metadata = save_batch(body, self.server.output)
                on_batch(directory, metadata)
                return dict(status='received', requestId=metadata['requestId'])
            with UPLOAD_LOCK:
                if not hasattr(self.server, 'uploads'):
                    self.server.uploads = Uploads()
                result = self.server.uploads.accept(upload_id,total,digest,offset,data,commit,publish)
            if commit or result['nextOffset'] % (128*1024) == 0:
                print(f"CHUNKS {result['nextOffset']}/{total} completed={result['completed']}", flush=True)
            self.reply(200, result)
        except UploadConflict as error:
            self.reply(409, dict(error=str(error),nextOffset=error.offset))
        except (ValueError, KeyError, TypeError, BadZipFile, OSError) as error:
            code = 408 if isinstance(error,TimeoutError) else 400
            print(f"CHUNK FAILED {type(error).__name__}: {error}", flush=True)
            try:
                self.reply(code, dict(error=str(error)))
            except OSError:
                pass

    def reply(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path, default=Path("received_batches"))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Receiver)
    server.output = args.output
    print(f"Listening on :{args.port}; batches -> {args.output.resolve()}", flush=True)
    server.serve_forever()
