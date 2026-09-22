from dataclasses import dataclass
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from .models import FrameMetadata

Image.MAX_IMAGE_PIXELS = 16_000_000


@dataclass
class Frame:
    meta: FrameMetadata
    jpeg: bytes


class LatestFrames:
    """One preview + one latest pending reference. No growing frame queue."""
    def __init__(self):
        self.latest: Frame | None = None
        self.pending: Frame | None = None

    def put(self, frame):
        self.latest = frame
        self.pending = frame if frame.meta.eligible else None

    def take(self):
        frame, self.pending = self.pending, None
        return frame

    def clear(self):
        self.latest = self.pending = None


def normalize_image(raw: bytes, settings) -> bytes:
    if len(raw) > settings.upload_max_bytes:
        raise ValueError('图片超过上传限制')
    try:
        with Image.open(BytesIO(raw)) as im:
            if im.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('仅支持 JPEG / PNG / WebP')
            if im.width * im.height > 16_000_000:
                raise ValueError('图片像素过多')
            im.load()
            from PIL.ImageOps import exif_transpose
            im = exif_transpose(im).convert('RGB')
            im.thumbnail((settings.image_size, settings.image_size))
            output = BytesIO()
            im.save(output, format='JPEG', quality=settings.jpeg_quality)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('无效图片') from exc
