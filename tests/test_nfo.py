from xml.etree import ElementTree as ET

from javlibrarian.nfo import build_nfo


def test_nfo_contains_media_center_fields_and_escapes_text():
    data = {
        "source": "javbus+javdb",
        "code": "SONE-035",
        "dvdid": "SONE-035",
        "title": "SONE-035 日本語 & 原題",
        "title_cn": "SONE-035 中文 <标题>",
        "release": "2024-02-03",
        "runtime": 123,
        "studio": "Maker",
        "label": "Label",
        "director": "Director",
        "series": "Series",
        "genres": ["剧情", "VR"],
        "actors": [
            {"name": "Actor A", "thumb": "https://img.test/a.jpg"},
            {"name": "Actor B", "thumb": ""},
        ],
    }

    payload = build_nfo(data, ["中文字幕"], "SONE-035-C")
    root = ET.fromstring(payload)

    assert root.tag == "movie"
    assert root.findtext("title") == "SONE-035 中文 <标题>"
    assert root.findtext("originaltitle") == "日本語 & 原題"
    assert root.findtext("sorttitle") == "SONE-035"
    assert root.findtext("num") == "SONE-035"
    assert root.findtext("uniqueid") == "SONE-035"
    assert root.find("uniqueid").attrib == {"type": "num", "default": "true"}
    assert root.findtext("premiered") == "2024-02-03"
    assert root.findtext("releasedate") == "2024-02-03"
    assert root.findtext("year") == "2024"
    assert root.findtext("runtime") == "123"
    assert root.findtext("studio") == "Maker"
    assert root.findtext("maker") == "Maker"
    assert root.findtext("label") == "Label"
    assert root.findtext("director") == "Director"
    assert root.findtext("set/name") == "Series"
    assert [element.text for element in root.findall("genre")] == [
        "剧情",
        "VR",
        "中文字幕",
    ]
    assert [element.text for element in root.findall("tag")] == ["中文字幕", "Series"]
    assert [element.findtext("name") for element in root.findall("actor")] == [
        "Actor A",
        "Actor B",
    ]
    assert root.findall("actor")[0].findtext("thumb") == "https://img.test/a.jpg"
    assert root.findall("actor")[1].find("thumb") is None
    assert root.findtext("poster") == "poster.jpg"
    assert root.findtext("fanart/thumb") == "fanart.jpg"
    assert root.findtext("source") == "javbus+javdb"
    assert root.findtext("originalfolder") == "SONE-035-C"
    assert b"&amp;" in payload and b"&lt;" in payload


def test_nfo_omits_empty_optional_fields_and_uses_original_title_fallback():
    payload = build_nfo(
        {
            "source": "javdb",
            "code": "TEST-001",
            "title": "TEST-001 Title",
            "genres": [],
            "actors": [],
        },
        [],
        "TEST-001",
    )
    root = ET.fromstring(payload)

    assert root.findtext("title") == "TEST-001 Title"
    assert root.findtext("originaltitle") == "Title"
    assert root.find("year") is None
    assert root.find("runtime") is None
    assert root.find("set") is None
