"""核心逻辑单元测试：假网络/时钟 + 临时目录，不访问站点、不真的睡眠。"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location(
    "js", Path(__file__).with_name("javlibrarian.py"))
js = importlib.util.module_from_spec(spec)
spec.loader.exec_module(js)


class Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.text = "ok"
        self.content = b"ok"


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.headers = {}
        self.cookies = type("C", (), {"set": staticmethod(lambda *a, **k: None)})()

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else Resp(200)
        if isinstance(item, Exception):
            raise item
        return item


def make(script, **kw):
    """造一个 Fetcher，换掉网络层和时钟；返回 (fetcher, sleeps 记录)"""
    f = js.Fetcher(**kw)
    f.s = FakeSession(script)
    sleeps, clock = [], [1000.0]
    js.time.time = lambda: clock[0]
    js.time.monotonic = lambda: clock[0]      # _wait 用的是 monotonic
    def fake_sleep(s):
        sleeps.append(round(s, 2))
        clock[0] += s          # 时钟前进，_wait 就不会再额外睡
    js.time.sleep = fake_sleep
    return f, sleeps


PASS = FAIL = 0
def check(name, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  {'✅' if ok else '❌'} {name}")
    if not ok:
        print(f"      got      {got}\n      expected {want}")


print("[1] Repeated 429 responses until retries are exhausted")
f, sleeps = make([Resp(429)] * 5)
st, body = f.get("http://x.com/a")
check("backs off 10→20→40→80 only before another retry", sleeps, [10.0, 20.0, 40.0, 80.0])
check("returns the actual 429 status", (st, body), (429, None))
check("counts all five 429 responses", f.throttled, 5)
check("raises the base interval from 5.0 to the 30.0 cap", f._delay_of("x.com:html"), 30.0)
check("makes five requests", f.s.calls, 5)
before = list(sleeps)
f.get("http://y.com/a")
check("cooldown for host X does not block host Y", sleeps, before)
f.get("http://x.com/a")
check("the next request to X observes the final 160-second cooldown", sleeps, before + [160.0])

print("\n[2] Retry-After takes precedence over exponential backoff")
f, sleeps = make([Resp(429, {"Retry-After": "8"}), Resp(200)])
st, _ = f.get("http://x.com/a")
check("waits 8 seconds instead of 10", sleeps, [8.0])
check("succeeds after retry", st, 200)

print("\n[3] Backoff is capped at 300 seconds")
f, sleeps = make([Resp(429)] * 10)
f.get("http://x.com/a", max_retry=10)
check("the sequence caps at 300 and does not sleep after the final attempt", sleeps,
      [10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0, 300.0, 300.0])

print("\n[4] HTTP 503 retries and slows down; permanent 403 returns immediately")
f, sleeps = make([Resp(503), Resp(200)])
st, _ = f.get("http://x.com/a")
check("succeeds after retrying 503", st, 200)
check("the 429 counter remains zero", f.throttled, 0)
check("slows the base interval once from 5 to 7.5", f._delay_of("x.com:html"), 7.5)
f, sleeps = make([Resp(403), Resp(200)])
st, body = f.get("http://x.com/a")
check("returns the actual 403 status", (st, body), (403, None))
check("does not retry or wait after 403", (f.s.calls, sleeps), (1, []))

print("\n[5] Network exceptions use backoff and retry")
f, sleeps = make([js.requests.ConnectionError("boom"),
                  js.requests.Timeout("slow"), Resp(200)])
st, _ = f.get("http://x.com/a")
check("succeeds after network exceptions", st, 200)
check("backs off 10→20", sleeps, [10.0, 20.0])
check("network exceptions do not slow the base interval", f._delay_of("x.com:html"), 5.0)
f, _ = make([ValueError("programming error")])
raised = False
try:
    f.get("http://x.com/a")
except ValueError:
    raised = True
check("programming errors are not disguised as network retries", raised, True)

print("\n[6] HTTP 404 returns immediately without retry or backoff")
f, sleeps = make([Resp(404), Resp(200)])
st, body = f.get("http://x.com/a")
check("returns 404", (st, body), (404, None))
check("does not sleep", sleeps, [])
check("makes exactly one request", f.s.calls, 1)

print("\n[7] Image and HTML buckets are independent")
f, sleeps = make([Resp(429), Resp(200)])
f.get("http://x.com/a", binary=True)
check("raises the image bucket from 2.0 to 3.0", f._delay["x.com:img"], 3.0)
check("the HTML bucket for the same host is unchanged", f._delay_of("x.com:html"), 5.0)

print("\n[8] Retryable server errors return their actual status after retries")
f, sleeps = make([Resp(500)] * 5)
st, body = f.get("http://x.com/a")
check("returns (500, None)", (st, body), (500, None))
check("HTTP 500 does not slow the base interval", f._delay_of("x.com:html"), 5.0)

print("\n[9] Rate limiting on host A does not affect host B")
f, sleeps = make([Resp(429), Resp(200), Resp(200)])
f.get("https://javdb.com/v/x")          # JavDB 吃到一次 429
f.get("https://www.javbus.com/CODE")    # JavBus 不受影响
check("slows the javdb bucket from 5 to 7.5", f._delay_of("javdb.com:html"), 7.5)
check("leaves the javbus bucket at 5.0", f._delay_of("www.javbus.com:html"), 5.0)
check("builds bucket keys from host and resource type",
      js.Fetcher.bucket_of("https://pics.dmm.co.jp/a/b.jpg", True), "pics.dmm.co.jp:img")

print("\n[10] Online title scrapes wait 10 seconds; local skips do not reset the timer")
f, sleeps = make([])
f.begin_movie()
check("does not wait before the first title", sleeps, [])
f.finish_movie()
js.time.sleep(4)                 # 上一部结束后，本地处理/跳过项已经消耗 4 秒
sleeps.clear()
f.begin_movie()
check("waits only the remaining 6 seconds before the next title", sleeps, [6.0])
f.finish_movie()
js.time.sleep(3)
sleeps.clear()
f.finish_movie()                 # 模拟 SKIP 后主循环调用；inactive 时必须是空操作
js.time.sleep(2)
sleeps.clear()
f.begin_movie()
check("a local skip does not reset the timer, leaving a 5-second wait", sleeps, [5.0])

print("\n[11] Permanent HTTP 400 returns immediately")
f, sleeps = make([Resp(400), Resp(200)])
st, body = f.get("http://x.com/a")
check("returns the actual 400 status", (st, body), (400, None))
check("does not retry or back off after 400", (f.s.calls, sleeps), (1, []))

print("\n[12] A fallback source supplies samples when the primary has none")
merged = js.merge_sources(
    {"source": "javbus", "code": "TEST-001", "title": "Title",
     "genres": [], "actors": [], "samples": []},
    {"source": "javdb", "code": "TEST-001", "title": "Title",
     "genres": [], "actors": [], "samples": ["https://img.test/sample1.jpg"]})
check("promotes fallback images to downloadable samples",
      merged.get("samples"), ["https://img.test/sample1.jpg"])
check("does not create unreachable samples_alt without primary samples",
      "samples_alt" in merged, False)

print("\n[13] Invalid images do not damage an existing target")
with tempfile.TemporaryDirectory() as td:
    dst = Path(td) / "fanart.jpg"
    original = b"existing-valid-image"
    replacement = b"x" * 2048
    dst.write_bytes(original)

    class ImageFetcher:
        def get(self, *args, **kwargs):
            return 200, replacement

    old_size = js.sips_size
    try:
        js.sips_size = lambda path: (None, None)
        result = js.download(ImageFetcher(), "https://img.test/a.jpg", dst, min_edge=200)
        check("preserves the old image when validation fails",
              (result, dst.read_bytes()), (False, original))
        check("removes the temporary image after failed validation",
              list(Path(td).glob(".fanart.*.tmp.jpg")), [])

        js.sips_size = lambda path: (800, 600)
        result = js.download(ImageFetcher(), "https://img.test/a.jpg", dst, min_edge=200)
        check("replaces the target after successful validation",
              (result, dst.read_bytes()), (True, replacement))
    finally:
        js.sips_size = old_size

print("\n[14] movie.nfo is committed only after the full title workflow")
with tempfile.TemporaryDirectory() as td:
    folder = Path(td) / "TEST-001"
    folder.mkdir()
    video = folder / "TEST-001.mp4"
    video.write_bytes(b"")
    old_bus = js.fetch_javbus
    old_db = js.fetch_javdb
    old_download = js.download_with_alt

    class MovieFetcher:
        def begin_movie(self):
            pass

    args = SimpleNamespace(force=False, no_images=False, max_samples=0)
    js.fetch_javbus = lambda fetcher, code: {
        "source": "javbus", "code": code, "dvdid": code, "title": "Title",
        "genres": [], "actors": [], "samples": [],
        "cover": "https://img.test/fanart.jpg"}
    js.fetch_javdb = lambda fetcher, code: None
    try:
        js.download_with_alt = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("image failure"))
        raised = False
        try:
            js.scrape_one(folder, MovieFetcher(), args)
        except RuntimeError:
            raised = True
        check("propagates an image-stage exception", raised, True)
        check("does not leave a completion marker after failure",
              (folder / "movie.nfo").exists(), False)
        check("does not write the video-side NFO early",
              video.with_suffix(".nfo").exists(), False)

        js.download_with_alt = lambda *a, **k: False
        status, _ = js.scrape_one(folder, MovieFetcher(), args)
        check("writes every NFO only after the workflow completes",
              (status, (folder / "movie.nfo").exists(), video.with_suffix(".nfo").exists()),
              ("OK", True, True))
    finally:
        js.fetch_javbus = old_bus
        js.fetch_javdb = old_db
        js.download_with_alt = old_download

print("\n[15] Rollback journals handle failures conservatively")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "library"
    root.mkdir()
    (root / "DONE").mkdir()
    log_path = Path(td) / "folder_rename_log.json"
    payload = {
        "root": str(root.resolve()),
        "batches": [{"time": "test", "entries": [
            {"old": "OLD1", "new": "DONE"},
            {"old": "OLD2", "new": "MISSING"}]}]}
    log_path.write_text(json.dumps(payload), encoding="utf-8")
    js.do_undo_folders(root, log_path)
    kept = json.loads(log_path.read_text(encoding="utf-8"))
    check("retains only unresolved entries after partial success",
          (len(kept["batches"]), kept["batches"][0]["entries"], (root / "OLD1").exists()),
          (1, [{"old": "OLD2", "new": "MISSING"}], True))
    (root / "MISSING").mkdir()
    js.do_undo_folders(root, log_path)
    check("clears the batch after its unresolved entry is handled",
          ((root / "OLD2").exists(), log_path.exists()), (True, False))

    bad_log = Path(td) / "bad.json"
    bad_log.write_text("{", encoding="utf-8")
    rejected = False
    try:
        js.RenameLog(bad_log, root)
    except SystemExit:
        rejected = True
    check("does not silently reset a corrupt journal", rejected, True)

    foreign_root = Path(td) / "foreign"
    foreign_root.mkdir()
    mixed_log = Path(td) / "mixed.json"
    mixed_log.write_text(json.dumps({
        "root": str(foreign_root.resolve()),
        "batches": [{"time": "old", "entries": [{"old": "A", "new": "B"}]}]}),
        encoding="utf-8")
    folder = root / "abc-001"
    folder.mkdir()
    rejected = False
    try:
        js.do_rename_folders([folder], mixed_log, apply=True)
    except SystemExit:
        rejected = True
    check("rejects a journal from a different media root",
          (rejected, folder.exists()), (True, True))

    unwritable_log = Path(td) / "missing" / "rename.json"
    stopped = False
    try:
        js.do_rename_folders([folder], unwritable_log, apply=True)
    except OSError:
        stopped = True
    check("does not rename when the journal pre-write fails",
          (stopped, folder.exists()), (True, True))

print("\n[16] The sips check does not block local skips")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    folder = root / "TEST-001"
    folder.mkdir()
    old_argv = sys.argv
    old_which = js.shutil.which
    js.shutil.which = lambda name: None
    try:
        sys.argv = ["javlibrarian.py", "--dir", str(root)]
        message = ""
        try:
            js.main()
        except SystemExit as e:
            message = str(e)
        check("clearly reports missing sips when image work is required",
              "sips" in message, True)

        (folder / "movie.nfo").write_bytes(b"<movie/>")
        sys.argv = ["javlibrarian.py", "--dir", str(root)]
        exited = False
        try:
            js.main()
        except SystemExit:
            exited = True
        check("does not block an existing movie.nfo on the sips check", exited, False)
    finally:
        sys.argv = old_argv
        js.shutil.which = old_which

print(f"\n{'─'*46}\nPassed {PASS} / Failed {FAIL}")
raise SystemExit(1 if FAIL else 0)
