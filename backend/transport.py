"""Application transport, NOT an Insta360/ESP32 firmware protocol implementation."""
import asyncio
from .models import CommandFeedback


class MockTransport:
    simulated = True

    def __init__(self, controller):
        self.controller = controller
        self.slot = next(iter(controller.config.slots.values()))
        self.tasks = set()

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def send(self, payload):
        if payload['type'] == 'query_position':
            self.spawn(self.position(payload))
        elif payload['type'] == 'command':
            self.spawn(self.move(payload['command']))

    async def position(self, payload):
        await asyncio.sleep(0.05)
        await self.controller.position(payload['connection_session_id'], payload['query_id'], self.slot, True)

    async def move(self, command):
        for status, delay in [('accepted', 0.05), ('moving', 0.15), ('completed', 0.6)]:
            await asyncio.sleep(delay)
            if self.controller.state.connection_session_id != command['connection_session_id']:
                return
            if status == 'completed':
                self.slot = command['target_slot']
            await self.controller.feedback(CommandFeedback(
                command_id=command['command_id'], connection_session_id=command['connection_session_id'],
                status=status, actual_slot=self.slot if status == 'completed' else None,
                position_verified=status == 'completed'))

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


class BridgeTransport:
    simulated = False

    def __init__(self, socket):
        self.socket = socket
        self.lock = asyncio.Lock()

    async def send(self, payload):
        async with self.lock:
            await asyncio.wait_for(self.socket.send_json(payload), timeout=2)

    async def close(self):
        pass
