"""Local capture is executed only on the machine actually hosting this adapter."""
import asyncio
from io import BytesIO
import time
from PIL import Image, ImageDraw
from .frames import normalize_image


def demo_image(tick):
    im = Image.new('RGB', (1280, 720), '#13262f')
    d = ImageDraw.Draw(im)
    for y in range(720):
        d.line((0, y, 1280, y), fill=(15 + y // 25, 30 + y // 15, 45 + y // 12))
    d.polygon([(0, 440), (220, 170), (410, 385), (620, 130), (950, 460)], fill='#294c59')
    d.polygon([(450, 460), (860, 180), (1280, 440)], fill='#3f6465')
    d.ellipse((960, 80, 1050, 170), fill='#e5c69b')
    d.rectangle((0, 460, 1280, 720), fill='#183b49')
    for y in range(485, 710, 22):
        x = 900 + (tick % 20) * 2
        d.line((x - (y - 450), y, x + (y - 450), y), fill='#77908a', width=2)
    d.text((40, 35), 'SYNTHETIC DEMO / NOT CAMERA FOOTAGE', fill='#e6e8e6', font_size=24)
    d.text((40, 665), f'FRAME {tick:06d}   /   NO OPTICAL EFFECT SIMULATION', fill='#a3c2c8', font_size=18)
    out = BytesIO()
    im.save(out, format='JPEG', quality=85)
    return out.getvalue()


class SourceManager:
    def __init__(self, controller):
        self.controller = controller
        self.task = None

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    async def start(self, kind, media_id=None, camera_index=0):
        c = self.controller
        if kind == 'video' and media_id not in c.config.media_files:
            raise ValueError('视频只能从受控配置 media_files 中选择')
        if kind == 'camera' and camera_index not in c.config.camera_indices:
            raise ValueError('摄像头编号未配置')
        if kind not in ('demo', 'video', 'camera', 'upload', 'ace_bridge'):
            raise ValueError('不支持的画面源')
        await self.stop()
        session = c.switch_source(kind, {'demo': '合成演示画面', 'video': media_id or '视频', 'camera': '普通摄像头', 'upload': 'HTTP / 本地图片', 'ace_bridge': 'Ace Pro 2 · 外部画面桥接'}[kind], kind == 'demo')
        if kind in ('demo', 'video', 'camera'):
            self.task = asyncio.create_task(self.run(kind, session, media_id, camera_index))
        return session

    async def run(self, kind, session, media_id, index):
        cap = None
        c, seq = self.controller, 0
        try:
            if kind != 'demo':
                import cv2
                # Local/controlled paths only. No arbitrary URL or server path API.
                cap = await asyncio.to_thread(cv2.VideoCapture, c.config.media_files[media_id] if kind == 'video' else index)
                if not cap.isOpened():
                    raise ValueError('无法打开画面源')
                fps = cap.get(cv2.CAP_PROP_FPS)
                interval = 1 / min(30, max(1, fps if fps > 0 else 15))
            else:
                interval = 0.2
            while session == c.source['session_id']:
                if c.source['status'] == 'paused':
                    await asyncio.sleep(0.1)
                    continue
                if kind == 'demo':
                    jpeg = demo_image(seq)
                    captured_version = c.state.state_version
                else:
                    captured_version = c.state.state_version
                    ok, pixels = await asyncio.to_thread(cap.read)
                    if not ok:
                        c.source['status'] = 'ended' if kind == 'video' else 'disconnected'
                        c.invalidate()
                        c.event('source_end', '视频文件结束' if kind == 'video' else '摄像头断开')
                        break
                    ok, encoded = cv2.imencode('.jpg', pixels)
                    if not ok:
                        continue
                    jpeg = normalize_image(encoded.tobytes(), c.config)
                if session != c.source['session_id']:
                    break
                if c.source['status'] == 'paused':
                    continue
                capture_version = None if kind == 'video' and not c.state.simulated else captured_version
                c.ingest(jpeg, session, seq, time.time(), capture_version)
                seq += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if session == c.source['session_id']:
                c.source['status'] = 'disconnected'
                c.invalidate()
                c.event('source_error', '画面接入失败（' + type(exc).__name__ + '），请检查本地配置与依赖')
        finally:
            if cap:
                cap.release()
