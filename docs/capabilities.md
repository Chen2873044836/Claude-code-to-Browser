# 工具能力与使用细节

## 工具

- `web_search(query, max_results=5, region="wt-wt", language="zh-cn")`
- `fetch_url(url, max_chars=None, start_index=0, extract_mode="auto")`
- `research_brief(query, max_sources=3, max_chars_per_source=None, region="wt-wt", language="zh-cn")`
- `health_check()`

`research_brief` 适合优先使用：它会先搜索，再抓取少量来源的短内容，比“搜索后逐个全文抓取”更节省上下文。

## 中国网络环境

如果本机网络访问 DuckDuckGo 不稳定，CC Web MCP 会按 `search_providers` 顺序继续尝试后续后端。默认配置会降级到 `bing_cn`，返回结果里会包含：

- `backend`：本次实际使用的搜索后端，例如 `bing_cn`。
- `search_scope_note`：当使用 `bing_cn` 时提醒模型这是区域偏置的 fallback，不等价于完整全球搜索。
- `fallback_reason`：触发降级的原因，例如 `duckduckgo_html failed: ...`。
- `attempted_backends`：每个搜索后端的尝试结果。

这样模型可以继续拿到可用资料，同时知道当前不是完整的 DuckDuckGo/全球搜索结果。

当前搜索后端包括 `duckduckgo`、`bing`、`bing_cn`、`searxng`、`mojeek` 和配置驱动的 `custom:<name>`。默认链路会先尝试 DuckDuckGo，再尝试国际版 Bing，最后才用 `bing_cn` 兜底。SearXNG 会优先使用 JSON 接口，JSON 被实例限流或关闭时会降级读取 HTML 结果页；Mojeek 使用公开 HTML 搜索入口，适合作为轻量 fallback；自定义后端适合接入第三方搜索 API 或自建搜索网关。

DuckDuckGo 后端内部会先尝试 HTML POST，再降级到 HTML GET，最后尝试 DuckDuckGo Lite 页面；这些都是公开网页入口，不需要 API key。HTTP/2 和 TLS 指纹随机化这类底层实验能力没有默认启用，避免把搜索稳定性建立在脆弱的私有实现细节上。

自定义后端会自动尝试常见 JSON 路径和字段名，也会在 `health_check` 中返回 `raw_result_count`、`usable_result_count`、命中的字段路径和业务错误信息。手动接 API 时，可以用 `cc-web-mcp config test-search custom:<name> "query"` 在命令行里先验证配置，再交给 Claude Code 实机调用。

如果开启 `search_parallel_enabled`，`web_search` 会并发请求前几个可用后端并去重合并结果，返回 `backend: "parallel:..."`、`aggregation.successful_backends`，并在重复命中的结果项里标注 `source_backends`。这个模式更接近 ddgs 的元搜索思路，适合网络不稳定但可以接受多发几个公开搜索请求的场景。

`fetch_url` 的 fallback 与 `web_search` 不同：普通搜索链路只在前一个搜索后端失败或空结果时进入下一个后端；抓取链路则是 `direct fetch -> Jina Reader -> search fallback`。开启 `enable_fetch_search_fallback` 后，只有目标 URL 命中配置的域名且直接抓取/Jina 都失败时，才会调用 `fetch_search_fallback_providers`。这适合把 `custom:zhihu` 放在普通搜索链路末尾，同时在抓取知乎正文失败时再定向使用知乎 API。

## 上下文友好的失败提示和分页

`fetch_url` 和 `web_search` 失败时会尽量返回给模型可直接使用的处理字段：

- `retryable`：是否值得稍后重试。
- `retry_after_seconds`：建议等待时间，仅在可能是临时网络问题时出现。
- `do_not_retry_reason`：告诉模型不要用同样参数立刻重复调用的原因。
- `recommended_next_action`：建议下一步，例如换来源、用 `research_brief`，或先跑 `health_check`。

`fetch_url` 返回内容被截断时，除了 `next_start_index`，还会返回 `truncation.next_call`。模型可以用里面的 `url`、`max_chars`、`start_index` 和 `extract_mode` 继续读取下一段，而不是重复读取同一段。

## 状态显示

`web_search`、`fetch_url` 和 `research_brief` 会在执行时向 Claude Code 发送 MCP progress/log 状态，例如正在搜索哪个后端、正在抓取哪个 URL、是否进入 Jina Reader fallback。Claude Code 是否把这些状态显示在 `Called cc-web ...` 折叠行附近，取决于当前 Claude Code 版本的 MCP 进度渲染；不改 Claude Code 源码时，cc-web 不能强制改写那一行 UI。

为了保证状态始终可见，工具返回 JSON 里也会包含：

- `status_summary`：一句话概括本次调用做了什么。
- `steps`：简短步骤列表，只记录搜索后端、抓取来源、fallback 等状态，不记录正文内容。

## 反爬、登录墙和超时

`fetch_url` 不会尝试绕过验证码、登录墙或 WAF。遇到知乎、微信公众号、X、Reddit 等强反爬或强登录站点时，轻量 HTTP 抓取可能返回 `403`、安全验证页、空正文或 `ReadTimeout`。

这类失败会尽量返回结构化诊断：

- `error_type`：例如 `captcha_or_challenge`、`login_required`、`blocked_or_waf`、`js_required`、`timeout_suspected_antibot`、`network_timeout`。
- `fetch_diagnostics.confidence`：`high` / `medium` / `low`，表示诊断置信度。
- `fetch_diagnostics.signals`：触发判断的证据，例如 `status_code=403`、`challenge keyword: 安全验证`、`known anti-bot domain: www.zhihu.com`。
- `fetch_diagnostics.recommendation`：给模型的处理建议，通常是改用搜索摘要、官方来源或其他可访问来源。

`ReadTimeout` 本身不能证明反爬；只有命中已知强反爬域名或其他页面特征时，才会标成 `timeout_suspected_antibot`。如果 Jina Reader fallback 也失败，cc-web 会优先保留原始目标站点的反爬诊断，避免被二次 fallback 的超时错误覆盖。

## 内容类型

- HTML：清理后转 Markdown。
- 纯文本和 Markdown：直接清洗。
- JSON：格式化后返回。
- PDF：默认拒绝；uvx 场景运行 `uvx cc-web-mcp init --runner uvx --with-pdf --force`，并开启 `enable_pdf_extract` 后，可用 `pypdf` 提取公开 PDF 文本；pip 环境可安装 `cc-web-mcp[pdf]`。

## 链接与缓存

Markdown 转换前会把 `<a href>` 解析成绝对链接。页面内 `/docs/xxx`、`../guide` 这类相对链接会按页面 URL 转成完整链接。

默认开启公开 URL 抓取缓存，TTL 由 `cache_ttl_seconds` 控制。Jina Reader fallback 结果不会写入原 URL 的直接抓取缓存，避免临时 fallback 掩盖后续恢复的原站点内容。

成功搜索结果也有独立短缓存，TTL 由 `search_cache_ttl_seconds` 控制，默认 `300` 秒。它只缓存成功搜索，失败、限流和全部后端不可用的结果不会写入缓存。触发 403/429、反爬挑战或网络失败的搜索后端会进入短期冷却，冷却期间优先尝试后续后端。
