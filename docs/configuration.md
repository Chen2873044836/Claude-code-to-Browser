# 配置说明

配置文件默认位于用户配置目录，不再依赖仓库根目录的 `config.json`。

- Windows：`%APPDATA%\cc-web-mcp\config.json`
- macOS/Linux：`~/.config/cc-web-mcp/config.json`

查看当前路径：

```powershell
cc-web-mcp config path
```

首次创建配置：

```powershell
cc-web-mcp config init
```

也可以通过 `CC_WEB_MCP_CONFIG` 指向自定义配置文件。

```json
{
  "allowed_model_patterns": ["deepseek"],
  "search_providers": ["duckduckgo", "bing", "bing_cn"],
  "allow_fetch_url_for_claude": false,
  "block_native_web_for_allowed_models": true,
  "searxng_base_url": "",
  "prefer_technical_sources": true,
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
  "cache_ttl_seconds": 1800,
  "search_cache_ttl_seconds": 300,
  "search_backend_cooldown_seconds": 60,
  "search_parallel_enabled": false,
  "search_parallel_max_backends": 2,
  "trust_tun_fake_ip_dns": false,
  "trusted_proxy_domains": [],
  "enable_pdf_extract": false
}
```

## 模型与路由

`allowed_model_patterns` 控制哪些模型被视为应该使用 cc-web 的第三方模型。匹配方式是大小写不敏感的关键词包含匹配。

```json
"allowed_model_patterns": ["deepseek", "qwen", "kimi"]
```

`allow_fetch_url_for_claude` 默认是 `false`。这会让官方 Claude 继续优先使用 Claude Code 内置 `WebSearch/WebFetch`，避免自动误选 cc-web。只有你明确希望官方 Claude 也可以调用 `cc-web fetch_url` 时，才改成：

```json
"allow_fetch_url_for_claude": true
```

即使打开这个开关，`web_search` 和 `research_brief` 仍建议只给 `allowed_model_patterns` 中匹配的第三方模型使用。

`block_native_web_for_allowed_models` 默认是 `true`。当当前模型匹配 `allowed_model_patterns` 时，守卫会阻止它调用 Claude Code 原生 `WebFetch`，并提示改用 `cc-web`。注意：部分第三方 Anthropic-compatible API 会在服务端直接拒绝 `WebSearch`，请求到不了 Claude Code 本地工具执行层，因此 `WebSearch` 必须靠 `CLAUDE.md` 启动指令提前绕开。

如果某个第三方 API 的原生 Web 工具已经可用，可以改成：

```json
"block_native_web_for_allowed_models": false
```

`health_check` 会在 `config` 字段里返回 `allow_fetch_url_for_claude` 和 `block_native_web_for_allowed_models`，方便排查当前路由策略。

## 搜索后端

`search_providers` 是推荐配置，表示按顺序尝试多个搜索后端。旧版 `search_provider` 仍兼容，但不建议新配置继续使用单后端字段。

默认搜索链路：

```json
"search_providers": ["duckduckgo", "bing", "bing_cn"]
```

`duckduckgo` 后端内部会先尝试 DuckDuckGo HTML POST，再尝试 HTML GET，最后尝试 DuckDuckGo Lite 页面。这样能吸收 ddgs 的公开入口降级思路，同时避免默认启用 HTTP/2/TLS 底层指纹随机化这类维护风险更高的实验手段。

如果当前网络无法访问 DuckDuckGo，可以保留默认降级链路，也可以直接只使用 Bing 中文入口：

```json
"search_providers": ["bing_cn"]
```

`bing_cn` 是实用 fallback，不是完整 DuckDuckGo/全球搜索结果的等价替代。使用 `bing_cn` 时，工具返回会包含 `search_scope_note` 提醒模型当前结果可能有区域偏置。

如果你希望增加一个不依赖账号的英文公开搜索 fallback，可以把 Mojeek 放到链路后面：

```json
"search_providers": ["duckduckgo", "bing", "mojeek", "bing_cn"]
```

`mojeek` 使用公开 HTML 搜索入口，适合作为轻量补充，不等价于付费搜索 API。

如果你有 SearXNG 实例，可以改为：

```json
{
  "search_providers": ["searxng", "duckduckgo", "bing", "bing_cn"],
  "searxng_base_url": "https://your-searxng.example"
}
```

