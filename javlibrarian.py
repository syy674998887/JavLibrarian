#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JavLibrarian
============
轻量的 JAV NAS 媒体库建设工具：扫描番号文件夹，整理命名、抓取元数据并生成媒体库结构。

主目标是绿联 UGOS 影视中心（按「视频文件名同名 nfo」规则生成，
需在媒体库设置里勾选「优先读取本地信息」）；
同时输出 movie.nfo 以兼容 Emby / Jellyfin / Kodi 的文件夹级读取。

设计原则
--------
1. 只新增文件，绝不删除、绝不触碰视频内容（改名是独立的显式命令）
2. Python 仅声明 requests 这一项直接依赖；图片处理使用 macOS 自带 sips
3. 番号清洗只在内存中进行，-C / -U / -UC 后缀转成中文标签写入 NFO
4. 本地推算的番号必须经页面 識別碼 反向校验才采信
5. 串行请求 + 保守限流，宁可慢也不要被封；不做元数据缓存，每次实抓
   （已有 movie.nfo 就整片跳过，缓存省不下几次请求，却会在字段口径
   改动后悄悄喂旧数据）
6. 海报分两条路：普通片一律从横版封面右侧裁 47.5%；VR 片先去剧照里
   找独立的竖版封面，找不到才裁。普通片不走剧照那条 —— 它们的剧照里
   也有竖版图，但那是竖着拍的场景照（比例 0.667），不是封面（0.735）

数据源（双源并跑，不是回退）
------
  JavBus  https://www.javbus.com/{番号}     骨架
  JavDB   https://javdb.com/search → /v/…  补强（需搜索页 + 详情页两次请求，
                                           搜索是模糊的，必须按番号精确校验）

两站都抓，按各自强项合并（merge_sources）。10 部抽样的分工依据：
  JavBus 强 —— 發行商 10/10 vs 2/10、类别 85 个 vs 70 个、演员头像 12 个 vs 0，
               封面比例稳定（JavDB 有时索引蓝光版，800×438 而非 800×538，
               拿去按 DVD 比例裁海报会裁错）
  JavDB 强 —— 部分片有繁中译名标题、系列偶尔更全，以及 JavBus 那边失效的图
               它可能还在（CJOD-149 的剧照在 DMM 全成占位图，JavDB 侧完好）

语言：类别两站都是繁中。标题 JavBus 恒为日文，JavDB 对少数片有繁中译名 ——
全库 91 部里只有 7 部（普通片 5/31 = 16%，VR 片 2/60 = 3%，VR 基本没人译），
有中文就用中文，日文原名始终保留在 originaltitle。
演员名两站都是日文，差别在 JavBus 用发行时的艺名、JavDB 用现艺名
（楓カレン→田中レモン、橋本ありな→新ありな）。只写 JavBus 的发行时
艺名 —— 和这部片封面、标题上印的一致；现艺名不写。
JavDB 的 locale=zh-CN 与 zh 输出一字不差，只是界面文案，切了没用。

实测 91 个番号：88 个双源命中，3 个只有 JavDB（DSVR-1273、REBDB-1006、
SS-027 在 JavBus 是 404），零未命中。合并后类别从平均 8.5 个升到 11.6 个。

限流策略
--------
计时桶按「主机 + 类型」划分，默认间隔 详情页 5.0s / 图片 2.0s。限流是各站
自己算的，分主机后 JavDB 被限流不会连累 JavBus，双源的请求也不必排队等
同一个间隔。两部实际联网刮削的影片之间另留 10.0s；首次不等、末次不空等，
纯本地跳过项不重置片间计时。一旦某桶吃到 429，除了指数退避（10s 起，翻倍，
封顶 300s），还会把该桶的基础间隔 ×1.5 永久调高（封顶 30s，本次运行内
不恢复）——被限流说明当前节奏已经过快，退避完再按原速冲回去只会再被限一次。
503 常是服务端过载或变相限流，同样触发减速；其他永久性 4xx 不自动重试。

实测：91 个番号双源连续跑 12.1 分钟（JavBus 91 次 + JavDB 182 次请求），
两站双双零 429、零 403、零重试、零减速。核心路径另有离线单元测试
（test_throttle.py，使用假 Session、假时钟与系统临时目录，不打真实站点）。

产物结构
--------
  番号文件夹/
    movie.nfo          文件夹级，Emby / Jellyfin / Kodi 读
    {视频名}.nfo        同名，绿联 UGOS 读（它不认 movie.nfo）
    fanart.jpg         横版封面，详情页背景
    poster.jpg         竖版海报，海报墙显示的就是它
    Samples/           剧照，默认全部下载（对应页面上的「樣品圖像」）
      sample1.jpg …

图片一律 JavBus 优先，失效（含 DMM 占位图）时自动换 JavDB 同位置那张 ——
两站的图失效是互补的，CJOD-149 靠这个从 0 张剧照变成 10 张。

用法（uv 项目，依赖由 pyproject.toml + uv.lock 管理）
----
  uv sync                                      # 首次/换机器：按 lock 装依赖
  export JAVLIBRARIAN_DIR="/path/to/JAV"          # 可选：设置默认媒体目录
  uv run javlibrarian.py --dir "/path/to/JAV"     # 也可每次通过参数指定目录
  uv run javlibrarian.py --dry-run               # 只看番号解析，不联网不写盘
  uv run javlibrarian.py --limit 5               # 试跑前 5 个
  uv run javlibrarian.py                         # 全量刮削
  uv run javlibrarian.py --only SONE-035-C       # 只处理指定文件夹
  uv run javlibrarian.py --force                 # 覆盖已有 NFO
  uv run javlibrarian.py --rename-folders        # 预览文件夹改名；确认后加 --apply
  uv run javlibrarian.py --rename-videos         # 预览视频文件改名；确认后加 --apply
  uv run javlibrarian.py --undo-folders          # 回滚最近一次文件夹改名
  uv run javlibrarian.py --undo-videos           # 回滚最近一次视频文件改名

注意：本文件不带 PEP 723 内联元数据。若加上，uv run 会切到脚本临时环境
      而绕开项目 .venv，导致 pyproject.toml / uv.lock 形同虚设。
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    sys.exit("Missing requests. This project manages dependencies with uv. Run:  uv sync\n"
             "Then use uv run javlibrarian.py ... instead of invoking python3 directly.")


# ══════════════════════════════════════════════════════════════════
#  配置
# ══════════════════════════════════════════════════════════════════

DIR_ENV = "JAVLIBRARIAN_DIR"

# 请求节奏默认值。命令行可以覆盖，但 Fetcher 与 CLI 共用同一份常量，避免口径漂移。
DEFAULT_HTML_DELAY  = 5.0
DEFAULT_IMG_DELAY   = 2.0
DEFAULT_MOVIE_DELAY = 10.0

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

JAVBUS = "https://www.javbus.com"
JAVDB = "https://javdb.com"

# 海报裁剪：正面封面占横版封面宽度的比例。
# 依据实体盒型：DVD 封套摊平 = 封底 135mm + 书脊 14mm + 正面 135mm = 284mm，
# 正面占 135/284 = 47.5%。实测把官方竖版 ps.jpg 在 pl.jpg 上滑窗匹配
# （CJOD-149 / IPZZ-778 / SONE-035），三部全部精准落在右对齐位置，与此吻合。
# 按宽度取比例而不是按高度：裁出来只跟盒型有关，不受源图高度影响。
POSTER_WIDTH_RATIO = 0.475

# VR 片的竖版封面不在横版封面里 —— 实测横版任意位置与竖版的 RMSE 都在 72~87（完全不像），
# 而剧照里那张 588×800 竖版图 RMSE 只有 13~35（几乎同一张）。两者是分别设计的独立宣传图。
# 所以 VR 走「从剧照里挑封面」，普通片走「从横版裁剪」。
PS_MATCH_HEIGHT   = 100      # 比对时把候选图和基准图统一缩放到的高度
# 超过此值视为剧照里没有竖版封面。取 60 是因为实测两类样本之间有一条干净空档：
#   确实是封面 —— 12 / 13.8 / 15 / 16 / 17 / 19.6 / 22 / 24 / 33.7 / 35 / 36 / 50.3
#   确实没有   —— 70 / 74.3 / 75 / 80 / 83 / 88.4 / 88.9 / 90 / 97 / 101.9
# 原值 50 卡在空档下沿，FSVSS-004 的封面 50.29 被误拒（同系列 FSVSS-003 是 36）。
PS_MATCH_MAX_RMSE = 60.0
PS_MIN_STDDEV     = 30.0     # 基准图灰度标准差下限，低于此值判为占位图（见下）
MIN_IMAGE_EDGE    = 200      # 短边小于此值判为 DMM 占位图（缺图时返回 90×122，2732 字节）

# 剧照存放目录。对应 JavBus 页面上的「樣品圖像」。
# 注意：改成非 extrafanart 的名字后，Emby / Jellyfin / Kodi 不再把这些图当轮播背景，
# 只是普通文件；封面 fanart.jpg 和海报 poster.jpg 不受影响。
SAMPLES_DIR = "Samples"

# DMM contentId：从剧照链接反推，用于拼出官方竖版 ps.jpg 的地址。
# 两个图床都要认：pics.dmm.co.jp/digital/video/{cid}/ 和
# awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/（SAVR-1062 这类走的是后者）
DMM_CID = re.compile(r'dmm\.co\.jp/(?:pics_dig/)?(?:digital/video|mono/movie/adult)/([^/]+)/')

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".wmv", ".mov", ".m4v", ".ts", ".iso", ".rmvb", ".flv"}


