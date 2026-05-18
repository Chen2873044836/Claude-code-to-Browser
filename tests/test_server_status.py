import asyncio
import json

from cc_web_mcp import server


class FakeContext:
    def __init__(self):
        self.progress = []
        self.info_messages = []

    async def report_progress(self, progress, total=None):
        self.progress.append((progress, total))

    async def info(self, message, **extra):
        self.info_messages.append(message)


class FakeRequestMeta:
    progressToken = "progress-token"


class FakeRequestSession:
    def __init__(self):
        self.notifications = []

    async def send_notification(self, notification, related_request_id=None):
        self.notifications.append((notification, related_request_id))


class FakeRequestContext:
    def __init__(self):
        self.meta = FakeRequestMeta()
        self.session = FakeRequestSession()


class FakeRichContext(FakeContext):
    request_id = "request-id"

    def __init__(self):
        super().__init__()
        self._request_context = FakeRequestContext()

    @property
    def request_context(self):
        return self._request_context


def test_web_search_emits_mcp_status_messages(monkeypatch):
    async def fake_search_web(query, max_results, region, language, domains=None, status_callback=None):
        if status_callback:
            await status_callback("cc-web: searching via fake")
            await status_callback("cc-web: search complete")
        return {"ok": True, "status_summary": "search complete", "steps": []}

    monkeypatch.setattr(server, "search_web", fake_search_web)
    ctx = FakeContext()

    result = asyncio.run(server.web_search("mcp docs", ctx=ctx))

    payload = json.loads(result)
    assert payload["ok"] is True
    assert ctx.info_messages == ["cc-web: searching via fake", "cc-web: search complete"]
    assert ctx.progress[-1] == (100, 100)


def test_progress_notification_includes_status_message():
    ctx = FakeRichContext()

    asyncio.run(server._send_progress(ctx, 25, 100, "cc-web: searching duckduckgo_html"))

    notification, request_id = ctx.request_context.session.notifications[0]
    assert request_id == "request-id"
    assert notification.root.params.progress == 25
    assert notification.root.params.total == 100
    assert notification.root.params.message == "cc-web: searching duckduckgo_html"
    assert ctx.progress == []


def test_context_is_injected_and_not_exposed_as_tool_parameter():
    for tool_name in ("web_search", "fetch_url", "research_brief"):
        tool = server.mcp._tool_manager._tools[tool_name]
        assert tool.context_kwarg == "ctx"
        assert "ctx" not in tool.parameters.get("properties", {})


def test_fetch_url_emits_mcp_status_messages(monkeypatch):
    async def fake_fetch_page(url=None, max_chars=None, start_index=0, extract_mode="auto", ref_id=None, status_callback=None):
        if status_callback:
            await status_callback("cc-web: fetching example.com")
            await status_callback("cc-web: extracting markdown")
        return {"ok": True, "status_summary": "fetch complete", "steps": [], "ref_id": ref_id}

    monkeypatch.setattr(server, "fetch_page", fake_fetch_page)
    ctx = FakeContext()

    result = asyncio.run(server.fetch_url("https://example.com", ctx=ctx))

    payload = json.loads(result)
    assert payload["ok"] is True
    assert ctx.info_messages == ["cc-web: fetching example.com", "cc-web: extracting markdown"]
    assert ctx.progress[-1] == (100, 100)


def test_fetch_url_accepts_ref_id_parameter(monkeypatch):
    async def fake_fetch_page(url=None, max_chars=None, start_index=0, extract_mode="auto", ref_id=None, status_callback=None):
        return {"ok": True, "url": url, "ref_id": ref_id, "steps": []}

    monkeypatch.setattr(server, "fetch_page", fake_fetch_page)

    result = asyncio.run(server.fetch_url(ref_id="ccweb-search-1"))

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["url"] is None
    assert payload["ref_id"] == "ccweb-search-1"


def test_web_search_passes_domains_to_core(monkeypatch):
    async def fake_search_web(query, max_results, region, language, domains=None, status_callback=None):
        return {"ok": True, "domains": domains, "steps": []}

    monkeypatch.setattr(server, "search_web", fake_search_web)

    result = asyncio.run(server.web_search("mcp docs", domains=["example.com"]))

    payload = json.loads(result)
    assert payload["domains"] == ["example.com"]


def test_research_brief_emits_mcp_status_messages(monkeypatch):
    async def fake_research_brief(query, max_sources, max_chars_per_source, region, language, domains=None, status_callback=None):
        if status_callback:
            await status_callback("cc-web: searching for sources")
            await status_callback("cc-web: fetching 1/2")
        return {"ok": True, "status_summary": "research brief complete", "steps": []}

    monkeypatch.setattr(server, "build_research_brief", fake_research_brief)
    ctx = FakeContext()

    result = asyncio.run(server.research_brief("docs", ctx=ctx))

    payload = json.loads(result)
    assert payload["ok"] is True
    assert ctx.info_messages == ["cc-web: searching for sources", "cc-web: fetching 1/2"]
    assert ctx.progress[-1] == (100, 100)


def test_research_brief_passes_domains_to_core(monkeypatch):
    async def fake_research_brief(query, max_sources, max_chars_per_source, region, language, domains=None, status_callback=None):
        return {"ok": True, "domains": domains, "steps": []}

    monkeypatch.setattr(server, "build_research_brief", fake_research_brief)

    result = asyncio.run(server.research_brief("docs", domains=["example.com"]))

    payload = json.loads(result)
    assert payload["domains"] == ["example.com"]
