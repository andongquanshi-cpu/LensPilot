#!/bin/bash
set -e
cd "$(dirname "$0")"
exec python3 android/desktop/receiver.py --port 8765 --output runtime/received_batches