def atomic_write_bytes(path, data):
    """同目录写临时文件后原子替换，避免留下半写入的完成标记或日志。"""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════
#  番号归一化
# ══════════════════════════════════════════════════════════════════

# 站点污染前缀：hhd800.com@ / www.98T.la@ / 489155.com@ / jav20.com-
SITE_PREFIX = re.compile(r'^\s*(?:[\w.-]+\.(?:com|me|net|la|cc|xyz|top|org|tv|info)[@\-])+', re.I)

# 开头方括号：[168x.me] / [LD-024] / [JavBus.com]
LEAD_BRACKET = re.compile(r'^\s*[\[\(]([^\]\)]*)[\]\)]\s*')

# DMM contentId 形式（字母紧跟补零数字，无分隔符）：ipvr00256 / vrkm01422 / savr00509
CONTENT_ID = re.compile(r'^([a-z]{2,7})(\d{4,6})$', re.I)

# 标准番号（带分隔符）：SSIS-001 / TSDS-42376 / REBDB-1006
STD_ID = re.compile(r'^([A-Za-z]{2,7})[-_](\d{2,6})$')

# 宽松搜索
ANY_ID = re.compile(r'([A-Za-z]{2,7})[-_](\d{2,6})')

# FC2 专用
FC2 = re.compile(r'FC2[-_]?(?:PPV[-_]?)?(\d{5,8})', re.I)

# 后缀语义标记 —— 保留含义，写入 NFO 标签（顺序敏感：先长后短）
TAG_RULES = [
    (re.compile(r'-UC(?![A-Za-z0-9])', re.I),         ["无码破解", "中文字幕"]),
    (re.compile(r'-uncensored(?![A-Za-z])', re.I),    ["无码破解"]),
    (re.compile(r'-leak(?![A-Za-z])', re.I),          ["无码流出"]),
    (re.compile(r'-U(?![A-Za-z0-9])', re.I),          ["无码破解"]),
    (re.compile(r'-C(?![A-Za-z0-9])', re.I),          ["中文字幕"]),
]

# 需要剥离的噪声（仅用于查询，不改文件名）—— 顺序敏感
JUNK_PATTERNS = [
    r'\.?\[4K\]@R',            # SONE-267.[4K]@R
    r'\[MP4_[^\]]*\]',         # [MP4_3.38GB]
    r'\[\d{3,4}[pP]\]',        # [1080p]
    r'-Rife(?![A-Za-z])',      # -Rife（AI 补帧）
    r'-4k(?![A-Za-z])',        # -4k
    r'-8k(?![A-Za-z])',
    r'-UC(?![A-Za-z0-9])',     # 标记已提取，此处剥离
    r'-uncensored(?![A-Za-z])',
    r'-leak(?![A-Za-z])',
    r'-U(?![A-Za-z0-9])',
    r'-C(?![A-Za-z0-9])',
    r'-cd\d+(?![0-9])',        # -cd1 / -CD2
    r'-[A-F](?![A-Za-z0-9])',  # -A / -B 分卷（实测为文件夹取名残留）
    r'-\d(?![0-9])',           # -1 / -2 单数字分卷
]


def normalize(folder_name):
    """
    文件夹名 → (查询番号, [中文标签])
    原始文件夹名不做任何修改，本函数结果仅用于查询与写 NFO。
    """
    tags = []
    for pat, tg in TAG_RULES:
        if pat.search(folder_name):
            tags = list(tg)
            break

    # FC2 单独处理
    m = FC2.search(folder_name)
    if m:
        return f"FC2-PPV-{m.group(1)}", tags

    s = folder_name.strip()

    # 开头方括号里若直接是番号，优先采信（[LD-024] / [SS-027] / [MBRBN-005]）
    mb = LEAD_BRACKET.match(s)
    if mb:
        inner = mb.group(1).strip()
        mi = STD_ID.match(inner) or ANY_ID.search(inner)
        if mi:
            # 保留原始位数，绝不能把 LD-024 变成 LD-24
            return f"{mi.group(1).upper()}-{mi.group(2)}", tags
        s = LEAD_BRACKET.sub('', s).strip()

    # 剥离站点前缀 + 残余方括号
    s = SITE_PREFIX.sub('', s).strip()
    s = re.sub(r'^\[[^\]]*\]\s*', '', s).strip()

    # 取第一个空白分隔的 token（处理 "SIVR-315 8K Konan Koyoi"）
    parts = re.split(r'[\s　]+', s)
    core = parts[0] if parts else s

    # 反复剥离噪声后缀
    prev = None
    while prev != core:
        prev = core
        for j in JUNK_PATTERNS:
            core = re.sub(j, '', core, flags=re.I)
    core = core.strip(' -_.')

    # DMM contentId：去前导零 (ipvr00256 → IPVR-256, vrkm01422 → VRKM-1422)
    m = CONTENT_ID.match(core)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2))}", tags

    # 标准番号：保留原始位数 (SONE-035 保持 035)
    m = STD_ID.match(core)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}", tags

    m = ANY_ID.search(core)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}", tags

    return None, tags


# ══════════════════════════════════════════════════════════════════
#  改名映射表（回滚依据）
# ══════════════════════════════════════════════════════════════════

class RenameLog:
    """
    改名映射表。三条设计要点，都是为了让回滚真的靠得住：

    1. 每成功改一个就立刻落盘。改到一半崩溃/断网/Ctrl-C 时，
       已完成的部分仍可回滚（旧实现是全部跑完才写盘，中断即永久丢失还原能力）。
    2. 记录 root 目录。回滚时校验，防止拿别的目录（或测试残留）的映射表误伤实盘。
    3. 按批次分组。默认只回滚最近一次，而不是把历史几次改名一起退掉。
    """

    def __init__(self, path, root):
        self.path = Path(path)
        self.root = str(Path(root).resolve())
        self.data = {"root": self.root, "batches": []}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as e:
                sys.exit(f"Unable to read rename journal; stopped to avoid overwriting "
                         f"rollback history: {self.path}\n{e}")
            if not isinstance(loaded, dict) or not isinstance(loaded.get("batches"), list):
                sys.exit(f"Invalid rename journal format; stopped to avoid overwriting "
                         f"rollback history: {self.path}")
            self.data = loaded
        self.batch = None

    def root_matches(self):
        return self.data.get("root") == self.root

    def open_batch(self):
        self.batch = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "entries": []}
        self.data["root"] = self.root
        self.data["batches"].append(self.batch)

    def add(self, entry):
        if self.batch is None:
            self.open_batch()
        self.batch["entries"].append(entry)
        self.flush()                      # ← 关键：每条立即落盘

    def flush(self):
        try:
            payload = json.dumps(self.data, ensure_ascii=False, indent=1).encode("utf-8")
            atomic_write_bytes(self.path, payload)
        except OSError as e:
            raise OSError(f"Unable to write rename journal; operation stopped: "
                          f"{self.path}: {e}") from e

    def batches(self):
        return self.data.get("batches", [])

    def drop_batch(self, idx):
        try:
            del self.data["batches"][idx]
        except Exception:
            return
        if self.data["batches"]:
            self.flush()
        elif self.path.exists():
            self.path.unlink()


def load_log_for_undo(path, root, want_all):
    """读取映射表并做安全校验，返回 (RenameLog, 待回滚批次索引列表)"""
    lp = Path(path)
    if not lp.exists():
        sys.exit(f"Rename journal not found: {path}")
    log = RenameLog(path, root)
    if not log.batches():
        sys.exit("Rename journal is empty; nothing to undo.")
    if not log.root_matches():
        sys.exit(
            f"Rename journal root does not match; stopped to protect the wrong library:\n"
            f"  Journal root : {log.data.get('root')}\n"
            f"  Selected root: {log.root}\n"
            f"Point --dir to the root recorded in the journal to undo that library.")
    idxs = list(range(len(log.batches()))) if want_all else [len(log.batches()) - 1]
    return log, idxs


# ══════════════════════════════════════════════════════════════════
#  文件夹命名标准化
# ══════════════════════════════════════════════════════════════════

# 标签 → 规范后缀（-C / -U / -UC 语义保留）
SUFFIX_MAP = {
    ("无码破解", "中文字幕"): "-UC",
    ("无码破解",):            "-U",
    ("无码流出",):            "-U",
    ("中文字幕",):            "-C",
}


def standard_name(folder_name):
    """文件夹名 → 规范名（大写番号 + 保留的语义后缀）；无法识别返回 None"""
    code, tags = normalize(folder_name)
    if not code:
        return None
    return f"{code}{SUFFIX_MAP.get(tuple(tags), '')}"


def plan_renames(folders):
    """
    返回 (计划列表, 冲突字典)
    计划项: (Path, 新名, 类型)  类型 ∈ {'same','case','real'}
    """
    plan = []
    targets = {}
    for f in folders:
        new = standard_name(f.name)
        if not new:
            continue
        if new == f.name:
            kind = "same"
        elif new.lower() == f.name.lower():
            kind = "case"          # 仅大小写：不区分大小写的文件系统需两步 mv
        else:
            kind = "real"
        plan.append((f, new, kind))
        targets.setdefault(new.lower(), []).append(f.name)

    collisions = {k: v for k, v in targets.items() if len(v) > 1}
    return plan, collisions


