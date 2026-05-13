import logging

from mcp.server.fastmcp import FastMCP

from web import check_health, fetch_page, research_brief as build_research_brief, search_web, to_json_text


logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


mcp = FastMCP(
    "cc-web",
    instructions=(
        "为指定模型提供只读网页搜索和网页正文抓取。"
        "官方 Claude 模型应优先使用内置 WebSearch/WebFetch；"
        "DeepSeek、Qwen、Kimi 等缺少官方搜索能力的模型可使用本 MCP。"
    ),
)


@mcp.tool()
async def web_search(query: str, max_results: int = 5, region: str = "wt-wt", language: str = "zh-cn") -> str:
    """搜索公开网页，返回标题、URL、摘要和抓取时间。"""
    return to_json_text(await search_web(query, max_results, region, language))


@mcp.tool()
async def fetch_url(
    url: str,
    max_chars: int | None = None,
    start_index: int = 0,
    extract_mode: str = "auto",
) -> str:
    """抓取 http/https URL 正文并转为 Markdown，支持 start_index 分页读取。"""
    return to_json_text(await fetch_page(url, max_chars, start_index, extract_mode))


@mcp.tool()
async def research_brief(
    query: str,
    max_sources: int = 3,
    max_chars_per_source: int | None = None,
    region: str = "wt-wt",
    language: str = "zh-cn",
) -> str:
    """搜索并抓取少量来源的短正文，适合先做上下文友好的资料概览。"""
    return to_json_text(await build_research_brief(query, max_sources, max_chars_per_source, region, language))


@mcp.tool()
async def health_check() -> str:
    """检查 MCP 依赖、配置和网络连通性。"""
    return to_json_text(await check_health())


if __name__ == "__main__":
    mcp.run("stdio")
