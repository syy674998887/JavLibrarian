<h1 align="center">JavLibrarian</h1>

<p align="center">
  <b>轻量、安全优先的 JAV NAS 媒体库建设工具。</b>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="Apache 2.0"></a>
  <a href="https://docs.astral.sh/uv/"><img src="https://img.shields.io/badge/uv-lockfile-DE5FE9" alt="uv"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

JavLibrarian 用于整理 NAS 上的 JAV 媒体库：从文件夹名识别番号，查询 JavBus 与 JavDB，并生成媒体中心可读取的 NFO 与图片。视频同名 NFO 适配绿联 UGOS 影视中心（需开启「优先读取本地信息」），文件夹级 `movie.nfo` 兼容 Emby / Jellyfin / Kodi。

---

## 目录

- [安装](#安装)
- [媒体库结构](#媒体库结构)
- [命令参考](#命令参考)
- [快速开始](#快速开始)
- [生成的文件](#生成的文件)
- [元数据来源与合并规则](#元数据来源与合并规则)
- [文件夹与视频改名](#文件夹与视频改名)
- [隐私](#隐私)
- [测试](#测试)
- [已知限制](#已知限制)
- [许可证](#许可证)

---

## 安装

```bash
git clone https://github.com/syy674998887/JavLibrarian.git
cd JavLibrarian
uv sync
uv run javlibrarian --help
```

支持 Python 3.11+；macOS、Windows 与 Linux 使用相同命令。

---

## 媒体库结构

`--dir` 指定媒体库根目录。程序只扫描其下的一级文件夹，番号从文件夹名中识别，不会递归处理更深层目录。隐藏文件夹会被忽略；无法识别番号的文件夹会由 `inspect` 报告，`scrape` 和两种 `rename-*` 不处理。

```text
/path/to/JAV/
├── SONE-035/
│   └── SONE-035.mp4
├── IPVR-256-C/
│   └── IPVR-256-C.mkv
└── FC2-PPV-1234567/
    └── FC2-PPV-1234567.mp4
```

番号规范化只用于查询和 NFO；`-C`、`-U`、`-UC`、`-leak` 等文件夹语义会写入 NFO 标签，`scrape` 不会改变文件夹或视频名称。

程序只识别一级文件夹内的视频文件，扩展名不区分大小写：

`.mp4` `.mkv` `.avi` `.wmv` `.mov` `.m4v` `.ts` `.iso` `.rmvb` `.flv`

视频文件名无需与文件夹名一致。同一文件夹内的多个受支持视频共用文件夹元数据，并分别生成视频同名 NFO。

---

## 命令参考

```bash
uv run javlibrarian COMMAND [OPTIONS]
```

| 命令 | 用途 |
| --- | --- |
| `scrape` | 查询元数据并生成 NFO 与图片 |
| `inspect` | 显示从文件夹名识别的查询番号与标签 |
| `rename-folders` | 标准化一级文件夹名称 |
| `rename-videos` | 清理视频及匹配附属文件的名称 |
| `undo-folders` | 回滚最近一批文件夹改名 |
| `undo-videos` | 回滚最近一批视频改名 |

> [!IMPORTANT]
> `inspect` 不联网、不写盘。`scrape` 会联网并写入 NFO 与图片，但不会删除或改写视频。两种改名和两种回滚命令默认只预览，必须提供 `--apply` 才会执行。

### 目录与筛选

| 参数 | 可用命令 | 用途 |
| --- | --- | --- |
| `--dir PATH` | 全部 | 媒体库根目录；未提供时读取 `JAVLIBRARIAN_DIR` |
| `--limit N` | `scrape`、`inspect`、两种 `rename-*` | 在应用 `--only` 后，最多处理按文件夹名不区分大小写排序的前 N 项；`0`（默认）表示全部 |
| `--only NAME` | `scrape`、`inspect`、两种 `rename-*` | 只处理指定番号对应的一级文件夹；`NAME` 必须是完整文件夹名且区分大小写，可重复提供 |

### 刮削

以下参数只属于 `scrape`：

| 参数 | 用途 |
| --- | --- |
| `--force` | 重新处理已有 `movie.nfo` 的文件夹，并替换本次成功生成的同名 NFO 与图片 |
| `--page-delay SECONDS` | 同一元数据来源连续页面请求之间的基础间隔；默认 `5.0` 秒，JavBus 与 JavDB 分别计时 |
| `--image-delay SECONDS` | 同一图片主机连续请求之间的基础间隔；默认 `2.0` 秒 |
| `--delay SECONDS` | 联网刮削的影片之间的间隔；默认 `10.0` 秒 |
| `-v`、`--verbose` | 显示请求等待、影片间等待、自动减速和重试信息 |

延迟值必须是有限的非负数。`0` 只关闭对应的基础间隔，重试退避仍可能等待。

HTTP 408、429、500、502、503、504 与网络异常最多重试 5 次。退避从 10 秒开始逐次翻倍，最高 300 秒；429 的纯数字 `Retry-After` 会优先采用。每次 429 或 503 会将受影响的非零「主机 + 请求类型」基础间隔乘以 1.5，最高 30 秒；其他 4xx 不重试。

### 改名与回滚

| 参数 | 可用命令 | 用途 |
| --- | --- | --- |
| `--apply` | 两种 `rename-*`、两种 `undo-*` | 执行当前显示的改名或回滚计划 |
| `--journal PATH` | 两种 `rename-*`、对应的 `undo-*` | 指定回滚日志；回滚时使用改名命令写入的同一文件 |

每次 `undo-*` 只处理对应日志中的最近批次；再次运行可继续回滚上一批。

---

## 快速开始

```bash
uv run javlibrarian inspect --dir "/path/to/JAV"
uv run javlibrarian scrape --dir "/path/to/JAV"
```

---

## 生成的文件

```text
SONE-035/
├── SONE-035.mp4
├── SONE-035.nfo
├── movie.nfo
├── fanart.jpg
├── poster.jpg
└── Samples/
    ├── sample1.jpg
    └── ...
```

| 文件 | 作用 |
| --- | --- |
| `{视频名}.nfo` | 供按视频同名 NFO 读取的媒体中心使用，如绿联 UGOS 影视中心 |
| `movie.nfo` | 兼容 Emby / Jellyfin / Kodi 的文件夹级 NFO，同时作为刮削完成标记 |
| `fanart.jpg` | 横版封面 |
| `poster.jpg` | 竖版海报 |
| `Samples/` | 页面剧照 |

图片和视频同名 NFO 完成后，程序最后原子写入 `movie.nfo`。执行中断时未生成该文件的文件夹会在下次运行重新处理。

---

## 元数据来源与合并规则

元数据来源为 [JavBus](https://www.javbus.com) 和 [JavDB](https://javdb.com)。只命中一个来源时直接使用该来源；双源都命中时以 JavBus 为主记录，由 JavDB 补充缺失字段和备用图片。

### 来源校验

来源结果报告的番号必须与本地规范化番号一致。常规字母加数字番号的比较不区分大小写和分隔符，并忽略数字部分的前导零，例如 `IPVR-256` 与 `ipvr_0256` 视为相同。两站都没有有效结果或处理发生异常时，该文件夹会报告失败。

### 字段合并

| 数据 | 合并规则 |
| --- | --- |
| 标题 | JavBus 标题写入 `originaltitle`；JavDB 标题不含日文假名时用作显示标题，否则使用主记录标题 |
| 发行日期、时长、制作商、发行商、导演、系列 | 保留 JavBus 已有值，仅用 JavDB 填补空缺 |
| 类别 | 合并两站类别并去重，JavBus 顺序在前 |
| 演员 | 使用 JavBus 演员与头像；仅在 JavBus 没有演员时使用 JavDB 女优名单 |
| 封面 | JavBus 为主源；下载失败时尝试 JavDB 封面 |
| 剧照 | JavBus 为主源，JavDB 同序号图片作为备源；JavBus 没有剧照时使用 JavDB |
| 数据源标记 | 按实际命中结果写为 `javbus`、`javdb` 或 `javbus+javdb` |

### 图片与海报

图片下载失败、无法解码或短边不足 200 像素时不会覆盖已有文件；存在备用来源时继续尝试。有效图片通过临时文件校验后再写入目标。

- 普通影片从横版封面右侧裁取宽度的 47.5% 作为 `poster.jpg`。
- VR 影片优先以 DMM `ps.jpg` 为参照，从剧照中识别竖版封面；没有可用参照时选择第一张竖图，最后再回退到横版封面裁剪。

---

## 文件夹与视频改名

文件夹与视频工作流使用独立的回滚日志。每项改名会在触碰文件系统前原子写入日志；回滚时会验证媒体库根目录，并区分已完成、未开始和部分完成的记录。

视频及其同名字幕（包括 `SONE-035.chs.srt` 这类带语言标记的字幕）、视频同名 NFO 会作为一组处理，文件夹级 `movie.nfo` 不参与改名。任一目标已被占用时整组跳过；回滚不会覆盖现有文件。

---

## 隐私

- 刮削会向 JavBus 与 JavDB 发送番号查询，并下载页面引用的图片。
- 改名回滚日志包含本地路径和媒体文件名。项目默认日志路径已被 Git 忽略，其他路径需自行保护。

---

## 测试

```bash
uv run --group test pytest
```

测试完全离线，不访问真实元数据站点。

---

## 已知限制

- 元数据解析依赖 JavBus 与 JavDB 当前的 HTML 结构。
- 请求有意串行且保守，大型媒体库需要较长时间。

---

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
