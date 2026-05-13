# CC Web MCP

CC Web MCP 是一个面向 Claude Code 第三方模型接入场景的轻量网页搜索和抓取 MCP。

它的主要用途是：当 Claude Code 接入 DeepSeek、Qwen、Kimi 等没有官方 `WebSearch` / `WebFetch` 能力的模型时，补上可访问国内外公开网页的只读工具链。官方 Claude 模型仍建议使用 Claude Code 原生搜索能力。

## 功能

- `web_search`：使用 DuckDuckGo HTML 搜索公开网页。
- `fetch_url`：抓取 `http/https` 页面并转为 Markdown，支持 `start_index` 分页读取。
- `research_brief`：先搜索，再抓取少量来源的短内容，减少上下文占用。
- `health_check`：检查依赖、配置和网络连通性。
- 可配置允许模型：通过 `config.json` 的 `allowed_model_patterns` 控制哪些模型能使用。
- 可选 Jina Reader fallback：普通抓取失败、403 或正文太短时，用 Jina Reader 作为备用读取通道。
- SSRF 安全边界：默认禁止抓取本机、内网、链路本地地址和云 metadata 地址，并检查重定向后的最终 URL。
- 内容类型分流：HTML 转 Markdown，文本/Markdown 直接清洗，JSON 格式化，PDF 和其他二进制类型默认拒绝。
- 相对链接转绝对链接：页面内 `/docs/xxx`、`../guide` 会按页面 URL 转成完整链接。
- 轻量缓存：默认按公开 URL 和提取模式缓存抓取结果，减少重复请求。

## 配置

编辑 `config.json`：

```json
{
  "allowed_model_patterns": ["deepseek"],
  "default_fetch_chars": 10000,
  "max_fetch_chars": 60000,
  "max_search_results": 10,
  "max_brief_sources": 3,
  "brief_chars_per_source": 2500,
  "brief_concurrency": 3,
  "dedupe_domains": true,
  "enable_jina_fallback": true,
  "jina_min_chars": 300,
  "allow_private_networks": false,
  "cache_ttl_seconds": 1800
}
```

如果要同时适用于更多模型：

```json
"allowed_model_patterns": ["deepseek", "qwen", "kimi"]
```

## Claude Code 注册

```powershell
claude mcp add --scope user --transport stdio cc-web -- py -3.11 E:\jc\cc_web_mcp\server.py
```

如果要使用指定 Python，请把路径替换为你自己的解释器位置：

```powershell
claude mcp add --scope user --transport stdio cc-web -- C:\Path\To\python.exe E:\jc\cc_web_mcp\server.py
```

## Hook 守卫

`hooks\guard.py` 可作为 Claude Code `PreToolUse` hook 使用。它会读取 `config.json`，只允许匹配 `allowed_model_patterns` 的模型调用 `mcp__cc_web__*` 工具。

## 测试

```powershell
py -3.11 -m pytest E:\jc\cc_web_mcp\tests -q
```

## 改进建议 / Roadmap

当前版本已经可以作为轻量 MVP 使用，但如果准备长期作为 DeepSeek / Qwen / Kimi 等第三方模型在 Claude Code 里的网页检索工具，建议优先补强以下工程点。

## 已完成的 Roadmap 项

- P0 安全边界：默认阻止 `localhost`、`127.0.0.0/8`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`、`::1`、`fc00::/7`、`fe80::/10` 等地址，并校验 30x 重定向后的 URL。如需访问内网文档，可显式配置 `allow_private_networks: true`。
- P0 Hook 阻断格式：`hooks/guard.py` 已输出 Claude Code `PreToolUse` 的 `hookSpecificOutput.permissionDecision = deny` 结构，降低后续 Claude Code 版本更新导致 hook 行为变化的风险。
- P1 内容类型分流：HTML、纯文本、Markdown、JSON 已分流处理；PDF 和未知二进制类型默认拒绝。
- P1 相对链接转绝对链接：Markdown 转换前会把 `<a href>` 解析成绝对链接。
- P2 `research_brief` 提效：支持同域名去重、并发抓取、失败来源保留错误信息。
- P2 缓存和重复抓取控制：默认开启公开 URL 抓取缓存，TTL 由 `cache_ttl_seconds` 控制。

## 后续 Roadmap

以下项目暂未纳入当前版本。

### P1：搜索后端可插拔

- 当前 `web_search` 使用 DuckDuckGo HTML，优点是无需 API key、实现轻量，但稳定性和搜索质量受 HTML 结构、限流、地区差异影响。
- 建议抽象搜索后端，保留 DuckDuckGo 作为默认免费后端，同时预留：
  - SearXNG
  - Tavily
  - Brave Search
  - Exa
  - Serper
- 配置可以类似：

```json
{
  "search_provider": "duckduckgo",
  "searxng_base_url": "",
  "tavily_api_key_env": "TAVILY_API_KEY",
  "brave_api_key_env": "BRAVE_API_KEY"
}
```

### P2：技术资料源加权

- 面向 coding agent 时，搜索结果最好偏向原始、高质量技术来源。
- 建议优先保留或加权：
  - 官方文档站点
  - GitHub 仓库、Issue、PR、Release
  - Stack Overflow
  - Read the Docs
  - PyPI / npm / crates.io 等包管理站点
  - 芯片厂商官网、SDK 文档、协议标准文档
- 可考虑降低搬运站、采集站、低质量 SEO 站点的优先级。

### P2：GitHub 专用工具

- 对开发场景来说，GitHub 网页直接转 Markdown 的效果不一定稳定。
- 后续可以增加专用工具：
  - `github_issue(owner, repo, number)`
  - `github_pr(owner, repo, number)`
  - `github_release(owner, repo)`
  - `github_file(owner, repo, path, ref)`
- 如果用户已经配置 GitHub MCP，也可以不重复实现，只在 README 中建议搭配 GitHub MCP 使用。

## 说明

- 这是只读工具链，不执行网页写入操作。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
