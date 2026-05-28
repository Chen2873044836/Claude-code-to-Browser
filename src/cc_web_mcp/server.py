import logging

from mcp import types
from mcp.server.fastmcp import Context, FastMCP

from cc_web_mcp.web import check_health, fetch_page, research_brief as build_research_brief, search_web, to_json_text


logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


mcp = FastMCP(
    "cc-web",
    instructions=(
        "cc-web 提供网页搜索和抓取能力。当需要获取最新信息、查阅文档或验证事实时，应主动使用这些工具。"
        "优先使用 research_brief 做快速调研，它会搜索并提取关键内容摘要。"
        "如果需要完整网页内容，使用 fetch_url。"
        "如果需要原始搜索结果列表，使用 web_search。"
    ),
)


async def _send_progress(ctx: Context | None, progress: int, total: int, message: str | None = None) -> None:
    if ctx is None:
        return
    sent = False
    try:
        request_context = ctx.request_context
        progress_token = request_context.meta.progressToken if request_context.meta else None
        if progress_token is not None:
            params = types.ProgressNotificationParams(
                progressToken=progress_token,
                progress=progress,
                total=total,
                message=message,
            )
            notification = types.ServerNotification(
                types.ProgressNotification(method="notifications/progress", params=params)
            )
            await request_context.session.send_notification(notification, ctx.request_id)
            sent = True
    except Exception:
        pass
    if not sent:
        try:
            await ctx.report_progress(progress, total)
        except Exception:
            pass


def _progress_callback(ctx: Context | None, total: int = 100):
    step = 0

    async def callback(message: str) -> None:
        nonlocal step
        if ctx is None:
            return
        step = min(total - 1, step + 10)
        try:
            await ctx.info(message)
        except Exception:
            pass
        await _send_progress(ctx, step, total, message)

    return callback


async def _finish_progress(ctx: Context | None) -> None:
    await _send_progress(ctx, 100, 100, "cc-web: done")


@mcp.tool()
async def web_search(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
    language: str = "zh-cn",
    domains: list[str] | None = None,
    ctx: Context = None,
) -> str:
    """搜索公开网页获取最新信息。当需要查阅文档、验证事实、了解最新进展或获取参考资料时使用此工具。"""
    result = await search_web(query, max_results, region, language, domains=domains, status_callback=_progress_callback(ctx))
    await _finish_progress(ctx)
    return to_json_text(result)


@mcp.tool()
async def fetch_url(
    url: str | None = None,
    max_chars: int | None = None,
    start_index: int = 0,
    extract_mode: str = "auto",
    ref_id: str | None = None,
    ctx: Context = None,
) -> str:
    """抓取网页内容并转换为 Markdown 格式。用于读取具体 URL 的完整内容，如文档页面、API 参考、技术文章等。"""
    result = await fetch_page(url, max_chars, start_index, extract_mode, ref_id=ref_id, status_callback=_progress_callback(ctx))
    await _finish_progress(ctx)
    return to_json_text(result)


@mcp.tool()
async def research_brief(
    query: str,
    max_sources: int = 3,
    max_chars_per_source: int | None = None,
    region: str = "wt-wt",
    language: str = "zh-cn",
    domains: list[str] | None = None,
    ctx: Context = None,
) -> str:
    """快速调研工具：搜索并提取关键内容摘要。最适合需要快速了解某个主题、获取概览信息或收集多个来源要点时使用。"""
    result = await build_research_brief(
        query,
        max_sources,
        max_chars_per_source,
        region,
        language,
        domains=domains,
        status_callback=_progress_callback(ctx),
    )
    await _finish_progress(ctx)
    return to_json_text(result)


@mcp.tool()
async def health_check() -> str:
    """检查 MCP 依赖、配置和网络连通性。"""
    return to_json_text(await check_health())


def run_stdio() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    run_stdio()
