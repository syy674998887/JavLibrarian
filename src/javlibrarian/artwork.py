"""Artwork download, validation, poster cropping, and VR poster matching."""

import os
import re
import sys
import warnings
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit(
        "Missing Pillow. This project manages dependencies with uv. Run:  uv sync\n"
        "Then use uv run javlibrarian ... instead of invoking Python directly."
    )

from .sources import JAVBUS, JAVDB


POSTER_WIDTH_RATIO = 0.475
PS_MATCH_HEIGHT = 100
PS_MATCH_MAX_RMSE = 60.0
PS_MIN_STDDEV = 30.0
MIN_IMAGE_EDGE = 200
SAMPLES_DIR = "Samples"
DMM_CID = re.compile(
    r"dmm\.co\.jp/(?:pics_dig/)?(?:digital/video|mono/movie/adult)/([^/]+)/"
)

_IMAGE_ERRORS = (
    OSError,
    SyntaxError,
    ValueError,
    Image.DecompressionBombWarning,
    Image.DecompressionBombError,
)


def _load_image(path):
    """Fully decode an image, apply EXIF orientation, and reject invalid input."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                source.load()
                return ImageOps.exif_transpose(source).copy()
    except _IMAGE_ERRORS:
        return None


def image_size(path):
    image = _load_image(path)
    if image is None:
        return None, None
    try:
        return image.size
    finally:
        image.close()


def _save_jpeg_atomic(image, destination):
    destination = Path(destination)
    temporary = destination.with_name(
        f".{destination.stem}.{os.getpid()}.tmp{destination.suffix}"
    )
    try:
        with image.convert("RGB") as rgb:
            rgb.save(temporary, format="JPEG", quality=95, optimize=True)
        os.replace(temporary, destination)
        return True
    except _IMAGE_ERRORS:
        return False
    finally:
        temporary.unlink(missing_ok=True)


def make_poster(source, destination, ratio=POSTER_WIDTH_RATIO):
    """Create a poster from a portrait image or the right side of a landscape cover."""
    image = _load_image(source)
    if image is None:
        return False
    try:
        width, height = image.size
        if not width or not height:
            return False
        if width / height < 1.15:
            return _save_jpeg_atomic(image, destination)
        poster_width = max(1, min(int(width * ratio), width))
        offset_x = width - poster_width
        with image.crop((offset_x, 0, width, height)) as poster:
            return _save_jpeg_atomic(poster, destination)
    finally:
        image.close()


def download(fetcher, url, destination, referer=None, min_edge=0):
    """Download an image atomically, optionally enforcing a minimum short edge."""
    if not url:
        return False
    status, data = fetcher.get(url, referer=referer, binary=True)
    if status != 200 or not data or len(data) < 1024:
        return False
    destination = Path(destination)
    temporary = destination.with_name(
        f".{destination.stem}.{os.getpid()}.tmp{destination.suffix}"
    )
    try:
        temporary.write_bytes(data)
        if min_edge:
            width, height = image_size(temporary)
            if not width or not height or min(width, height) < min_edge:
                return False
        os.replace(temporary, destination)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def referer_for(url):
    return JAVDB + "/" if "jdbstatic.com" in (url or "") else JAVBUS + "/"


def download_with_alt(fetcher, url, alternate, destination, min_edge=MIN_IMAGE_EDGE):
    """Download from the primary source, falling back to the alternate source."""
    if download(
        fetcher,
        url,
        destination,
        referer=referer_for(url),
        min_edge=min_edge,
    ):
        return True
    if alternate:
        return download(
            fetcher,
            alternate,
            destination,
            referer=referer_for(alternate),
            min_edge=min_edge,
        )
    return False


def gray_matrix(source, width, height):
    """Decode and resize an image into an 8-bit grayscale matrix."""
    if width <= 0 or height <= 0:
        return None
    image = _load_image(source)
    if image is None:
        return None
    try:
        with image.convert("L") as gray:
            with gray.resize((width, height), Image.Resampling.LANCZOS) as scaled:
                pixels = scaled.tobytes()
    finally:
        image.close()
    return [
        list(pixels[row * width : (row + 1) * width]) for row in range(height)
    ]


def gray_stddev(matrix):
    values = [value for row in matrix for value in row]
    if not values:
        return 0.0
    average = sum(values) / len(values)
    return (sum((value - average) ** 2 for value in values) / len(values)) ** 0.5


def gray_rmse(left, right):
    if not left or not right:
        return float("inf")
    total = count = 0
    for left_row, right_row in zip(left, right):
        for left_value, right_value in zip(left_row, right_row):
            difference = left_value - right_value
            total += difference * difference
            count += 1
    return (total / count) ** 0.5 if count else float("inf")


def ps_reference_url(samples, code=None):
    """Derive the DMM portrait-reference URL from samples or a catalog number."""
    content_id = None
    for sample in samples:
        match = DMM_CID.search(sample or "")
        if match:
            content_id = match.group(1)
            break
    if not content_id and code:
        match = re.match(r"^([A-Za-z]+)[-_]?(\d+)$", code.strip())
        if match:
            content_id = f"{match.group(1).lower()}{int(match.group(2)):05d}"
    if not content_id:
        return None
    return (
        f"https://pics.dmm.co.jp/digital/video/{content_id}/{content_id}ps.jpg"
    )


def is_vr(data, code):
    """Detect VR titles from the catalog number, title, or genres."""
    if "VR" in re.sub(r"[^A-Za-z]", "", code).upper():
        return True
    title = data.get("title") or ""
    if "【VR】" in title or "[VR]" in title.upper():
        return True
    return any("VR" in (genre or "").upper() for genre in data.get("genres", []))


def pick_sample_poster(fetcher, candidates, reference_url, workdir):
    """Choose a portrait sample matching the DMM reference image."""
    portrait = []
    for candidate in candidates:
        width, height = image_size(candidate)
        if width and height and width < height:
            portrait.append(candidate)
    if not portrait:
        return None, "no portrait image among samples"

    base = target_width = target_height = None
    if reference_url:
        reference_path = Path(workdir) / "_ps_ref.jpg"
        if download(
            fetcher,
            reference_url,
            reference_path,
            referer=JAVBUS + "/",
            min_edge=100,
        ):
            width, height = image_size(reference_path)
            if width and height:
                target_width = max(1, round(width * PS_MATCH_HEIGHT / height))
                target_height = PS_MATCH_HEIGHT
                base = gray_matrix(reference_path, target_width, target_height)
                if base and gray_stddev(base) < PS_MIN_STDDEV:
                    base = None
            reference_path.unlink(missing_ok=True)
    if not base:
        return portrait[0], "first portrait sample (no reference)"

    best = None
    best_score = float("inf")
    for candidate in portrait:
        score = gray_rmse(
            base, gray_matrix(candidate, target_width, target_height)
        )
        if score < best_score:
            best, best_score = candidate, score
    if best_score > PS_MATCH_MAX_RMSE:
        return None, f"no matching poster among samples (RMSE {best_score:.0f})"
    return best, f"RMSE {best_score:.0f}"
