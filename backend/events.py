import json
import logging
import sqlite3
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .models import SystemEvent


class EventStore:
    def __init__(self, settings):
        self.settings = settings
        Path(settings.database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(settings.database)
        self.db.execute('PRAGMA auto_vacuum = FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, ts REAL, body TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, body TEXT)')
        self.db.execute('INSERT OR REPLACE INTO settings VALUES (1, ?)', (settings.model_dump_json(),))
        self.logger = logging.getLogger('optic.events.' + str(id(self)))
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(Path(settings.database).parent / 'events.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
        self.logger.addHandler(handler)
        self.db.commit()

    def add(self, event: SystemEvent):
        body = event.model_dump_json()
        self.db.execute('INSERT INTO events VALUES (?, ?, ?)', (event.event_id, event.timestamp, body))
        self.db.execute('DELETE FROM events WHERE ts < ?', (time.time() - self.settings.event_ttl_seconds,))
        self.db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY ts DESC LIMIT ?)', (self.settings.event_limit,))
        self.db.commit()
        self.logger.info(body)

    def recent(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT body FROM events ORDER BY ts DESC LIMIT 40')]

    def close(self):
        self.db.close()
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
