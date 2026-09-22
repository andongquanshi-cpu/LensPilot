"""Bounded, resumable LAN uploads; only verified complete archives are published."""
import hashlib
import re
import time

LIMIT = 22 * 1024 * 1024
CHUNK = 8192

class UploadConflict(ValueError):
    def __init__(self, offset):
        self.offset = offset
        super().__init__('offset mismatch')

class Uploads:
    def __init__(self):
        self.items = {}

    def accept(self, upload_id, total, digest, offset, data, commit, publish):
        now = time.monotonic()
        self.items = {k:v for k,v in self.items.items() if now-v['updated'] < 900}
        if not re.fullmatch(r'[a-fA-F0-9-]{36}', upload_id):
            raise ValueError('invalid upload id')
        if not 0 < total <= LIMIT or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('invalid size or checksum')
        if len(data) > CHUNK or offset < 0 or offset > total:
            raise ValueError('invalid chunk')
        if commit and data:
            raise ValueError('commit must be empty')
        item = self.items.get(upload_id)
        if item is None:
            if offset != 0:
                raise UploadConflict(0)
            if sum(v['result'] is None for v in self.items.values()) >= 4:
                raise ValueError('too many pending uploads')
            completed = [k for k,v in self.items.items() if v['result'] is not None]
            if len(completed) >= 64:
                del self.items[completed[0]]
            item = dict(total=total,digest=digest,data=bytearray(),updated=now,result=None)
            self.items[upload_id] = item
        if item['total'] != total or item['digest'] != digest:
            raise ValueError('upload id reused for different content')
        item['updated'] = now
        if item['result'] is not None:
            return item['result']
        body = item['data']
        if offset > len(body):
            raise UploadConflict(len(body))
        if commit:
            if len(body) != total or offset != total:
                raise UploadConflict(len(body))
            if hashlib.sha256(body).hexdigest() != digest:
                del self.items[upload_id]
                raise ValueError('checksum mismatch')
            result = publish(body)
            item['result'] = dict(result, nextOffset=total, completed=True)
            item['data'] = None
            return item['result']
        if not data or offset+len(data)>total:
            raise ValueError('empty or oversized chunk')
        if offset < len(body):
            if body[offset:offset+len(data)] != data:
                raise ValueError('conflicting duplicate chunk')
        else:
            body.extend(data)
        return dict(nextOffset=len(body),completed=False)
