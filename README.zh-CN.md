# JavLibrarian

一个轻量、安全优先的 JAV NAS 媒体库建设工具，用于整理本地影片目录并生成媒体中心可读取的元数据与图片。

[English](README.md) · **简体中文**

JavLibrarian 面向“每部影片一个文件夹”的媒体库：在内存中规范番号，同时抓取 JavBus 与 JavDB，合并双方元数据，并写出适配媒体中心的 NFO 和图片。主要适配绿联 UGOS 影视中心，同时通过文件夹级 `movie.nfo` 兼容 Emby、Jellyfin 与 Kodi。

项目有意优先保证行为可预测，而不是追求吞吐量：全程串行刮削、保守限流、自动跳过已完成文件夹，刮削主路径中不包含任何删除或视频内容修改操作。

## 核心能力

- 每部影片同时查询 JavBus 与 JavDB，按双方优势合并元数据。
- 同时生成 `movie.nfo` 和每个已识别视频的同名 NFO。
- 下载 `fanart.jpg`、生成 `poster.jpg`，并将剧照保存到 `Samples/`。
- 将 `-C`、`-U`、`-UC` 等文件名语义后缀保留为 NFO 标签。
- 接受元数据前，使用详情页自报番号反向校验本地推算结果。
- 文件夹和视频改名采用相互独立、默认只预览的工作流。
- 每次成功改名后立即写入与媒体根目录绑定的回滚映射表。
- 按“主机 + 请求类型”独立限流，并提供有上限的重试与退避。
- 最后原子写入 `movie.nfo`，使其成为可靠的完成标记。

## 安全模型

| 操作 | 默认行为 |
| --- | --- |
| 刮削 | 新增或替换元数据与图片；绝不删除视频，也不修改视频字节 |
| 已有 `movie.nfo` | 在联网、图片工具检查和影片间等待之前立即跳过整个文件夹 |
| 强制刷新 | 必须显式提供 `--force` |
| 文件夹改名 | 默认只预览，只有同时提供 `--apply` 才执行 |
| 视频改名 | 默认只预览；重复片源和无关文件只报告、不处理 |
| 回滚 | 校验映射表记录的媒体根目录是否与当前目录一致 |
| 图片或 NFO 流程中断 | 不提交 `movie.nfo`，下次运行仍会重试 |
| 改名日志写入 | 每次成功改名后立即原子落盘 |

对重要媒体库进行操作前，请先检查 dry run 和改名预览。文件系统或 NAS 快照仍然是防范硬件故障及工具之外误操作的最佳保护。

## 运行要求

| 要求 | 说明 |
| --- | --- |
| Python | 3.9 或更高版本 |
| 项目运行器 | `uv` |
| Python 直接依赖 | `requests>=2.32.5`，由 `pyproject.toml` 与 `uv.lock` 安装 |
| 图片处理 | macOS 自带 `sips`；没有该工具时使用 `--no-images` |
| 网络访问 | JavBus、JavDB 及页面引用的图片主机 |

JavLibrarian 有意使用 macOS 系统自带的 `sips`，不额外引入 Pillow，因此图片生成目前依赖 macOS。只生成元数据时不需要 `sips`。

## 安装

克隆或下载仓库后执行：

```bash
cd JavLibrarian
uv sync
uv run javlibrarian.py --help
```

请通过 `uv run` 启动脚本，以确保使用锁定的项目环境。本脚本有意不使用 PEP 723 内联元数据。

## 媒体库目录要求

媒体根目录的每个一级子目录应对应一部影片：

```text
/path/to/JAV/
├── SONE-035/
│   └── SONE-035.mp4
├── IPVR-256-C/
│   └── IPVR-256-C.mkv
└── FC2-PPV-1234567/
    └── FC2-PPV-1234567.mp4
```

支持的视频扩展名：

```text
.mp4  .mkv  .avi  .wmv  .mov  .m4v  .ts  .iso  .rmvb  .flv
```

隐藏目录会被忽略。刮削时只在内存中清洗番号；只有显式进入改名工作流才会改变文件夹名称。

## 快速开始

先检查番号识别结果，不联网、不写盘：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --dry-run
```

再试跑前 5 个文件夹：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --limit 5
```

处理整个媒体库：

```bash
uv run javlibrarian.py --dir "/path/to/JAV"
```

只处理指定文件夹：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" \
  --only "SONE-035" \
  --only "IPVR-256-C"
```

只生成 NFO，不下载或处理图片：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --no-images
```

### 默认媒体目录

`--dir` 的优先级最高。需要重复运行时，可以设置 `JAVLIBRARIAN_DIR`：

```bash
export JAVLIBRARIAN_DIR="/path/to/JAV"
uv run javlibrarian.py --dry-run
uv run javlibrarian.py
```

`export` 设置的环境变量只在当前 shell 及其子进程中有效。只有确实需要持久的 shell 默认值时，才应将其加入相应的 shell 启动文件。

## 生成的文件

一个成功处理的文件夹结构如下：

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

- `{视频名}.nfo` 适配要求 NFO 与视频同名的媒体中心，包括 UGOS。
- `movie.nfo` 适配 Emby、Jellyfin、Kodi 等文件夹级读取器。
- `fanart.jpg` 是横版封面。
- `poster.jpg` 是竖版海报。普通影片从横版封面的正面区域裁剪；VR 影片优先从剧照中识别独立的竖版封面。
- `Samples/` 保存有效剧照，默认下载全部剧照。