`searxng` 会优先尝试 JSON 搜索接口；如果实例禁用了 JSON 输出，会自动降级读取 HTML 结果页。

`health_check` 会返回 `search_providers`、`search_backend_status` 和 `first_available_search_backend`，方便你一眼判断当前环境到底能用哪个搜索后端。`429` 这类限流状态会被视为不可用，避免误把暂时不可搜索的后端排在第一位。

## 抓取与摘要

- `default_fetch_chars`：`fetch_url` 默认返回字符数。
- `max_fetch_chars`：单次抓取允许返回的最大字符数。
- `max_search_results`：搜索工具最多返回的结果数。
- `max_brief_sources`：`research_brief` 最多抓取的来源数。
- `brief_chars_per_source`：`research_brief` 每个来源最多保留的字符数。
- `brief_concurrency`：`research_brief` 并发抓取数量。
- `dedupe_domains`：`research_brief` 是否按域名去重。

## 自定义搜索 API

如果你有第三方搜索 API 或自建搜索网关，可以通过 `custom_search_apis` 手动增加后端，然后在 `search_providers` 里使用 `custom:<name>`。

```json
{
  "search_providers": ["custom:brave", "searxng", "bing"],
  "custom_search_apis": {
    "brave": {
      "url": "https://api.search.brave.com/res/v1/web/search",
      "method": "GET",
      "headers": {
        "X-Subscription-Token": "${BRAVE_SEARCH_API_KEY}"
      },
      "params": {
        "q": "{query}",
        "count": "{max_results}",
        "search_lang": "{language}"
      },
      "results_path": "web.results",
      "title_path": "title",
      "url_path": "url",
      "snippet_path": "description"
    }
  }
}
```

字段说明：

- `custom:<name>` 会读取 `custom_search_apis.<name>`。
- `headers`、`params`、`json` 和 `url` 支持 `${ENV_NAME}` 环境变量占位，适合保存 API key。
- 请求模板支持 `{query}`、`{max_results}`、`{language}`、`{region}` 和 `{unix_timestamp}`。
- `results_path`、`title_path`、`url_path`、`snippet_path` 使用简单点号路径，例如 `web.results` 或 `organic_results`。这些字段可以省略，cc-web 会自动尝试 `results/items/data/Data.Items/web.results/organic_results` 以及 `title/url/snippet/description/ContentText` 等常见字段。
- `extra_paths` 可以把额外字段保留到结果的 `metadata`，例如 `{"content_id": "ContentID", "author": "AuthorName"}`。这些字段会在 `fetch_url` 的搜索 fallback surrogate markdown 中展示，适合保留内容类型、作者、点赞数、评论数等上下文。
- `enable_general_search` 默认为 `true`。如果某个 API 只适合定向 fallback，例如知乎内容 API，可以设为 `false`；这样它不会参与普通 `web_search` 的末尾兜底，但仍可被 `fetch_search_fallback_providers` 和 `config test-search` 使用。
- 如果一个 API 有自己的业务成功码，可以配置 `success_code_path`、`success_codes` 和 `message_path`，避免 HTTP 200 但业务失败时被误判为可用。
- `method` 默认是 `GET`；需要 POST 时可以配置 `"method": "POST"` 和 `"json": {...}`。

`health_check` 会把自定义后端显示为 `custom:<name>`，并使用同一套 URL、headers 和 params 做轻量探测。返回里会包含 `raw_result_count`、`usable_result_count` 和命中的字段路径，方便判断是请求失败还是字段映射失败。不要把私密 API key 直接写进配置文件，优先使用环境变量。

本地调试单个后端时，可以先跑：

```powershell
cc-web-mcp config test-search custom:zhihu "deepseek" --max-results 3
```

这个命令会临时只启用指定 provider，并输出规范化后的搜索结果和诊断字段。

## Jina Reader fallback

`enable_jina_fallback` 控制普通抓取失败、403 或正文太短时是否尝试 Jina Reader。

```json
"enable_jina_fallback": true
```

`jina_min_chars` 控制正文过短时触发 fallback 的阈值。Jina fallback 内部会重复做 URL 安全校验，并默认禁止内网 URL 走 Jina。

启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。

## Fetch Search fallback

`fetch_url` 默认不会把“相关搜索结果”冒充成原 URL 正文。对于知乎这类容易 403、挑战页或正文过短的网站，可以开启抓取失败后的定向搜索 fallback：

