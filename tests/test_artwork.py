import io

from PIL import Image

from javlibrarian import artwork


class ImageFetcher:
    def __init__(self, data):
        self.data = data

    def get(self, *args, **kwargs):
        return 200, self.data


def test_invalid_image_does_not_damage_existing_target(tmp_path):
    destination = tmp_path / "fanart.jpg"
    original = b"existing-valid-image"
    destination.write_bytes(original)

    result = artwork.download(
        ImageFetcher(b"x" * 2048),
        "https://img.test/a.jpg",
        destination,
        min_edge=200,
    )

    assert result is False
    assert destination.read_bytes() == original
    assert list(tmp_path.glob(".fanart.*.tmp.jpg")) == []


def test_valid_image_atomically_replaces_target(tmp_path):
    destination = tmp_path / "fanart.jpg"
    destination.write_bytes(b"old")
    encoded = io.BytesIO()
    Image.new("RGB", (800, 600), "navy").save(encoded, format="JPEG")
    replacement = encoded.getvalue()

    result = artwork.download(
        ImageFetcher(replacement),
        "https://img.test/a.jpg",
        destination,
        min_edge=200,
    )

    assert result is True
    assert destination.read_bytes() == replacement
    assert list(tmp_path.glob(".fanart.*.tmp.jpg")) == []


def test_pillow_backend_crops_right_side_and_creates_no_conversion_artifact(tmp_path):
    source = tmp_path / "cover.png"
    destination = tmp_path / "poster.jpg"
    cover = Image.new("RGB", (400, 200), "red")
    cover.paste("blue", (200, 0, 400, 200))
    cover.save(source)
    cover.close()

    assert artwork.image_size(source) == (400, 200)
    assert artwork.make_poster(source, destination, ratio=0.5) is True
    with Image.open(destination) as poster:
        assert poster.size == (200, 200)
        center = poster.getpixel((100, 100))
        assert center[0] < 30 and center[2] > 220
    assert list(tmp_path.glob(".*.tmp.jpg")) == []

    matrix = artwork.gray_matrix(source, 20, 10)
    assert (len(matrix), len(matrix[0])) == (10, 20)
    assert list(tmp_path.glob("*.bmp")) == []


def test_reference_url_supports_both_dmm_paths_and_catalog_fallback():
    assert artwork.ps_reference_url(
        ["https://pics.dmm.co.jp/digital/video/sone00035/sone00035jp-1.jpg"]
    ) == "https://pics.dmm.co.jp/digital/video/sone00035/sone00035ps.jpg"
    assert artwork.ps_reference_url(
        ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/savr01062/x.jpg"]
    ) == "https://pics.dmm.co.jp/digital/video/savr01062/savr01062ps.jpg"
    assert artwork.ps_reference_url([], code="SONE-035") == (
        "https://pics.dmm.co.jp/digital/video/sone00035/sone00035ps.jpg"
    )
    assert artwork.ps_reference_url([], code="FC2-PPV-1234567") is None


def test_vr_detection_uses_code_title_or_genre():
    assert artwork.is_vr({"title": "", "genres": []}, "IPVR-256") is True
    assert artwork.is_vr({"title": "【VR】Title", "genres": []}, "FSVSS-003") is True
    assert artwork.is_vr({"title": "Title", "genres": ["VR専用"]}, "FSVSS-003") is True
    assert artwork.is_vr({"title": "Title", "genres": ["剧情"]}, "SONE-035") is False


def test_download_with_alt_uses_source_specific_referers(monkeypatch, tmp_path):
    calls = []

    def fake_download(fetcher, url, destination, referer=None, min_edge=0):
        calls.append((url, referer, min_edge))
        return url.endswith("alternate.jpg")

    monkeypatch.setattr(artwork, "download", fake_download)

    result = artwork.download_with_alt(
        object(),
        "https://pics.dmm.co.jp/primary.jpg",
        "https://c1.jdbstatic.com/alternate.jpg",
        tmp_path / "image.jpg",
    )

    assert result is True
    assert calls == [
        (
            "https://pics.dmm.co.jp/primary.jpg",
            "https://www.javbus.com/",
            artwork.MIN_IMAGE_EDGE,
        ),
        (
            "https://c1.jdbstatic.com/alternate.jpg",
            "https://javdb.com/",
            artwork.MIN_IMAGE_EDGE,
        ),
    ]