def rename_folder(folder, new_name):
    """
    执行改名。macOS/SMB 上文件系统常不区分大小写，
    仅大小写变化必须经临时名中转，否则 rename 会静默无效或报错。
    返回 (成功?, 消息)
    """
    parent = folder.parent
    target = parent / new_name

    if folder.name == new_name:
        return True, "Already normalized"

    case_only = folder.name.lower() == new_name.lower()

    # 目标已存在且不是自身 → 冲突，绝不覆盖
    if target.exists() and not case_only:
        return False, f"Target already exists; skipped: {new_name}"

    def landed():
        """确认目标名真的以正确大小写落盘（不区分大小写的 FS 上 exists() 不可信）"""
        try:
            return new_name in {p.name for p in parent.iterdir()}
        except Exception:
            return False

    # 先试单步——实测本机 SMB 支持，中断风险最小。
    # 改成不同名字时 rename 不抛异常即成功（POSIX 语义），无需再列目录校验；
    # 只有仅改大小写时，不区分大小写的文件系统可能静默无效，才需要 landed()。
    try:
        folder.rename(target)
        if not case_only or landed():
            return True, new_name
    except Exception as e:
        if not case_only:
            return False, f"{type(e).__name__}: {e}"

    # 单步无效（不区分大小写的文件系统）→ 临时名中转
    if case_only:
        try:
            src = target if target.exists() else folder
            tmp = parent / f"__casetmp__{new_name}"
            n = 0
            while tmp.exists():
                n += 1
                tmp = parent / f"__casetmp{n}__{new_name}"
            src.rename(tmp)
            tmp.rename(parent / new_name)
            return (True, new_name) if landed() else (False, "Rename verification failed")
        except Exception as e:
            return False, f"Two-step rename failed: {type(e).__name__}: {e}"

    return False, "Rename verification failed"


def do_rename_folders(folders, log_path, apply=False):
    plan, collisions = plan_renames(folders)

    same = [p for p in plan if p[2] == "same"]
    case = [p for p in plan if p[2] == "case"]
    real = [p for p in plan if p[2] == "real"]
    unknown = len(folders) - len(plan)

    print(f"\nFolders             : {len(folders)}")
    print(f"  Already normalized: {len(same)}")
    print(f"  Case-only changes : {len(case)}   (requires two-step mv)")
    print(f"  Renames           : {len(real)}")
    if unknown:
        print(f"  Unrecognized IDs  : {unknown}   (unchanged)")

    if collisions:
        print(f"\n⚠️  Found {len(collisions)} naming conflict group(s); "
              "all affected folders will be skipped:")
        for tgt, srcs in collisions.items():
            print(f"    [{tgt}] ← {srcs}")
    else:
        print("\n✅ No naming conflicts")

    if real:
        print("\n─── Renames ───")
        for f, new, _ in real:
            print(f"  {f.name[:52]:<54} → {new}")
    if case:
        print("\n─── Case-only changes ───")
        for f, new, _ in case:
            print(f"  {f.name:<24} → {new}")

    if not apply:
        print("\n[Preview] No changes made. Review the plan, then add --apply.")
        return

    # ---- 真正执行 ----
    collide_names = {s for v in collisions.values() for s in v}
    root = folders[0].parent if folders else Path(".")
    log = RenameLog(log_path, root)
    if log.batches() and not log.root_matches():
        sys.exit(
            f"Rename journal belongs to another media root; stopped to avoid mixing batches:\n"
            f"  Journal root : {log.data.get('root')}\n"
            f"  Selected root: {log.root}\n"
            "Use --folder-log to select a different journal.")
    log.open_batch()
    log.flush()                         # 先确认日志可写，再开始改名
    ok = skip = fail = 0
    print("\n─── Applying changes ───")
    for f, new, kind in plan:
        if kind == "same":
            continue
        if f.name in collide_names:
            print(f"  ⏭  {f.name}  (conflict; skipped)")
            skip += 1
            continue
        good, msg = rename_folder(f, new)
        if good:
            log.add({"old": f.name, "new": new})     # 每条立即落盘
            ok += 1
            print(f"  ✅ {f.name[:50]:<52} → {new}")
        else:
            fail += 1
            print(f"  ❌ {f.name[:50]:<52} {msg}")

    if not ok:
        log.drop_batch(-1)

    print(f"\nFolder rename complete: succeeded {ok}  skipped {skip}  failed {fail}")
    if ok:
        print(f"Journal saved: {log_path}")
        print("To undo:  uv run javlibrarian.py --undo-folders --dir \"<media-root>\"")


def _undo_entries(root, entries, rename_fn, label):
    """倒序回滚一批记录。倒序是为了避开 A→B、B→C 这类改名链的名字占用冲突。"""
    ok = fail = skip = 0
    remaining = []
    for item in reversed(entries):
        good, msg = rename_fn(root, item)
        if good is None:
            skip += 1
            remaining.append(item)
            print(f"  ⏭  {item['new']} does not exist; skipped")
        elif good:
            ok += 1
            print(f"  ↩️  {item['new'][:44]:<46} → {item['old']}")
        else:
            fail += 1
            remaining.append(item)
            print(f"  ❌ {item['new'][:44]:<46} {msg}")
    print(f"\n{label} rollback complete: succeeded {ok}  skipped {skip}  failed {fail}")
    return ok, skip, fail, list(reversed(remaining))


def do_undo_folders(root, log_path, want_all=False):
    log, idxs = load_log_for_undo(log_path, root, want_all)
    batches = log.batches()
    total = sum(len(batches[i]["entries"]) for i in idxs)
    print(f"Journal batches: {len(batches)}; rollback selection: "
          f"{len(idxs)} batch(es) / {total} entries "
          f"{'(all)' if want_all else '(latest only)'}")

    def do_one(root_path, item):
        cur = Path(root_path) / item["new"]
        if not cur.is_dir():
            return None, ""
        return rename_folder(cur, item["old"])

    all_ok = True
    for i in sorted(idxs, reverse=True):
        b = batches[i]
        print(f"\n── Batch {i + 1}/{len(batches)}  {b.get('time', '')}")
        ok, skip, fail, remaining = _undo_entries(root, b["entries"], do_one, "Folder")
        if remaining:
            if ok:
                b["entries"] = remaining
                log.flush()
            all_ok = False
        else:
            log.drop_batch(i)
    if all_ok:
        print("Rolled-back batch records were removed from the journal.")
    else:
        print("Skipped or failed entries remain in the journal; resolve them and retry.")


# ══════════════════════════════════════════════════════════════════
#  视频文件名清理
# ══════════════════════════════════════════════════════════════════

# 视频文件名里的站点污染：4k2.com@ / hhd800.com@ / [activehlj.com]@ / 489155.com@
VID_SITE = re.compile(r'^(?:\[[^\]]*\]@?|[\w.-]+\.(?:com|me|net|la|cc|xyz|top|tv|info)@)+', re.I)

# 分卷序号可能出现在中间或末尾，按优先级匹配
VOL_PATTERNS = [
    (r'^(.*?)[-_\s](\d{1,2})[-_](?:\d+k|8k|4k)$', "num"),    # mdvr00341_1_8k
    (r'^(.*?)[-_\s]([A-Fa-f])(?:[-_].*)?$',       "alpha"),  # SAVR-393_A / SIVR-032-A-2x-RIFE
    (r'^(.*?)[-_\s](\d{1,2})$',                   "num"),    # SIVR-030 1 / ipvr00256-1
    (r'^(.*?[a-z])(\d{1,2})$',                    "num"),    # sivr00315vrv18khia1
    (r'^(.*?\d)([a-f])(?:[-_].*)?$',              "alpha"),  # SIVR-285a-4k60fps
]

