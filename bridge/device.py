"""PC-side application bridge; load the team's protocol plugin, never guess firmware bytes."""
import argparse
import asyncio
import importlib
import json
import os
import time
from collections import OrderedDict
from websockets.asyncio.client import connect


class FirmwareAdapter:
    async def query_position(self) -> dict:
        """Return actual_slot and position_verified from hardware, never from last command."""
        raise NotImplementedError('通信团队需实现位置查询与可信反馈')

    async def select(self, command):
        """Async iterator of accepted/moving/completed/failed feedback dictionaries.
        Firmware must deduplicate command_id across transport retries/reconnects and
        reject expired commands using an agreed clock/TTL mechanism.
        """
        raise NotImplementedError('通信团队需实现已验证的固件协议')
        yield


async def run(url, adapter, token):
    # In-memory bridge dedup is additional protection; durable dedup belongs to firmware.
    seen = OrderedDict()
    while True:
        try:
            async with connect(url, max_size=8192, open_timeout=5) as ws:
                await ws.send(json.dumps({'type':'auth','token':token}))
                session = None
                movement = None
                async def send(kind, **kwargs):
                    await ws.send(json.dumps(dict(type=kind,connection_session_id=session,**kwargs)))
                async def heartbeats():
                    while True:
                        await asyncio.sleep(3)
                        if session: await send('heartbeat')
                async def move(command):
                    try:
                        async for feedback in adapter.select(command):
                            await send('feedback',feedback=dict(command_id=command['command_id'],connection_session_id=session,**feedback))
                    except Exception:
                        await send('feedback',feedback=dict(command_id=command['command_id'],connection_session_id=session,status='failed',error_code='ADAPTER_ERROR'))
                heartbeat = asyncio.create_task(heartbeats())
                try:
                    async for raw in ws:
                        message = json.loads(raw)
                        if message['type']=='query_position':
                            session = message['connection_session_id']
                            if movement and not movement.done():
                                # Query must report uncertainty while the mechanism may still move.
                                position = {'actual_slot':None,'position_verified':False}
                            else:
                                position = await adapter.query_position()
                            await send('position',query_id=message['query_id'],**position)
                        elif message['type']=='command':
                            command = message['command']
                            if command['connection_session_id']!=session: continue
                            if command['command_id'] in seen: continue
                            if movement and not movement.done(): continue
                            if time.time()>command['expires_at']: continue
                            seen[command['command_id']]=True
                            while len(seen)>1024:seen.popitem(last=False)
                            movement=asyncio.create_task(move(command))
                finally:
                    heartbeat.cancel()
                    if movement: movement.cancel()
                    await asyncio.gather(heartbeat,*([movement] if movement else []),return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print('Bridge disconnected:',type(exc).__name__,'; reconnecting without resending movement')
            await asyncio.sleep(3)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='ws://127.0.0.1:8000/ws/device')
    p.add_argument('--adapter',required=True,help='Trusted local Python module:factory supplied by communication team')
    args=p.parse_args()
    token=os.environ.get('OPTIC_DEVICE_TOKEN')
    if not token: p.error('Set OPTIC_DEVICE_TOKEN in this PC environment')
    module,factory=args.adapter.split(':',1)
    adapter=getattr(importlib.import_module(module),factory)()
    asyncio.run(run(args.url,adapter,token))


if __name__=='__main__':main()
