# CC Web MCP

CC Web MCP 是一个面向 Claude Code 第三方模型接入场景的轻量网页搜索和抓取 MCP。

它的主要用途是：当 Claude Code 接入 DeepSeek、Qwen、Kimi 等没有官方 `WebSearch` / `WebFetch` 能力的模型时，补上可访问国内外公开网页的只读工具链。官方 Claude 模型仍建议使用 Claude Code 原生搜索能力。

## 功能概览

- `web_search`：按配置的搜索后端顺序搜索公开网页，默认 `duckduckgo -> bing_cn`。
- `fetch_url`：抓取 `http/https` 页面并转为 Markdown，支持 `start_index` 分页读取。
- `research_brief`：先搜索，再抓取少量来源的短内容，减少上下文占用。
- `health_check`：检查依赖、配置和网络连通性。
- 模型路由：通过 `allowed_model_patterns`、启动指令和 hook 守卫，让 DeepSeek、Qwen、Kimi 等第三方模型优先走 cc-web，官方 Claude 默认继续走原生 `WebSearch/WebFetch`。
- 安全边界：默认禁止抓取本机、内网、链路本地地址和云 metadata 地址，并检查 DNS 解析和重定向后的最终 URL。

## 快速开始

以下命令以 Windows PowerShell 和 `py -3.11` 为例。`<安装目录>` 请替换为你自己的项目路径。

```powershell
git clone https://github.com/JcDizzy/CC-Web-MCP.git <安装目录>
cd <安装目录>
py -3.11 -m pip install -r requirements.txt
claude mcp add --scope user --transport stdio cc-web -- py -3.11 .\server.py
```

如果要使用指定 Python，请把路径替换为你自己的解释器位置：

```powershell
claude mcp add --scope user --transport stdio cc-web -- <Python解释器路径> .\server.py
```

安装第三方模型路由指令和 hook 守卫：

```powershell
py -3.11 .\scripts\install_instructions.py
py -3.11 .\scripts\install_hook.py
```

这两个脚本会更新用户级 `~\.claude\CLAUDE.md` 和 `~\.claude\settings.json`。`install_hook.py` 会在写入前创建 `settings.json.cc-web-backup.<时间戳>` 备份，可以重复运行。

确认 MCP 已注册：

```powershell
claude mcp get cc-web
```

在 Claude Code 中调用 `health_check`，确认依赖、配置和网络连通性。也可以在命令行先做一次本地诊断：

```powershell
py -3.11 .\scripts\doctor.py
```

如果只想看 JSON 结果，并暂时跳过真实网络访问：

```powershell
py -3.11 .\scripts\doctor.py --json --skip-network
```

## 第一次验证建议

安装完成后，建议先用第三方模型在 Claude Code 里做一次小范围联网任务，确认路由是否生效：

```text
使用 cc-web 查询 “Claude Code MCP PreToolUse hook permissionDecision”，先用 research_brief 获取资料概览，再总结当前推荐写法。
```

如果模型仍尝试调用原生 `WebSearch`，说明启动指令可能没有生效，先检查 `~\.claude\CLAUDE.md`。如果模型尝试调用原生 `WebFetch` 并被拦截，说明 hook 已生效；模型应根据提示改用 `cc-web fetch_url`。

建议优先让模型调用 `research_brief`，只有某个来源确实关键时，再用 `fetch_url` 单独读取完整页面。

## 基础配置

编辑 `config.json`：

```json
{
  "allowed_model_patterns": ["deepseek"],
  "search_providers": ["duckduckgo", "bing_cn"],
  "allow_fetch_url_for_claude": false,
  "block_native_web_for_allowed_models": true
}
```

常用调整：

- 同时适配更多第三方模型：`"allowed_model_patterns": ["deepseek", "qwen", "kimi"]`
- DuckDuckGo 不稳定时只使用 Bing 中文入口：`"search_providers": ["bing_cn"]`
- 某个第三方 API 的原生 Web 工具已经可用时：`"block_native_web_for_allowed_models": false`
- 明确允许官方 Claude 调用 `cc-web fetch_url`：`"allow_fetch_url_for_claude": true`

完整配置说明见 [docs/configuration.md](docs/configuration.md)。

## 测试

```powershell
py -3.11 -m pip install -r requirements-dev.txt
py -3.11 -m pytest .\tests -q
```

## 文档

- [安装与验证](docs/installation.md)
- [配置说明](docs/configuration.md)
- [Claude Code 路由、Hook 与自动授权](docs/routing-and-permissions.md)
- [工具能力与使用细节](docs/capabilities.md)
- [安全说明](docs/security.md)
- [Roadmap](docs/roadmap.md)

## 重要边界

- `bing_cn` 是实用降级，不是全球搜索的等价替代。
- `WebSearch` 在部分第三方 Anthropic-compatible API 中会在服务端直接报错，Claude Code 本地 hook 拦截不到；需要依赖 `CLAUDE.md` 启动指令提前绕开。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