SIDECAR_EXT = {".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}


def rename_path(src, new_name):
    """
    改名单个文件。与 rename_folder 同样的坑：不区分大小写的文件系统上，
    仅改大小写时单步 rename 可能静默无效，需经临时名中转。异常抛给调用方。
    """
    parent = src.parent
    if src.name == new_name:
        return
    src.rename(parent / new_name)
    if src.name.lower() != new_name.lower():
        return
    # 仅改大小写：校验是否真的以新大小写落盘，没有则临时名中转
    if new_name in {p.name for p in parent.iterdir()}:
        return
    tmp = parent / f"__casetmp__{new_name}"
    n = 0
    while tmp.exists():
        n += 1
        tmp = parent / f"__casetmp{n}__{new_name}"
    (parent / new_name).rename(tmp)
    tmp.rename(parent / new_name)


def video_volume_key(stem):
    """剥离站点前缀后 → (基名, 分卷序号)；无分卷返回 (基名, None)"""
    s = VID_SITE.sub("", stem)
    s = re.sub(r'[\[\]]', '', s)
    for pat, kind in VOL_PATTERNS:
        m = re.search(pat, s, re.I)
        if m:
            g = m.group(2)
            idx = int(g) if kind == "num" else ord(g.upper()) - 64
            return m.group(1).lower().rstrip("-_ "), idx
    return s.lower(), None


def classify_videos(folder):
    """
    分类文件夹内的视频 →
      kind ∈ {'single','split','dup','none'} , videos, junk
    'dup'  = 同一部片的多个来源/版本（绝不自动处理）
    'junk' = 与番号无关的混入文件（绝不自动处理）
    """
    vids = sorted([p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in VIDEO_EXT],
                  key=lambda p: p.name)
    code, _ = normalize(folder.name)
    prefix = re.match(r'^([A-Za-z]+)', code).group(1).lower() if code else ""

    related, junk = [], []
    for v in vids:
        clean = VID_SITE.sub("", v.stem).lower()
        (related if prefix and prefix in clean else junk).append(v)

    # 只有一个视频且没有无关文件时，junk 判定不可靠 —— 全部归为相关
    if not related and vids:
        related, junk = vids, []

    if not related:
        return "none", [], junk
    if len(related) == 1:
        return "single", related, junk

    keys = [video_volume_key(v.stem) for v in related]
    bases = {k[0] for k in keys}
    idxs = [k[1] for k in keys]
    if len(bases) == 1 and None not in idxs and len(set(idxs)) == len(idxs):
        ordered = [v for _, v in sorted(zip(idxs, related), key=lambda t: t[0])]
        return "split", ordered, junk
    return "dup", related, junk


def plan_video_renames(folders):
    """返回 (改名计划, 重复片源列表, 无关文件列表)"""
    plan, dups, junks = [], [], []
    for f in folders:
        code, tags = normalize(f.name)
        if not code:
            continue
        base = f"{code}{SUFFIX_MAP.get(tuple(tags), '')}"
        kind, vids, junk = classify_videos(f)
        if junk:
            junks.append((f, junk))
        if kind == "dup":
            dups.append((f, vids))
            continue
        if kind == "single":
            targets = [f"{base}{vids[0].suffix.lower()}"]
        elif kind == "split":
            targets = [f"{base}-{i}{v.suffix.lower()}" for i, v in enumerate(vids, 1)]
        else:
            continue
        for v, t in zip(vids, targets):
            if v.name != t:
                plan.append((f, v, t))
    return plan, dups, junks


def do_rename_videos(folders, log_path, apply=False):
    plan, dups, junks = plan_video_renames(folders)

    print(f"\nVideo files eligible for safe cleanup: {len(plan)}")
    print(f"⚠️  Folders with duplicate sources     : {len(dups)} "
          "(reported only; manual choice required)")
    print(f"🚮 Folders with unrelated files        : {len(junks)} "
          "(reported only; manual review required)")

    if dups:
        print("\n" + "─" * 78)
        print("⚠️  Duplicate sources — multiple sources or qualities for one title "
              "require a manual choice")
        print("─" * 78)
        for f, vids in dups:
            print(f"  {f.name}")
            for v in vids:
                print(f"     └ {v.name:<48} {v.stat().st_size / 2**30:6.2f} GB")

    if junks:
        print("\n" + "─" * 78)
        print("🚮 Unrelated files — suspected promotional files; "
              "nothing will be deleted or renamed")
        print("─" * 78)
        for f, junk in junks:
            print(f"  {f.name}")
            for v in junk:
                print(f"     └ {v.name:<48} {v.stat().st_size / 2**30:6.2f} GB")

    if plan:
        print("\n" + "─" * 78)
        print("✅ Video files eligible for cleanup")
        print("─" * 78)
        cur = None
        for f, v, t in plan:
            if f.name != cur:
                print(f"  {f.name}/")
                cur = f.name
            print(f"     {v.name[:50]:<52} → {t}")

    if not apply:
        print("\n[Preview] No changes made. Review the plan, then add --apply.")
        return

    root = folders[0].parent if folders else Path(".")
    log = RenameLog(log_path, root)
    if log.batches() and not log.root_matches():
        sys.exit(
            f"Rename journal belongs to another media root; stopped to avoid mixing batches:\n"
            f"  Journal root : {log.data.get('root')}\n"
            f"  Selected root: {log.root}\n"
            "Use --video-log to select a different journal.")
    log.open_batch()
    log.flush()                         # 先确认日志可写，再开始改名
    ok = fail = 0
    print("\n─── Applying changes ───")
    for f, v, t in plan:
        target = f / t
        # 不区分大小写的文件系统上，仅改大小写时 target.exists() 会命中文件自身，
        # 不能据此判为冲突（文件夹改名早已处理，这里之前漏了）。
        if target.exists() and v.name.lower() != t.lower():
            print(f"  ⏭  {v.name} → {t}  (target exists; skipped)")
            continue
        try:
            # 同名的字幕 / NFO 等附属文件一起改，避免变成孤儿
            side_moves = []
            for s in f.iterdir():
                if s.is_file() and s.stem == v.stem and s.suffix.lower() in SIDECAR_EXT:
                    side_moves.append((s, f / (Path(t).stem + s.suffix)))
            rename_path(v, t)
            for s, st in side_moves:
                if st.name.lower() == s.name.lower() or not st.exists():
                    rename_path(s, st.name)
        except Exception as e:
            fail += 1
            print(f"  ❌ {v.name[:50]:<52} {type(e).__name__}: {e}")
            continue
        # 日志失败必须终止后续改名，不能被上面的文件操作异常分支吞掉。
        sides = [{"old": s.name, "new": st.name} for s, st in side_moves]
        log.add({"dir": f.name, "old": v.name, "new": t, "sides": sides})
        ok += 1
        print(f"  ✅ {v.name[:50]:<52} → {t}")

    if not ok:
        log.drop_batch(-1)

    print(f"\nVideo rename complete: succeeded {ok}  failed {fail}")
    if ok:
        print(f"Journal saved: {log_path}")
        print("To undo:  uv run javlibrarian.py --undo-videos --dir \"<media-root>\"")


def do_undo_videos(root, log_path, want_all=False):
    log, idxs = load_log_for_undo(log_path, root, want_all)
    batches = log.batches()
    total = sum(len(batches[i]["entries"]) for i in idxs)
    print(f"Journal batches: {len(batches)}; rollback selection: "
          f"{len(idxs)} batch(es) / {total} entries "
          f"{'(all)' if want_all else '(latest only)'}")

    def do_one(root_path, item):
        d = Path(root_path) / item["dir"]
        cur = d / item["new"]
        if not cur.is_file():
            return None, ""
        try:
            rename_path(cur, item["old"])
            # 附属文件（nfo / 字幕）一并退回。
            # 注意 exists() 在不区分大小写的文件系统上会命中自身，需先排除仅大小写差异。
            for s in item.get("sides", []):
                sp = d / s["new"]
                if not sp.is_file():
                    continue
                if s["new"].lower() == s["old"].lower() or not (d / s["old"]).exists():
                    rename_path(sp, s["old"])
            return True, ""
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    all_ok = True
    for i in sorted(idxs, reverse=True):
        b = batches[i]
        print(f"\n── Batch {i + 1}/{len(batches)}  {b.get('time', '')}")
        ok, skip, fail, remaining = _undo_entries(root, b["entries"], do_one, "Video")
        if remaining:
            if ok:
                b["entries"] = remaining
                log.flush()
            all_ok = False
        else:
            log.drop_batch(i)
    if all_ok:
        print("Rolled-back batch records were removed from the journal.")
    else:
        print("Skipped or failed entries remain in the journal; resolve them and retry.")


# ══════════════════════════════════════════════════════════════════
#  HTTP 会话（串行 + 限流退避）
# ══════════════════════════════════════════════════════════════════

class Fetcher:
    """
    按「主机 + 类型」分桶限流。

    分类型：HTML 详情页是触发 429 的真凶（实测 4 并发跑 37 个就被封），
    图片是静态资源，无需同等节流。HTML 严、图片松。

    分主机：限流是各站自己算的。JavBus 和 JavDB 共用一个桶的话，一是 JavDB
    被限流会连累 JavBus 跟着减速，二是双源并跑时两站的请求要排队等同一个
    间隔、白白慢一倍。按主机分开后各站各自计时，互不干扰。

    策略取向：宁可慢，不要被封。一旦某个桶吃到 429，就把它的基础间隔按 1.5 倍
    永久调高（本次运行内不恢复）——被限流说明当前节奏已经过快，退避完再按原速
    冲回去只会再被限一次。

    影片之间另设独立间隔，从上一部实际联网刮削结束时开始计时。已有 NFO、番号
    无法识别等纯本地跳过项不参与计时，因此不会为了跳过文件夹白等。
    """

    BACKOFF_START = 10.0     # 首次退避秒数
    BACKOFF_CAP   = 300.0    # 退避封顶
    SLOWDOWN      = 1.5      # 吃到 429 后基础间隔的放大倍数
    DELAY_CAP     = 30.0     # 基础间隔封顶，防止无限放大
    RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

    def __init__(self, delay=DEFAULT_HTML_DELAY, img_delay=DEFAULT_IMG_DELAY,
                 verbose=False, movie_delay=DEFAULT_MOVIE_DELAY):
        self.verbose = verbose
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
            "Accept": "text/html,application/xhtml+xml,image/webp,*/*;q=0.8",
        })
        self.s.cookies.set("over18", "1", domain="javdb.com")   # JavDB 的年龄确认
        self._base = {"html": delay, "img": img_delay}    # 类型 → 初始间隔
        self._delay = {}                                  # 计时桶 → 当前基础间隔
        self._last = {}                                   # 计时桶 → 上次请求时间戳
        self._blocked_until = {}                          # 计时桶 → 限流冷却截止时间
        self.throttled = 0                                # 本次运行吃到的 429 次数
        self.movie_delay = movie_delay                    # 实际刮削影片之间的间隔
        self._movie_ended_at = None                       # 上一部实际刮削的结束时间
        self._movie_active = False                        # 当前文件夹是否已进入联网刮削

    @staticmethod
    def bucket_of(url, binary):
        host = re.sub(r'^https?://([^/]+).*$', r'\1', url or "").lower() or "?"
        return f"{host}:{'img' if binary else 'html'}"

    def _delay_of(self, bucket):
        if bucket not in self._delay:
            self._delay[bucket] = self._base["img" if bucket.endswith(":img") else "html"]
        return self._delay[bucket]

    def _wait(self, bucket):
        # 用 monotonic 而不是 time()：全量刮削要跑几十分钟，期间系统对时
        # （NTP）把墙钟往前跳会让间隔失效、瞬间打出一串请求，往后跳则白等。
        delay = self._delay_of(bucket)
        now = time.monotonic()
        gap = now - self._last.get(bucket, now - delay)
        wait = max(delay - gap, self._blocked_until.get(bucket, 0) - now)
        if wait > 0:
            time.sleep(wait)
        self._last[bucket] = time.monotonic()

    def _slow_down(self, bucket):
        old = self._delay_of(bucket)
        self._delay[bucket] = min(old * self.SLOWDOWN, self.DELAY_CAP)
        if self.verbose and self._delay[bucket] > old:
            print(f"      · {bucket} base interval {old:.1f}s → {self._delay[bucket]:.1f}s", flush=True)

    def begin_movie(self):
        """在实际联网刮削开始前补足片间间隔；首部影片不等待。"""
        if self._movie_ended_at is not None and self.movie_delay > 0:
            elapsed = time.monotonic() - self._movie_ended_at
            wait = self.movie_delay - elapsed
            if wait > 0:
                if self.verbose:
                    print(f"      · inter-title wait {wait:.1f}s", flush=True)
                time.sleep(wait)
        self._movie_active = True

    def finish_movie(self):
        """只记录真正进入过联网刮削的影片；SKIP 调用本方法不会重置计时。"""
        if self._movie_active:
            self._movie_ended_at = time.monotonic()
            self._movie_active = False

    def get(self, url, referer=None, binary=False, max_retry=5):
        """返回 (status_code, content) ；content 为 str 或 bytes；失败返回 (code, None)"""
        headers = {"Referer": referer} if referer else {}
        bucket = self.bucket_of(url, binary)
        backoff = self.BACKOFF_START
        for attempt in range(max_retry):
            self._wait(bucket)
            try:
                r = self.s.get(url, headers=headers, timeout=30)
            except requests.exceptions.RequestException as e:
                if attempt == max_retry - 1:
                    return 0, None
                if self.verbose:
                    print(f"      · {type(e).__name__}; retrying in {backoff:.0f}s", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, self.BACKOFF_CAP)
                continue

            if r.status_code == 429:
                self.throttled += 1
                ra = r.headers.get("Retry-After")
                wait = float(ra) if (ra and ra.isdigit()) else backoff
                self._slow_down(bucket)
                if attempt == max_retry - 1:
                    # 不再全局空等；只阻止该主机桶在冷却期内再次请求。
                    deadline = time.monotonic() + wait
                    self._blocked_until[bucket] = max(
                        self._blocked_until.get(bucket, 0), deadline)
                    return 429, None
                if self.verbose:
                    print(f"      · 429 rate limit; retrying in {wait:.0f}s", flush=True)
                time.sleep(wait)
                backoff = min(backoff * 2, self.BACKOFF_CAP)
                continue

            if r.status_code == 200:
                return 200, (r.content if binary else r.text)

            if r.status_code not in self.RETRYABLE_STATUS:
                return r.status_code, None

            if r.status_code == 503:
                self._slow_down(bucket)
            if attempt == max_retry - 1:
                return r.status_code, None
            time.sleep(backoff)
            backoff = min(backoff * 2, self.BACKOFF_CAP)
        return 0, None


