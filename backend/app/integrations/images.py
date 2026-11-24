"""Image processing for uploads (OQ-10, OQ-14, OQ-15).

Every image is decoded and re-encoded, which drops EXIF/GPS and any other metadata; the uploaded bytes are
never stored. Decoding is bounded (pixel limit) so a crafted file cannot exhaust memory.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 60_000_000

PUBLIC_FORMATS = {"JPEG", "PNG", "WEBP"}
PRIVATE_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}
PUBLIC_WIDTHS = (560, 800, 1300)
PUBLIC_MIN_WIDTH = 800
PRIVATE_MAX_SIDE = 2000


class ImageError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Variant:
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class PublicImage:
    width: int
    height: int
    variants: dict[str, Variant]


def _open(data: bytes, formats: set[str]) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image_format = image.format or ""
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise ImageError("INVALID_IMAGE", "The file is not a readable image.") from exc
    if image_format not in formats:
        raise ImageError("UNSUPPORTED_FILE_TYPE", "This image format is not allowed.")
    # Apply the camera orientation before the EXIF block is dropped.
    return ImageOps.exif_transpose(image)


def _flatten(image: Image.Image, keep_alpha: bool) -> Image.Image:
    if keep_alpha and image.mode in ("RGBA", "LA", "P"):
        return image.convert("RGBA")
    if image.mode != "RGB":
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image


def process_public(data: bytes) -> PublicImage:
    image = _flatten(_open(data, PUBLIC_FORMATS), keep_alpha=True)
    width, height = image.size
    if width < PUBLIC_MIN_WIDTH:
        raise ImageError("IMAGE_TOO_SMALL", f"The image must be at least {PUBLIC_MIN_WIDTH} px wide.")
    variants = {}
    for target in PUBLIC_WIDTHS:
        w = min(target, width)
        h = round(height * w / width)
        resized = image.resize((w, h), Image.Resampling.LANCZOS) if w != width else image
        buffer = io.BytesIO()
        resized.save(buffer, "WEBP", quality=82, method=4)
        variants[str(target)] = Variant(buffer.getvalue(), w, h)
    return PublicImage(width, height, variants)


def process_private(data: bytes) -> Variant:
    """Client request photo: JPEG, longest side ≤ 2000 px, no metadata (HEIC accepted and converted)."""
    image = _flatten(_open(data, PRIVATE_FORMATS), keep_alpha=False)
    image.thumbnail((PRIVATE_MAX_SIDE, PRIVATE_MAX_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85, optimize=True)
    return Variant(buffer.getvalue(), image.size[0], image.size[1])
