# CC-Web-MCP（优化版）

> 基于 [JcDizzy/CC-Web-MCP](https://github.com/JcDizzy/CC-Web-MCP) 的优化版本，已提交 PR 至原仓库。

## 这是什么

CC-Web-MCP 是一个为 **Claude Code** 设计的本地网页搜索和抓取 MCP 工具链。

**解决的问题：** 当 Claude Code 接入 DeepSeek、Qwen、Kimi 等第三方模型时，这些模型没有官方的 WebSearch/WebFetch 能力，无法联网。CC-Web-MCP 补上了这个缺口，让第三方模型也能搜索网页、抓取内容。

**核心功能：**
- `web_search` - 搜索公开网页
- `fetch_url` - 抓取网页内容并转为 Markdown
- `research_brief` - 快速调研工具，搜索并提取关键摘要
- `health_check` - 检查依赖和网络连通性

## 快速上手

### 安装（推荐方式）

```bash
uvx cc-web-mcp init --runner uvx
```

### 验证安装

```bash
uvx cc-web-mcp doctor
```

### 在 Claude Code 中使用

安装完成后重启 Claude Code，直接使用：

```
使用 cc-web 搜索 "某个技术问题"
```

模型会自动调用 `mcp__cc-web__web_search` 或 `mcp__cc-web__research_brief`。

## 优化内容

本版本在原版基础上做了以下优化：

### 速度优化

| 优化项 | 原值 | 新值 | 效果 |
|--------|------|------|------|
| HTTP 超时 | 15 秒 | 8 秒 | 后端卡住时等待时间减半 |
| 并行搜索 | 关闭 | 开启 | 同时请求 DuckDuckGo + Bing，速度翻倍 |
| 搜索缓存 | 300 秒 | 600 秒 | 相同查询 10 分钟内直接返回缓存 |
| 默认抓取字符 | 10000 | 15000 | 减少分页次数 |

### 调用主动性优化

- **工具描述**：从"仅供第三方模型使用"改为正向功能说明，模型更愿意主动调用
- **MCP 指令**：从"不要主动使用"改为"当需要获取最新信息时，应主动使用"
- **CLAUDE.md 模板**：从英文否定指令改为中文正向引导
- **Claude 可用 fetch_url**：默认允许官方 Claude 使用 `fetch_url`

### 配套修复

- 更新 doctor 检查逻辑，适配新的 CLAUDE.md 模板
- 更新测试用例，全部 201 个测试通过

## 原作者

- **原仓库**：[JcDizzy/CC-Web-MCP](https://github.com/JcDizzy/CC-Web-MCP)
- **原作者**：[JcDizzy](https://github.com/JcDizzy)
- **优化者**：[Chen2873044836](https://github.com/Chen2873044836)
- **优化 PR**：[#3](https://github.com/JcDizzy/CC-Web-MCP/pull/3)

## 技术栈

- Python 3.11+
- MCP (FastMCP) - MCP Server 框架
- httpx - 异步 HTTP 客户端
- beautifulsoup4 - HTML 解析
- markdownify - HTML 转 Markdown

## 搜索后端

默认按顺序尝试：`DuckDuckGo → Bing → Bing_cn`

支持自定义搜索 API、SearXNG、Mojeek 等。

## 安全特性

- 默认禁止抓取内网地址
- DNS 解析后二次校验 IP
- 302 重定向后再次安全检查
- 反爬检测和诊断

## 文档

- [安装与验证](docs/installation.md)
- [配置说明](docs/configuration.md)
- [路由与 Hook](docs/routing-and-permissions.md)
- [工具能力](docs/capabilities.md)
- [安全说明](docs/security.md)

## License

MIT
