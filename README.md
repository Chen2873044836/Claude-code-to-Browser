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
  "enable_jina_fallback": true,
  "jina_min_chars": 300
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

## 说明

- 这是只读工具链，不执行网页写入操作。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
