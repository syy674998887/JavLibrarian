from javlibrarian.sources import (
    fetch_javdb,
    javdb_find,
    merge_sources,
    parse_javbus,
)


class ScriptedFetcher:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_javbus_parser_extracts_fields_and_validates_catalog_number():
    page = """
    <h3>TEST-001 日本語タイトル</h3>
    <a class="bigImage" href="/pics/cover.jpg"></a>
    <div class="col-md-3 info">
      <span class="header">識別碼:</span> TEST-001
      <span class="header">發行日期:</span> 2024-02-03
      <span class="header">製作商:</span> Maker
      <span class="header">發行商:</span> Label
      <span class="header">系列:</span> Series
      <span class="header">導演:</span> Director
      <span class="header">長度:</span> 123分鐘
      <span class="genre"><a href="/genre/a">VR</a></span>
    </div>
    <a class="avatar-box" href="/star/a">
      <div class="photo-frame"><img src="/actress.jpg"></div><span>演員名</span>
    </a>
    <a class="sample-box" href="https://img.test/sample.jpg"></a>
    """

    data = parse_javbus(page, "TEST-001")

    assert data == {
        "source": "javbus",
        "code": "TEST-001",
        "title": "TEST-001 日本語タイトル",
        "cover": "https://www.javbus.com/pics/cover.jpg",
        "dvdid": "TEST-001",
        "release": "2024-02-03",
        "studio": "Maker",
        "label": "Label",
        "series": "Series",
        "director": "Director",
        "runtime": 123,
        "genres": ["VR"],
        "actors": [
            {"name": "演員名", "thumb": "https://www.javbus.com/actress.jpg"}
        ],
        "samples": ["https://img.test/sample.jpg"],
    }
    assert parse_javbus(page.replace("TEST-001\n", "TEST-002\n", 1), "TEST-001") is None


def test_javdb_search_selects_exact_equivalent_catalog_number():
    search = """
    <a href="/v/wrong"><strong>TEST-002</strong></a>
    <a href="/v/right"><strong>test_0001</strong></a>
    """
    fetcher = ScriptedFetcher([(200, search)])

    assert javdb_find(fetcher, "TEST-001") == "/v/right"
    assert fetcher.urls == ["https://javdb.com/search?q=TEST-001&f=all"]


def test_javdb_fetch_parses_detail_page():
    search = '<a href="/v/right"><strong>TEST-001</strong></a>'
    detail = """
    <h2 class="title is-4"><strong>TEST-001</strong><strong>中文标题</strong></h2>
    <div><strong>日期:</strong>2024-02-03</div>
    <div><strong>片商:</strong><a>Maker</a></div>
    <div><strong>發行:</strong>Label</div>
    <div><strong>系列:</strong>Series</div>
    <div><strong>導演:</strong>Director</div>
    <div><strong>時長:</strong>123 分鐘</div>
    <div><strong>類別:</strong>VR, 劇情, VR</div>
    <div><strong>演員:</strong><a>女優</a><strong>♀</strong><a>男優</a><strong>♂</strong></div>
    <img src="https://c1.jdbstatic.com/covers/cover.jpg">
    <a href="https://c1.jdbstatic.com/samples/key_l_2.jpg"></a>
    <a href="https://c1.jdbstatic.com/samples/key_l_1.jpg"></a>
    """
    fetcher = ScriptedFetcher([(200, search), (200, detail)])

    data = fetch_javdb(fetcher, "TEST-001")

    assert data["dvdid"] == "TEST-001"
    assert data["title"] == "中文标题"
    assert data["runtime"] == 123
    assert data["genres"] == ["VR", "劇情", "VR"]
    assert data["actors"] == [{"name": "女優", "thumb": ""}]
    assert data["cover"] == "https://c1.jdbstatic.com/covers/cover.jpg"
    assert data["samples"] == [
        "https://c1.jdbstatic.com/samples/key_l_1.jpg",
        "https://c1.jdbstatic.com/samples/key_l_2.jpg",
    ]
    assert fetcher.urls[-1] == "https://javdb.com/v/right?locale=zh"


def test_source_merge_promotes_fallback_samples_when_primary_has_none():
    merged = merge_sources(
        {
            "source": "javbus",
            "code": "TEST-001",
            "title": "Title",
            "genres": [],
            "actors": [],
            "samples": [],
        },
        {
            "source": "javdb",
            "code": "TEST-001",
            "title": "Title",
            "genres": [],
            "actors": [],
            "samples": ["https://img.test/sample1.jpg"],
        },
    )

    assert merged["samples"] == ["https://img.test/sample1.jpg"]
    assert "samples_alt" not in merged


def test_source_merge_policy_preserves_primary_and_enriches_missing_fields():
    bus = {
        "source": "javbus",
        "code": "TEST-001",
        "title": "日本語タイトル",
        "studio": "Primary Studio",
        "series": None,
        "genres": ["A"],
        "actors": [{"name": "发行时艺名", "thumb": "x"}],
        "cover": "bus-cover",
        "samples": ["bus-sample"],
    }
    db = {
        "source": "javdb",
        "code": "TEST-001",
        "title": "中文标题",
        "studio": "Secondary Studio",
        "series": "Series",
        "genres": ["A", "B", "B"],
        "actors": [{"name": "现艺名", "thumb": ""}],
        "cover": "db-cover",
        "samples": ["db-sample"],
    }

    merged = merge_sources(bus, db)

    assert merged["title_cn"] == "中文标题"
    assert merged["studio"] == "Primary Studio"
    assert merged["series"] == "Series"
    assert merged["genres"] == ["A", "B"]
    assert merged["actors"] == bus["actors"]
    assert merged["cover_alt"] == "db-cover"
    assert merged["samples_alt"] == ["db-sample"]
    assert bus.get("title_cn") is None


def test_source_merge_handles_single_source():
    bus = {"source": "javbus"}
    db = {"source": "javdb"}

    assert merge_sources(bus, None) == bus
    assert merge_sources(None, db) is db
    assert merge_sources(None, None) is None