# ══════════════════════════════════════════════════════════════════
#  数据源：JavBus（主）
# ══════════════════════════════════════════════════════════════════

def _clean(t):
    return html.unescape(re.sub(r'<[^>]+>', '', t)).strip()


def _same_code(a, b):
    """番号等价比较：忽略大小写、分隔符与前导零（IPVR-256 == ipvr_0256）"""
    def norm(x):
        m = re.match(r'^([A-Za-z]+)[-_]?0*(\d+)$', (x or "").strip())
        return f"{m.group(1).upper()}-{int(m.group(2))}" if m else (x or "").upper()
    return norm(a) == norm(b)


def parse_javbus(page_html, code):
    """解析 JavBus 影片页 → dict；无封面视为未命中"""
    if '<a class="bigImage"' not in page_html:
        return None

    d = {"source": "javbus", "code": code}

    m = re.search(r'<h3>(.*?)</h3>', page_html, re.S)
    d["title"] = _clean(m.group(1)) if m else code

    m = re.search(r'<a class="bigImage" href="([^"]+)"', page_html)
    if m:
        u = m.group(1)
        d["cover"] = u if u.startswith("http") else JAVBUS + u

    # info 区块
    i = page_html.find('class="col-md-3 info"')
    blk = page_html[i:i + 6000] if i > 0 else page_html

    def field(label):
        m = re.search(r'<span class="header">%s:</span>\s*(?:<[^>]+>\s*)?([^<]+)' % label, blk)
        return _clean(m.group(1)) if m and _clean(m.group(1)) else None

    # 本地推算的番号不作数：拿页面自报的識別碼反向校验，不一致就当未命中。
    # 防止归一化剥离过头 / 站点模糊匹配，把别的片子的元数据挂到你的文件夹上。
    page_id = field("識別碼")
    if page_id and not _same_code(page_id, code):
        return None
    d["dvdid"]   = page_id or code
    d["release"] = field("發行日期")
    d["studio"]  = field("製作商")
    d["label"]   = field("發行商")
    d["series"]  = field("系列")
    d["director"] = field("導演")

    rt = field("長度")
    if rt:
        mm = re.search(r'(\d+)', rt)
        d["runtime"] = int(mm.group(1)) if mm else None

    # 繁中类别
    genres = re.findall(
        r'<span class="genre">(?:(?!</span>).)*?<a href="[^"]*/genre/[^"]*">([^<]+)</a>',
        blk, re.S)
    d["genres"] = [_clean(g) for g in genres if _clean(g)]

    # 演员 + 头像
    actors = []
    for mm in re.finditer(
            r'<a class="avatar-box" href="[^"]*">\s*<div class="photo-frame">\s*'
            r'<img src="([^"]+)"[^>]*>\s*</div>\s*<span>([^<]+)</span>', page_html, re.S):
        thumb, name = mm.group(1), _clean(mm.group(2))
        if not thumb.startswith("http"):
            thumb = JAVBUS + thumb
        if "nowprinting" in thumb.lower():
            thumb = ""
        actors.append({"name": name, "thumb": thumb})
    if not actors:
        for mm in re.finditer(r'<a href="[^"]*/star/[^"]*">([^<]+)</a>', page_html):
            n = _clean(mm.group(1))
            if n and n not in [a["name"] for a in actors]:
                actors.append({"name": n, "thumb": ""})
    d["actors"] = actors

    # 剧照
    samples = re.findall(r'<a class="sample-box" href="([^"]+)"', page_html)
    d["samples"] = [s if s.startswith("http") else JAVBUS + s for s in samples]

    return d


def fetch_javbus(fetcher, code):
    status, page = fetcher.get(f"{JAVBUS}/{code}")
    if status != 200 or not page:
        return None
    return parse_javbus(page, code)


# ══════════════════════════════════════════════════════════════════
#  数据源：JavDB（补 JavBus 的缺口）
# ══════════════════════════════════════════════════════════════════

def _javdb_field(page, *labels):
    """panel-block 里的 "标签: 值"，值可能裹着 <a>，取纯文本。"""
    for lb in labels:
        m = re.search(r'<strong>%s\s*:?\s*</strong>(.*?)</div>' % lb, page, re.S)
        if m:
            v = _clean(re.sub(r'<[^>]+>', ' ', m.group(1))).replace("&nbsp;", " ").strip()
            v = re.sub(r'\s{2,}', ' ', v)
            if v:
                return v
    return None


def javdb_find(fetcher, code):
    """搜索页 → 详情页路径。

    JavDB 的搜索是模糊的：搜 DSVR-1273 会同时返回 DSVR-1173、DSVR-1073，
    所以必须按结果卡片里 <strong> 的番号精确比对，不能取第一条。
    """
    status, page = fetcher.get(f"{JAVDB}/search?q={code}&f=all")
    if status != 200 or not page:
        return None
    for chunk in page.split('<a href="/v/')[1:]:
        path = chunk.split('"', 1)[0]
        head = chunk[:600]
        for got in re.findall(r'<strong>([A-Za-z0-9\-_]+)</strong>', head):
            if _same_code(got, code):
                return f"/v/{path}"
    return None


def fetch_javdb(fetcher, code):
    path = javdb_find(fetcher, code)
    if not path:
        return None
    status, page = fetcher.get(f"{JAVDB}{path}?locale=zh")
    if status != 200 or not page:
        return None

    d = {"source": "javdb", "code": code}

    m = re.search(r'<h2 class="title[^"]*">(.*?)</h2>', page, re.S)
    if not m:
        return None
    parts = re.findall(r'<strong[^>]*>(.*?)</strong>', m.group(1), re.S)
    page_id = _clean(parts[0]) if parts else None
    if page_id and not _same_code(page_id, code):
        return None                       # 同 JavBus：番号对不上就不采信
    d["dvdid"] = page_id or code
    d["title"] = _clean(parts[1]) if len(parts) > 1 else code

    d["release"]  = _javdb_field(page, "日期")
    d["studio"]   = _javdb_field(page, "片商")
    d["label"]    = _javdb_field(page, "發行", "发行")
    d["series"]   = _javdb_field(page, "系列")
    d["director"] = _javdb_field(page, "導演", "导演")

    rt = _javdb_field(page, "時長", "时长")
    if rt:
        mm = re.search(r'(\d+)', rt)
        d["runtime"] = int(mm.group(1)) if mm else None

    cats = _javdb_field(page, "類別", "类别") or ""
    d["genres"] = [g.strip() for g in cats.split(",") if g.strip()]

    # 演员块里 ♀/♂ 紧跟在名字后面；只留女优，和 JavBus 的 avatar-box 口径一致
    actors, seen = [], set()
    blk = re.search(r'<strong>演員\s*:?\s*</strong>(.*?)</div>', page, re.S)
    if blk:
        for mm in re.finditer(r'>([^<>]+)</a>\s*<strong[^>]*>\s*♀', blk.group(1)):
            n = _clean(mm.group(1))
            if n and n not in seen:
                seen.add(n)
                actors.append({"name": n, "thumb": ""})
    d["actors"] = actors

    m = re.search(r'(https://c\d\.jdbstatic\.com/covers/[^"\']+)', page)
    if m:
        d["cover"] = m.group(1)
    # _l_ 是大图，_s_ 是缩略图，只要大图
    sm = sorted(set(re.findall(r'https://c\d\.jdbstatic\.com/samples/[^"\']*_l_(\d+)\.jpg', page)),
                key=int)
    base = re.search(r'(https://c\d\.jdbstatic\.com/samples/[^"\']*)_l_\d+\.jpg', page)
    d["samples"] = [f"{base.group(1)}_l_{n}.jpg" for n in sm] if base else []
    return d


