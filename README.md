<h1 align="center">SakuraMedia JavRanking 影片排行榜</h1>

<p align="center">SakuraMedia 社区插件：从 JavRanking 公开榜单抓取番号，自动补齐影片资料并写入排行榜。</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT">
  <img src="https://img.shields.io/badge/version-1.3.2-green" alt="Version: 1.3.2">
  <img src="https://img.shields.io/badge/Host_API-18-orange" alt="Host API 18">
</p>

## 这是什么

一个 SakuraMedia 排行榜来源插件。它读取 [JavRanking](https://javranking.cc/zh-hans/rankings/index.md) 公开 Markdown 页面里的四个榜单番号，交给 SakuraMedia 宿主：已有影片直接复用，缺的番号走已启用的元数据源补资料，最后写入排行榜。

- 来源：`javranking_cc`，周期固定 `all`
- 榜单：DMM 本周热销（`dmm_weekly`）、JavRanking 本周热播（`weekly_hot`）、JavLibrary TOP250（`javlibrary`）、全站神作总榜 TOP 100（`awarded`）
- 调度：默认每周一 04:20 依次同步四榜；也可手动同步全部或单个榜单

## 快速安装

前置条件：SakuraMedia 后端（Host API 18，镜像 0.16.0 验证通过）；Python >= 3.10；无需额外依赖包。

方式一，插件管理页上传 Release 中的 ZIP（不要解压），安装后重启 API 与 APS。

方式二，命令行（容器名和路径换成实际值）：

```sh
docker cp 'sakuramedia_javranking-1.3.2.zip' <容器>:/tmp/javranking.zip
docker exec <容器> python /app/cli.py plugins install /tmp/javranking.zip
```

## 快速开始

1. 安装并重启后，打开 SakuraMedia「任务管理」，手动触发 **同步 JavRanking 全部四个榜单**；或先试最小榜：

```sh
python /app/cli.py aps javranking-board --params-json '{"board_key":"dmm_weekly"}'
```

2. 等任务显示 completed（`queued` 只表示排队）。

3. 打开「榜单 → 筛选 → 来源 JavRanking」，周期选「全部」，应能看到 DMM 本周热销的影片。

预期输出：任务结果里 `fetched_numbers` 是抓到的番号数，`stored_items` 是写入榜单数；两者可能不同，差值就是 `skipped_movies`（未能补齐资料的番号数），这不是抓取失败。字段名以实际任务结果为准。

## 同步与更新

- 每榜重新读取最新名单更新名次；已存在的影片直接复用本地资料，只有本地缺少的番号才调用已启用的元数据源。
- 下榜不会删除影片。
- 单榜重试命令同上，把 `board_key` 换成表中任意值。

## 项目结构

```text
sakuramedia_javranking/   插件源码（manifest、注册、抓取）
tests_javranking/         单元回归与验收工具
javranking-release/       打包脚本 build.py（输出 dist/）
```

## 适用场景

适合：想让 SakuraMedia 排行榜多一个公开榜单来源；能接受部分影片因元数据源不可达而跳过。

不适合：期望 100% 影片入库——覆盖率取决于已启用的元数据源（独立空库实测仅默认 JavBus/AVMOO 源时 DMM 周榜写入 8–11/84 条）；需要下载影片或抓取图片——本插件不做这两件事。

## 已知限制

- 入库覆盖率取决于已启用的元数据源。独立空库实测中，仅默认 JavBus/AVMOO 源时 DMM 周榜写入 8–11/84 条；未配置代理或元数据源不可达时覆盖率更低。这不是榜单抓取失败，跳过数会如实记录。
- ARM64 未测试。验证仅在 Linux amd64、SakuraMedia 0.16.0 上进行。
- 全站神作总榜需逐条解析 100 个公开影片详情页获取番号，首次同步较慢；结果缓存在插件 `data/awarded-numbers.json`，缓存不可写时自动退化为内存模式（当次可用、下次重解析）。
- 榜单低于安全下限、表格格式变化或候选影片均无法解析时不覆盖旧榜。
- 上游站点允许缺片，部分番号可能永远无法匹配到影片资料。

## 开发与测试

```sh
# 构建发布包（输出 dist/，含 .sha256）
python javranking-release/build.py

# 单元回归（需要 SakuraMedia 后端源码路径）
SAKURA_BACKEND=/path/to/sakuramediabe python3 -m pytest -q tests_javranking
```

打包脚本只收录 `sakuramedia_javranking/` 下四个发布文件并校验 ZIP 根布局。

## 贡献

欢迎 Issue 与 PR；提交前请跑通上面的回归测试。

## License

[MIT](LICENSE)。榜单数据来自 [JavRanking](https://javranking.cc/zh-hans/) 公开页面，本项目不复制、不再分发站点内容，不用于商业用途。SakuraMedia 是 tinypinglite 的项目；本插件为独立社区插件，未经官方审计或背书。