```json
{
  "enable_fetch_search_fallback": true,
  "fetch_search_fallback_domains": ["zhihu.com", "zhuanlan.zhihu.com"],
  "fetch_search_fallback_providers": ["custom:zhihu"],
  "fetch_search_fallback_mode": "exact_or_candidates",
  "max_fetch_search_fallback_results": 3
}
```

执行顺序是：

```text
direct fetch -> Jina Reader fallback -> search fallback
```

如果搜索结果 URL 与原 URL 规范化后精确匹配，`fetch_url` 会返回 `ok: true`，并标注 `backend: "search_fallback:<provider>"`、`source_type: "search_result_surrogate"`、`exact_url_match`、`matched_url` 和 `fallback_reason`。

如果没有精确匹配，默认不会返回成功正文，而是在失败结果里附带 `search_fallback.candidates`，让模型知道有哪些相关候选，但不要把它们当作原文。

`research_brief` 内部抓取搜索结果失败时，会把搜索结果的 title/snippet 作为 fallback query，避免用 URL 直接搜索导致命中质量差。普通 `web_search` 的后端顺序不需要因此把 `custom:zhihu` 前移。

## 缓存与安全开关

`cache_ttl_seconds` 控制公开 URL 正文抓取缓存时间。正文抓取缓存只在 `allow_private_networks: false` 时启用，缓存 key 包含 schema version，避免旧格式缓存污染新逻辑。

`search_cache_ttl_seconds` 控制成功搜索结果的短缓存时间，默认 `300` 秒。它只缓存成功结果，不缓存失败或限流响应；它独立于 `allow_private_networks`，因为搜索缓存不抓取用户提供的任意 URL。
`search_backend_cooldown_seconds` 控制搜索后端在触发 403/429、反爬挑战或网络失败后的基础冷却时间，默认 `60` 秒；连续失败会指数退避，最高 300 秒。冷却期间会跳过该后端，优先尝试链路里的下一个后端。

`allow_private_networks` 默认是 `false`。只建议在可信内网文档场景临时开启：

```json
"allow_private_networks": true
```

`trusted_proxy_domains` 用于少数本机透明代理 / TUN 环境：某些公开域名可能解析到 `198.18.0.0/15` 代理测试网段。cc-web 默认会阻止这类解析；只有你确认该域名由可信代理接管时，才加入白名单：

```json
"trusted_proxy_domains": ["github.com"]
```

如果你使用全局 TUN / fake-ip DNS，并确认公开域名会统一解析到 `198.18.0.0/15`，可以开启：

```json
"trust_tun_fake_ip_dns": true
```

该选项只放行“公开域名解析到 `198.18.0.0/15`”的情况；直接访问 `198.18.x.x`、`127.0.0.1`、内网地址和云 metadata 地址仍会被拦截。

## 并发搜索聚合

默认搜索模式是顺序 fallback：先尝试 `search_providers` 里的第一个后端，失败或空结果时再尝试下一个。这个模式最省请求，也最容易解释。

如果你希望更接近元搜索行为，可以打开并发聚合：

```json
{
  "search_parallel_enabled": true,
  "search_parallel_max_backends": 2
}
```

开启后，`web_search` 会并发请求当前可用的前几个搜索后端，跳过处于冷却中的后端和禁用普通搜索的 `custom:<name>` 后端，然后按 URL 去重合并结果。重复 URL 会保留更长的摘要，并在结果项里增加 `source_backends`，表示该结果来自哪些后端。返回顶层会增加：

- `backend`：例如 `parallel:duckduckgo_html+bing`。
- `aggregation`：包含 `mode: "parallel"` 和 `successful_backends`。
- `attempted_backends`：仍保留每个后端的成功、失败或跳过状态。

建议先设为 `2`，通常让 DuckDuckGo 和国际版 Bing 并发已经能提升稳定性；把 `bing_cn` 也纳入并发可能带来区域偏置结果。

## PDF 提取

默认 PDF 会明确拒绝，避免误读二进制内容。若需要读取公开 PDF，可安装可选依赖并开启：

推荐 uvx 场景直接刷新 Claude Code 注册命令：

```powershell
uvx cc-web-mcp init --runner uvx --with-pdf --force
```

普通 pip 环境可安装 PyPI extra：

```powershell
py -3.11 -m pip install "cc-web-mcp[pdf]"
```

```json
"enable_pdf_extract": true
```