# ══════════════════════════════════════════════════════════════════
#  图片处理（下载 + sips 裁剪）
# ══════════════════════════════════════════════════════════════════

def sips_size(path):
    try:
        o = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                           capture_output=True, text=True, timeout=30).stdout
        w = int(re.search(r'pixelWidth:\s*(\d+)', o).group(1))
        h = int(re.search(r'pixelHeight:\s*(\d+)', o).group(1))
        return w, h
    except Exception:
        return None, None


def make_poster(src, dst, ratio=POSTER_WIDTH_RATIO):
    """从横版封面裁出右侧竖版海报。

    普通片的封套是一整张纸包住 DVD 盒，摊平 =【封底 | 书脊 | 正面封面】，
    比例恒为 1.48（对应盒子 (135+14+135)mm × 190mm）。正面封面就是最右边那块。
    只有剧照里找不到竖版封面时才走这里 —— 见 pick_sample_poster()。

    已知裁不准的：不是 DVD 盒展开图的片（实测 REBDB-1006 比例 1.810、
    SS-027 = 1.798、MIHD-006 = 1.329，标准盒型是 1.48）。它们的正面封面
    未必占 47.5% 宽、也未必贴右边缘。但这几部要么没剧照、要么 DMM 的
    ps.jpg 是占位图，没有可信基准能定位真实裁剪区域（拿 147×200 缩略图
    滑窗，已知正确的对照组 RMSE 也有 53.6，噪声盖过信号），所以一律按
    47.5% 右裁，偏一点也好过没有。
    """
    w, h = sips_size(src)
    if not w or not h:
        return False
    if w / h < 1.15:                      # 本来就是竖版，直接复制
        shutil.copyfile(src, dst)
        return True
    pw = max(1, min(int(w * ratio), w))   # 按封面宽度取比例
    off_x = w - pw                        # 右对齐
    r = subprocess.run(
        ["sips", "-c", str(h), str(pw), "--cropOffset", "0", str(off_x),
         str(src), "--out", str(dst)],
        capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and Path(dst).exists()


def download(fetcher, url, dst, referer=None, min_edge=0):
    """下图。min_edge 为短边下限，用来挡 DMM 的占位图。

    占位图是 90×122 / 2732 字节 —— 字节数门槛拦不住（实测 CJOD-149、DSVR-1273
    的剧照现在全是占位图），必须真去读像素尺寸。
    """
    if not url:
        return False
    status, data = fetcher.get(url, referer=referer, binary=True)
    if status != 200 or not data or len(data) < 1024:
        return False
    dst = Path(dst)
    tmp = dst.with_name(f".{dst.stem}.{os.getpid()}.tmp{dst.suffix}")
    try:
        tmp.write_bytes(data)
        if min_edge:
            w, h = sips_size(tmp)
            if not w or not h or min(w, h) < min_edge:
                return False
        os.replace(tmp, dst)
        return True
    finally:
        tmp.unlink(missing_ok=True)


def referer_for(url):
    """图挂在哪家的 CDN 上就带哪家的 referer。JavBus 的剧照直连 DMM，仍用 JavBus。"""
    return JAVDB + "/" if "jdbstatic.com" in (url or "") else JAVBUS + "/"


def download_with_alt(fetcher, url, alt, dst, min_edge=MIN_IMAGE_EDGE):
    """先下主源，失效（含占位图）就换备源同位置那张。返回是否成功。"""
    if download(fetcher, url, dst, referer=referer_for(url), min_edge=min_edge):
        return True
    if alt:
        return download(fetcher, alt, dst, referer=referer_for(alt), min_edge=min_edge)
    return False


# ── 竖版封面识别（sips + 纯 Python，不引入 Pillow）────────────────────

def gray_matrix(src, width, height):
    """把图缩放到指定尺寸并解码成灰度矩阵。

    走 sips 转 BMP 再自己解析 —— 标准库没有 JPEG 解码器，图片处理不额外引入 Pillow。
    坑：sips 输出的是 top-down BMP，高度字段是负数，按无符号读会得到 42 亿行。
    """
    tmp = Path(f"{src}.bmp")
    try:
        subprocess.run(["sips", "--resampleHeightWidth", str(height), str(width),
                        "-s", "format", "bmp", str(src), "--out", str(tmp)],
                       capture_output=True, timeout=60)
        if not tmp.exists():
            return None
        b = tmp.read_bytes()
    except Exception:
        return None
    finally:
        tmp.unlink(missing_ok=True)

    if len(b) < 54 or b[:2] != b"BM":
        return None
    off = int.from_bytes(b[10:14], "little")
    w   = int.from_bytes(b[18:22], "little", signed=True)
    h   = int.from_bytes(b[22:26], "little", signed=True)
    px  = int.from_bytes(b[28:30], "little") // 8
    topdown, h = h < 0, abs(h)
    if w <= 0 or h <= 0 or px < 3:
        return None
    row = ((w * px + 3) // 4) * 4
    if off + row * h > len(b):
        return None
    out = []
    for y in range(h):
        base = off + (y if topdown else h - 1 - y) * row
        out.append([(b[base + x * px]     * 114 +      # BGR → 灰度
                     b[base + x * px + 1] * 587 +
                     b[base + x * px + 2] * 299) // 1000 for x in range(w)])
    return out


def gray_stddev(m):
    """灰度标准差，用来识别「近乎空白」的图。

    DMM 缺图时返回的占位图不止 90×122 一种尺寸：DSVR-1273 的 ps.jpg 是 147×200，
    尺寸够大能躲过 MIN_IMAGE_EDGE，但内容是浅色背景加一行字。
    实测标准差：正常封面 62~65，占位图 15.3（和已知占位图的 15.2 几乎一致）。
    """
    v = [q for row in m for q in row]
    if not v:
        return 0.0
    avg = sum(v) / len(v)
    return (sum((q - avg) ** 2 for q in v) / len(v)) ** 0.5


def gray_rmse(a, b):
    """两张同尺寸灰度图的均方根误差。越小越像；实测同一张图 13~35，不同图 70+。"""
    if not a or not b:
        return float("inf")
    s = n = 0
    for ra, rb in zip(a, b):
        for va, vb in zip(ra, rb):
            d = va - vb
            s += d * d
            n += 1
    return (s / n) ** 0.5 if n else float("inf")


KANA = re.compile(r'[぀-ヿ]')          # 平/片假名。没有假名的标题即判为中文译名


def merge_sources(bus, db):
    """双源合并：以 JavBus 为骨架，JavDB 只补它的强项。

    10 部抽样实测的分工依据：
      JavBus 强 —— 發行商 10/10 vs 2/10、类别 85 个 vs 70 个、演员头像 12 个 vs 0，
                   封面比例稳定（JavDB 有时索引的是蓝光版，800×438 而非 800×538，
                   拿去按 DVD 比例裁海报会裁错）
      JavDB 强 —— 部分片有繁中译名标题（4/10）、系列偶尔更全、
                   JavBus 那边失效的图它可能还在（CJOD-149 的剧照就是）
    """
    if not bus:
        return db
    d = dict(bus)
    if not db:
        return d

    # 中文标题：JavDB 的标题不含假名就是译名
    db_title = (db.get("title") or "").strip()
    if db_title and not KANA.search(db_title):
        d["title_cn"] = db_title

    # JavBus 缺的标量字段用 JavDB 补
    for f in ("release", "runtime", "studio", "label", "series", "director"):
        if not d.get(f) and db.get(f):
            d[f] = db[f]

    # 类别取并集去重，保持 JavBus 的顺序在前。
    # 必须去重：JavDB 自己的类别列表里就有重复（IPVR-256 的「VR」出现两次）。
    d["genres"] = list(dict.fromkeys(list(d.get("genres", [])) + db.get("genres", [])))

    # 演员只取 JavBus —— 它记的是发行时的艺名，和封面、标题上印的一致。
    # JavDB 记的是现艺名（楓カレン→田中レモン、橋本ありな→新ありな），
    # 写进去会和这部片本身的封面标题对不上。只有 JavBus 没有时才用它兜底。
    if not d.get("actors"):
        d["actors"] = db.get("actors", [])

    # 图片留作兜底：JavBus 的某张失效时顶上
    if db.get("cover"):
        d["cover_alt"] = db["cover"]
    if db.get("samples"):
        if d.get("samples"):
            d["samples_alt"] = db["samples"]
        else:
            d["samples"] = db["samples"]
    return d


def ps_reference_url(samples, code=None):
    """DMM 官方竖版封面 ps.jpg 的地址。

    它只有 147×200，太小不能入库，仅作「哪张才是竖版封面」的比对基准。
    两条路依次尝试：
      1. 剧照链接里的 cid —— JavBus 走这条（它的封面链接是站内 hash，认不出 cid）
      2. 从番号推 cid（SONE-035 → sone00035）—— JavDB 的图挂在自己的 CDN 上，
         链接里没有 cid，只能这样兜。少数片的 cid 带前缀（FSVSS-003 是
         1fsvss00003）推不出来，那就退回「第一张竖版图」，不影响主流程。
    """
    cid = None
    for s in samples:
        m = DMM_CID.search(s or "")
        if m:
            cid = m.group(1)
            break
    if not cid and code:
        m = re.match(r'^([A-Za-z]+)[-_]?(\d+)$', code.strip())
        if m:
            cid = f"{m.group(1).lower()}{int(m.group(2)):05d}"
    if not cid:
        return None
    return f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}ps.jpg"


def is_vr(d, code):
    """VR 判定：标题带【VR】/ 类别含 VR / 番号含 VR，任一命中即可。

    不能只看番号 —— FSVSS-003 是 VR 但番号里没有 VR，靠标题的【VR】前缀和类别
    「VR専用」「ハイクオリティVR」认出来。也不能看封面宽高比，VR 的比例
    1.33/1.60/1.77 都有，会和非标普通片撞。
    """
    if "VR" in re.sub(r'[^A-Za-z]', '', code).upper():
        return True
    if "【VR】" in (d.get("title") or "") or "[VR]" in (d.get("title") or "").upper():
        return True
    return any("VR" in (g or "").upper() for g in d.get("genres", []))


def pick_sample_poster(fetcher, candidates, ref_url, workdir):
    """从剧照里挑出竖版封面，返回 (选中的 Path, 说明) 或 (None, 原因)。

    只对 VR 片使用。普通片的剧照里也常有竖版图，但那是竖着拍的场景照不是封面 ——
    实测比例几乎都是 534×800 = 0.667（标准照片比例），而真封面是 588×800 = 0.735，
    与 ps.jpg 完全一致。个别 600×800 = 0.750 的宣传图还会骗过 RMSE
    （MIDA-039 的第 6 张 RMSE 31、MIDA-439 的第 10 张 RMSE 56，都不是封面），
    所以普通片一律不走这里，直接裁横版。

    实测 9 部 VR：8 部命中（RMSE 13~35），其中 MDVR-327 的封面排在第二张而不是第一张，
    SAVR-1062 的剧照里根本没有封面（最低 70）→ 这两种情况都得靠基准图比对才认得出来。
    拿不到基准图时退回「第一张竖版图」，仍比裁剪强。
    """
    portrait = []
    for p in candidates:
        w, h = sips_size(p)
        if w and h and w < h:
            portrait.append(p)
    if not portrait:
        return None, "no portrait image among samples"

    base = tw = th = None
    if ref_url:
        rp = Path(workdir) / "_ps_ref.jpg"
        if download(fetcher, ref_url, rp, referer=JAVBUS + "/", min_edge=100):
            rw, rh = sips_size(rp)
            if rw and rh:
                tw, th = max(1, round(rw * PS_MATCH_HEIGHT / rh)), PS_MATCH_HEIGHT
                base = gray_matrix(rp, tw, th)
                # 基准图本身是占位图的话，拿它比对只会算出一个假的高 RMSE，
                # 把本来正确的竖版封面误判成「没有」。宁可当作没有基准。
                if base and gray_stddev(base) < PS_MIN_STDDEV:
                    base = None
            rp.unlink(missing_ok=True)
    if not base:
        return portrait[0], "first portrait sample (no reference)"

    best, best_score = None, float("inf")
    for p in portrait:
        score = gray_rmse(base, gray_matrix(p, tw, th))
        if score < best_score:
            best, best_score = p, score
    if best_score > PS_MATCH_MAX_RMSE:
        return None, f"no matching poster among samples (RMSE {best_score:.0f})"
    return best, f"RMSE {best_score:.0f}"


# ══════════════════════════════════════════════════════════════════
#  NFO 生成（中文优先）
# ══════════════════════════════════════════════════════════════════

def build_nfo(d, tags, folder_name):
    root = ET.Element("movie")

    def add(parent, tag, text):
        if text is None or text == "":
            return None
        e = ET.SubElement(parent, tag)
        e.text = str(text)
        return e

    code = d.get("dvdid") or d.get("code")

    def strip_code(t):
        """JavBus 的 <h3> 已含番号前缀，去重后再拼"""
        t = (t or "").strip()
        return t[len(code):].strip() if t.upper().startswith(code.upper()) else t

    body = strip_code(d.get("title"))
    # 中文标题优先：JavDB 对部分片有繁中译名，有就用，没有才用日文原名。
    # 原名始终保留在 originaltitle，不被中文覆盖。
    display = strip_code(d.get("title_cn")) or body

    add(root, "title", f"{code} {display}".strip())
    add(root, "originaltitle", body or display)
    add(root, "sorttitle", code)
    add(root, "num", code)

    uid = ET.SubElement(root, "uniqueid")
    uid.set("type", "num")
    uid.set("default", "true")
    uid.text = code

    add(root, "premiered", d.get("release"))
    add(root, "releasedate", d.get("release"))
    if d.get("release") and re.match(r'^\d{4}', d["release"]):
        add(root, "year", d["release"][:4])

    add(root, "runtime", d.get("runtime"))
    add(root, "studio", d.get("studio"))
    add(root, "maker", d.get("studio"))
    add(root, "label", d.get("label"))
    add(root, "director", d.get("director"))

    if d.get("series"):
        s = ET.SubElement(root, "set")
        add(s, "name", d["series"])

    # 类别：繁中类别 + 语义标记（-C/-U 转标签，方便 Emby 筛选）
    for g in d.get("genres", []):
        add(root, "genre", g)
    for t in tags:
        add(root, "genre", t)
        add(root, "tag", t)
    if d.get("series"):
        add(root, "tag", d["series"])

    for a in d.get("actors", []):
        ae = ET.SubElement(root, "actor")
        add(ae, "name", a.get("name"))
        add(ae, "type", "Actor")
        if a.get("thumb"):
            add(ae, "thumb", a["thumb"])

    add(root, "poster", "poster.jpg")
    fa = ET.SubElement(root, "fanart")
    add(fa, "thumb", "fanart.jpg")

    add(root, "source", d.get("source"))
    add(root, "originalfolder", folder_name)

    raw = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")
    return pretty


# ══════════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════════

def list_folders(root):
    return sorted([p for p in Path(root).iterdir()
                   if p.is_dir() and not p.name.startswith(".")],
                  key=lambda p: p.name.lower())


def do_dry_run(folders):
    print(f"\n{'Original folder':<44} {'Query ID':<16} Tags")
    print("─" * 92)
    ok = bad = 0
    for f in folders:
        code, tags = normalize(f.name)
        if code:
            ok += 1
        else:
            bad += 1
        mark = "✅" if code else "❌"
        print(f"{f.name[:43]:<44} {str(code):<16} {'/'.join(tags) or '—'}  {mark}")
    print("─" * 92)
    print(f"Recognized {ok} / Unrecognized {bad} / Total {len(folders)}")
    print("\n[dry-run] No network requests or file writes were performed.")


def scrape_one(folder, fetcher, args):
    code, tags = normalize(folder.name)
    if not code:
        return "SKIP", "Catalog number not recognized"

    nfo_path = folder / "movie.nfo"
    if nfo_path.exists() and not args.force:
        return "SKIP", "movie.nfo exists; skipped (--force to override)"

    # 先完成所有纯本地跳过判断，再开始片间计时；这样 SKIP 不会产生无意义等待。
    fetcher.begin_movie()

    videos = sorted([p for p in folder.iterdir()
                     if p.is_file() and p.suffix.lower() in VIDEO_EXT],
                    key=lambda p: p.name)

    # 不做缓存，每次都实抓。刮削是一次性的（已有 movie.nfo 就跳过整片），
    # 缓存省不下几次请求，却会在字段口径改动后悄悄喂旧数据。
    bus = fetch_javbus(fetcher, code)
    db = fetch_javdb(fetcher, code)
    d = merge_sources(bus, db)

    if not d:
        return "MISS", f"{code} was not found in either metadata source"

    # 合并后的 source 要覆盖掉 merge_sources 从 JavBus 带过来的 "javbus"，
    # 否则双源命中的片在 NFO 里会写成单源，和控制台输出对不上。
    src_tag = "+".join(s for s, ok in (("javbus", bus), ("javdb", db)) if ok)
    d["source"] = src_tag

    # 先构建内容，但把 movie.nfo 留到最后写；它同时是下次运行的完成标记。
    payload = build_nfo(d, tags, folder.name)

    imgs = []
    if not args.no_images:
        samples = d.get("samples", [])
        alt_samples = d.get("samples_alt", [])
        if args.max_samples > 0:
            samples = samples[:args.max_samples]
            alt_samples = alt_samples[:args.max_samples]
        fanart = folder / "fanart.jpg"
        poster = folder / "poster.jpg"

        # ---- 横版封面 → fanart ----
        # 两站的图失效是互补的：CJOD-149 的剧照在 JavBus 侧全是 DMM 占位图，
        # 同一部片 JavDB 侧却是好的；IPZZ-778 反过来。所以一边挂了就换另一边。
        has_fanart = download_with_alt(fetcher, d.get("cover"), d.get("cover_alt"), fanart)
        if has_fanart:
            imgs.append("fanart")

        # ---- 竖版海报 ----
        # VR 片的竖版封面是剧照里独立的一张图，先去剧照里找；找不到才裁。
        # 普通片一律裁 —— 它们的剧照里也有竖版图，但那是竖着拍的场景照不是封面。
        if is_vr(d, code):
            # 剧照先下到系统临时目录：竖版封面混在里面，挑出来当海报之后再把
            # 剩下的搬进剧照目录，这样封面不会在剧照里重复，也不必回头删文件。
            tmp = Path(tempfile.mkdtemp(prefix="jav_"))
            try:
                got = []
                for idx, su in enumerate(samples, 1):
                    p = tmp / f"s{idx:02d}.jpg"
                    alt = alt_samples[idx - 1] if idx <= len(alt_samples) else None
                    if download_with_alt(fetcher, su, alt, p):
                        got.append(p)

                pick, note = pick_sample_poster(
                    fetcher, got, ps_reference_url(samples, code=code), tmp)
                if pick:
                    shutil.copyfile(pick, poster)
                    got.remove(pick)
                    imgs.append(f"poster(sample: {note})")
                elif has_fanart and make_poster(fanart, poster):
                    imgs.append(f"poster(crop: {note})")

                if got:
                    ef = folder / SAMPLES_DIR
                    ef.mkdir(exist_ok=True)
                    for n, p in enumerate(got, 1):
                        shutil.copyfile(p, ef / f"sample{n}.jpg")
                    imgs.append(f"samples×{len(got)}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            if has_fanart and make_poster(fanart, poster):
                imgs.append("poster(crop)")
            if samples:
                ef = folder / SAMPLES_DIR
                ef.mkdir(exist_ok=True)
                n = 0
                for idx, su in enumerate(samples, 1):
                    alt = alt_samples[idx - 1] if idx <= len(alt_samples) else None
                    if download_with_alt(fetcher, su, alt, ef / f"sample{idx}.jpg"):
                        n += 1
                if n:
                    imgs.append(f"samples×{n}")

    # ---- NFO ----
    # 绿联按视频同名 NFO 读取；movie.nfo 兼容 Emby / Jellyfin / Kodi，并作为
    # 整片完成标记。所有图片流程结束后再原子写入，异常中断时下次仍会重试。
    n_nfo = 1
    for v in videos:
        side = v.with_suffix(".nfo")
        if side.exists() and not args.force:
            continue
        atomic_write_bytes(side, payload)
        n_nfo += 1
    atomic_write_bytes(nfo_path, payload)       # 必须最后提交

    detail = f"{code} [{src_tag}] nfo×{n_nfo}"
    if tags:
        detail += f" tags:{'/'.join(tags)}"
    if imgs:
        detail += f" images:{','.join(imgs)}"
    return "OK", detail


def main():
    ap = argparse.ArgumentParser(
        description="JavLibrarian — JAV NAS media library builder (Emby / Jellyfin / Kodi)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.environ.get(DIR_ENV),
                    help=f"media root (overrides environment variable {DIR_ENV})")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse catalog numbers without network requests or file writes")
    ap.add_argument("--limit", type=int, default=0, help="process only the first N folders")
    ap.add_argument("--only", action="append", default=[],
                    help="process only the named folder (repeatable)")
    ap.add_argument("--delay", type=float, default=DEFAULT_HTML_DELAY,
                    help=f"HTML request interval in seconds (default {DEFAULT_HTML_DELAY:.1f}; "
                         "automatically increased after HTTP 429)")
    ap.add_argument("--img-delay", type=float, default=DEFAULT_IMG_DELAY,
                    help=f"image request interval in seconds (default {DEFAULT_IMG_DELAY:.1f})")
    ap.add_argument("--movie-delay", type=float, default=DEFAULT_MOVIE_DELAY,
                    help=f"interval between online title scrapes in seconds "
                         f"(default {DEFAULT_MOVIE_DELAY:.1f}; no wait before the first title "
                         "or for local skips)")
    ap.add_argument("--force", action="store_true", help="overwrite existing movie.nfo files")
    ap.add_argument("--no-images", action="store_true", help="write NFO files without images")
    ap.add_argument("--max-samples", type=int, default=0,
                    help="maximum sample images per title (default 0 = all)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show request throttling and retry details")

    g = ap.add_argument_group("Rename and rollback")
    g.add_argument("--rename-folders", action="store_true",
                   help="normalize folder names (preview only unless --apply is set)")
    g.add_argument("--rename-videos", action="store_true",
                   help="clean video filenames (preview only unless --apply is set; "
                        "duplicates and unrelated files are reported but unchanged)")
    g.add_argument("--apply", action="store_true",
                   help="apply changes from --rename-folders or --rename-videos")
    g.add_argument("--undo-folders", action="store_true",
                   help="undo the latest folder rename batch from the journal")
    g.add_argument("--undo-videos", action="store_true",
                   help="undo the latest video rename batch from the journal")
    g.add_argument("--undo-all", action="store_true",
                   help="undo every batch with --undo-folders or --undo-videos")
    g.add_argument("--folder-log", default=str(Path(__file__).parent / "folder_rename_log.json"),
                   help="folder rename journal path")
    g.add_argument("--video-log", default=str(Path(__file__).parent / "video_rename_log.json"),
                   help="video rename journal path")
    args = ap.parse_args()

    if not args.dir:
        ap.error(f"specify the media root with --dir or set {DIR_ENV}")

    root = Path(args.dir).expanduser()
    if not root.is_dir():
        sys.exit(f"Directory does not exist or is not accessible: {root}\n"
                 "Check the path, mount status, and permissions.")

    # ---- 还原改名 ----
    if args.undo_folders:
        do_undo_folders(root, args.folder_log, want_all=args.undo_all)
        return
    if args.undo_videos:
        do_undo_videos(root, args.video_log, want_all=args.undo_all)
        return

    folders = list_folders(root)
    if args.only:
        want = set(args.only)
        folders = [f for f in folders if f.name in want]
    if args.limit:
        folders = folders[:args.limit]

    if not folders:
        sys.exit("No folders found.")

    print(f"Root   : {root}")
    print(f"Folders: {len(folders)}")

    # ---- 文件夹改名 ----
    if args.rename_folders:
        do_rename_folders(folders, args.folder_log, apply=args.apply)
        return

    # ---- 视频文件名清理 ----
    if args.rename_videos:
        do_rename_videos(folders, args.video_log, apply=args.apply)
        return

    # --dry-run 必须真的不联网：之前配 --only/--limit 时会漏进刮削路径发请求
    if args.dry_run:
        do_dry_run(folders)
        return

    # 纯跳过项不需要图片工具，避免在没有实际刮削任务时阻塞主路径。
    needs_sips = not args.no_images and any(
        normalize(f.name)[0] and (args.force or not (f / "movie.nfo").exists())
        for f in folders)
    if needs_sips and shutil.which("sips") is None:
        sys.exit("Image processor 'sips' was not found. Run on macOS or use --no-images "
                 "to generate NFO files only.")

    print(f"Intervals: HTML {args.delay}s / images {args.img_delay}s / titles {args.movie_delay}s"
          f"   Samples: {'all' if args.max_samples <= 0 else args.max_samples}"
          f"   Images: {'off' if args.no_images else 'on'}"
          f"   Force: {'yes' if args.force else 'no'}")
    print("─" * 92)

    fetcher = Fetcher(delay=args.delay, img_delay=args.img_delay,
                      movie_delay=args.movie_delay, verbose=args.verbose)
    stat = {"OK": 0, "SKIP": 0, "MISS": 0}
    misses = []
    t0 = time.time()

    for i, f in enumerate(folders, 1):
        try:
            st, msg = scrape_one(f, fetcher, args)
        except KeyboardInterrupt:
            print("\nInterrupted. A rerun will skip completed titles that already have movie.nfo.")
            break
        except Exception as e:
            st, msg = "MISS", f"Error {type(e).__name__}: {e}"
        finally:
            # scrape_one 只有通过纯本地跳过检查后才会标记 active；因此 SKIP 是空操作。
            # 在下一部开始前等待，而不是在这里直接 sleep，末部影片便不会空等。
            fetcher.finish_movie()
        stat[st] = stat.get(st, 0) + 1
        if st == "MISS":
            misses.append((f.name, msg))
        icon = {"OK": "✅", "SKIP": "⏭ ", "MISS": "❌"}[st]
        print(f"[{i:3}/{len(folders)}] {icon} {f.name[:40]:<42} {msg}", flush=True)

    dt = time.time() - t0
    print("─" * 92)
    print(f"Complete: succeeded {stat['OK']}  skipped {stat['SKIP']}  failed {stat['MISS']}"
          f"   elapsed {dt/60:.1f} min")
    if fetcher.throttled:
        slowed = {b: v for b, v in fetcher._delay.items()
                  if v > fetcher._base["img" if b.endswith(":img") else "html"]}
        print(f"Rate limiting: HTTP 429 occurred {fetcher.throttled} time(s)"
              + ("; slowed " + ", ".join(f"{b} → {v:.1f}s" for b, v in slowed.items())
                 if slowed else ""))
    if misses:
        print("\nUnmatched titles (manual review may be needed):")
        for n, m in misses:
            print(f"  · {n:<44} {m}")


if __name__ == "__main__":
    main()