NFO 会在数据可用时写入番号、显示标题、原始标题、发行日期与年份、时长、制作商、发行商、导演、系列、类别、语义标签、演员、图片引用、数据源和原始文件夹名。

全部图片任务和视频同名 NFO 写入完成后，程序才会原子提交 `movie.nfo`。如果该文件已经存在，除非提供 `--force`，否则会立即跳过整个文件夹。

## 请求与限流策略

默认值均可通过命令行覆盖：

| 范围 | 默认值 | 说明 |
| --- | ---: | --- |
| HTML 请求 | 5 秒 | 每个主机独立计时 |
| 图片请求 | 2 秒 | 与 HTML 使用不同计时桶 |
| 实际刮削影片 | 10 秒 | 仅在真正进入联网刮削的影片之间计算 |

第一部联网影片不等待；纯本地跳过项既不等待，也不重置影片计时；最后一部处理完成后不会再空等。

HTTP 408、429、500、502、503、504 会重试，最多尝试 5 次。退避从 10 秒开始，逐次翻倍，最高 300 秒。出现 429，以及适用情况下的 503 后，对应“主机 + 类型”计时桶会在本次运行内永久放慢 1.5 倍，基础间隔最高 30 秒。永久性客户端错误会立即返回。

## 文件夹与视频改名

文件夹和视频改名是相互独立、默认只预览的工作流。

预览文件夹标准化：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --rename-folders
```

执行已经检查过的文件夹改名：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --rename-folders --apply
```

预览并执行安全的视频文件名清理：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --rename-videos
uv run javlibrarian.py --dir "/path/to/JAV" --rename-videos --apply
```

回滚最近一个批次：

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --undo-folders
uv run javlibrarian.py --dir "/path/to/JAV" --undo-videos
```

如需回滚全部记录批次，在对应的撤销命令后增加 `--undo-all`。

默认映射表：

| 工作流 | 映射表 |
| --- | --- |
| 文件夹改名 | `folder_rename_log.json` |
| 视频改名 | `video_rename_log.json` |

映射表默认保存在脚本旁边，包含本地路径和媒体文件名，并已通过 `.gitignore` 排除。只要仍可能需要回滚，就应保留这些文件。可通过 `--folder-log` 或 `--video-log` 指定其他路径。

## 命令行参数

| 参数 | 用途 |
| --- | --- |
| `--dir PATH` | 媒体根目录；优先于 `JAVLIBRARIAN_DIR` |
| `--dry-run` | 只解析文件夹名；不联网、不写盘 |
| `--limit N` | 只处理筛选结果中的前 N 个文件夹 |
| `--only NAME` | 按完整文件夹名筛选；可重复提供 |
| `--delay SECONDS` | HTML 请求间隔；默认 5.0 |
| `--img-delay SECONDS` | 图片请求间隔；默认 2.0 |
| `--movie-delay SECONDS` | 联网影片之间的间隔；默认 10.0 |
| `--force` | 处理已有 `movie.nfo` 的文件夹，并替换已有 NFO 产物 |
| `--no-images` | 只生成 NFO，不处理图片 |
| `--max-samples N` | 每部影片最多下载的剧照数；0 表示全部 |
| `-v`、`--verbose` | 显示限流和等待细节 |
| `--rename-folders` | 预览文件夹名标准化 |
| `--rename-videos` | 预览安全的视频文件名清理 |
| `--apply` | 执行选定的改名预览 |
| `--undo-folders` | 回滚最近一个文件夹改名批次 |
| `--undo-videos` | 回滚最近一个视频改名批次 |
| `--undo-all` | 回滚所选撤销工作流的全部批次 |
| `--folder-log PATH` | 指定文件夹改名映射表路径 |
| `--video-log PATH` | 指定视频改名映射表路径 |

## 元数据来源

JavLibrarian 会同时查询两个来源，而不是将其中一个仅作为失败回退：

- **JavBus** 提供主要元数据骨架、影片发行时使用的演员名与头像，以及较稳定的封面信息。
- **JavDB** 补充标题、系列、类别，以及 JavBus 可能缺失的图片资源。

程序不会直接采信搜索结果顺序。只有详情页自报番号与本地规范化番号一致时，才会接受该结果。

网站可能随时调整 HTML。解析失败会按文件夹报告，不会触发破坏性清理。

## 测试

运行现有离线测试：

```bash
uv run test_throttle.py
```

测试使用假 HTTP Session、假时钟和系统临时目录，不会访问真实元数据站点。覆盖内容包括重试策略、请求计时桶、影片间隔、备用图片源、图片与 NFO 原子提交、回滚收敛，以及已有 `movie.nfo` 的快速跳过路径。

## 隐私与运行说明

- 改名映射表包含本地文件系统路径和媒体文件名。它们已经被 Git 忽略，但仍应按私人数据管理。
- JavLibrarian 不要求账户凭据。
- 刮削会向公开元数据来源发送番号查询，并在未使用 `--no-images` 时下载页面引用的图片。
- 项目不保留元数据缓存；强制刷新会重新获取当前来源数据。
- 请遵守适用法律、来源网站条款和网络策略，仅管理自己有权处理的媒体。

## 已知限制

- 图片处理依赖 macOS `sips`。
- 元数据解析依赖 JavBus 与 JavDB 当前的 HTML 结构。
- 请求有意串行且保守，大型媒体库需要较长时间。
- 扫描器要求每部影片位于媒体根目录的一个一级子目录中。
- 重复片源和无关文件必须人工判断，程序绝不自动解决。
- 本项目是命令行工具，不包含计划任务、后台守护进程或图形界面。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
