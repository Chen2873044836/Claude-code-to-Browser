from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import inspect
import ipaddress
import json
import os
import re
import socket
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown

from cc_web_mcp.config import default_config_dict, resolve_config_path


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SEARCH_USER_AGENTS = (
    USER_AGENT,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
)
MAX_DOWNLOAD_BYTES = 5_000_000
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=8.0, read=15.0)
DEFAULT_CONFIG_PATH = resolve_config_path()
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "cc-web-mcp"
CACHE_SCHEMA_VERSION = 3
SEARCH_CACHE_SCHEMA_VERSION = 6
BROWSE_REF_TTL_SECONDS = 1_800
MAX_BROWSE_REFS = 200
BING_CN_SCOPE_NOTE = "bing_cn may be region-biased and is used as fallback; it is not equivalent to full global search."
DEFAULT_SEARCH_PROVIDERS = ("duckduckgo", "bing", "bing_cn")
CUSTOM_SEARCH_PROVIDER_PREFIX = "custom:"
MAX_SEARCH_BACKEND_COOLDOWN_SECONDS = 300
DEFAULT_CUSTOM_RESULTS_PATHS = (
    "results",
    "items",
    "data.results",
    "data.items",
    "data",
    "Data.Items",
    "Data.Results",
    "Data",
    "web.results",
    "organic_results",
)
DEFAULT_CUSTOM_TITLE_PATHS = ("title", "Title", "name", "Name", "headline", "Headline", "object.title")
DEFAULT_CUSTOM_URL_PATHS = ("url", "Url", "URL", "link", "Link", "href", "Href", "object.url", "target.url")
DEFAULT_CUSTOM_SNIPPET_PATHS = (
    "snippet",
    "Snippet",
    "description",
    "Description",
    "summary",
    "Summary",
    "content",
    "Content",
    "ContentText",
    "excerpt",
    "Excerpt",
    "text",
    "Text",
    "object.excerpt",
)
_SEARCH_BACKEND_COOLDOWNS: dict[str, dict[str, Any]] = {}
ANTI_BOT_DOMAINS = (
    "zhihu.com",
    "weixin.qq.com",
    "x.com",
    "twitter.com",
    "reddit.com",
)
CHALLENGE_PATH_HINTS = (
    "/account/unhuman",
    "/captcha",
    "/challenge",
    "/security",
    "/verify",
)
LOGIN_PATH_HINTS = (
    "/login",
    "/signin",
    "/sign_in",
    "/auth",
)
CHALLENGE_KEYWORDS = (
    "安全验证",
    "访问异常",
    "验证码",
    "请完成验证",
    "人机验证",
    "verify you are human",
    "are you a human",
    "unusual traffic",
    "just a moment",
    "attention required",
    "checking your browser",
)
LOGIN_KEYWORDS = (
    "登录后查看",
    "请登录",
    "login required",
    "sign in to continue",
)
JS_REQUIRED_KEYWORDS = (
    "enable javascript",
    "requires javascript",
    "请启用 javascript",
    "请启用js",
)
TRUSTED_PROXY_IP_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "198.18.0.0/15",
    )
)
BLOCKED_IP_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "127.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "169.254.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


class FetchSafetyError(ValueError):
    pass


class FetchDiagnosticError(FetchSafetyError):
    def __init__(self, message: str, diagnostics: dict[str, Any]):
        super().__init__(message)
        self.diagnostics = diagnostics


class EmptySearchResultsError(RuntimeError):
    pass


class LowRelevanceSearchResultsError(RuntimeError):
    pass


class SearchBackendUnavailableError(RuntimeError):
    pass


StatusCallback = Callable[[str], Awaitable[None] | None]


class StatusRecorder:
    def __init__(self, callback: StatusCallback | None = None):
        self.callback = callback
        self.steps: list[dict[str, str]] = []

    async def add(self, message: str) -> None:
        message = _clean_text(message)
        if not message:
            return
        self.steps.append({"message": message, "at": now_iso()})
        if self.callback:
            maybe_awaitable = self.callback(message)
            if maybe_awaitable:
                await maybe_awaitable

    def summary(self, fallback: str = "") -> str:
        if fallback:
            return fallback
        if self.steps:
            return self.steps[-1]["message"]
        return ""


async def _call_with_optional_status(fn: Callable[..., Any], *args: Any, status_callback: StatusCallback | None = None, **kwargs: Any) -> Any:
    signature = None
    if status_callback is not None:
        try:
            signature = inspect.signature(fn)
            if "status_callback" in signature.parameters:
                kwargs["status_callback"] = status_callback
        except (TypeError, ValueError):
            kwargs["status_callback"] = status_callback
    if kwargs:
        try:
            signature = signature or inspect.signature(fn)
            accepts_var_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
            if not accepts_var_kwargs:
                kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
        except (TypeError, ValueError):
            pass
    return await fn(*args, **kwargs)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class FetchTarget:
    url: str
    connect_url: str
    connect_host: str
    hostname: str
    host_header: str
    request_target: str


@dataclass(frozen=True)
class BrowseRef:
    ref_id: str
    kind: str
    url: str
    title: str = ""
    snippet: str = ""
    created_at: float = 0.0


class BrowseSession:
    def __init__(self, ttl_seconds: int = BROWSE_REF_TTL_SECONDS, max_entries: int = MAX_BROWSE_REFS):
        self.ttl_seconds = max(1, int(ttl_seconds or BROWSE_REF_TTL_SECONDS))
        self.max_entries = max(1, int(max_entries or MAX_BROWSE_REFS))
        self._counter = 0
        self._entries: OrderedDict[str, BrowseRef] = OrderedDict()

    def _now(self) -> float:
        return datetime.now(timezone.utc).timestamp()

    def _prune(self) -> None:
        now = self._now()
        for ref_id, entry in list(self._entries.items()):
            if now - entry.created_at > self.ttl_seconds:
                self._entries.pop(ref_id, None)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def add(self, kind: str, url: str, title: str = "", snippet: str = "") -> str:
        self._prune()
        self._counter += 1
        ref_id = f"ccweb-{kind}-{self._counter}"
        self._entries[ref_id] = BrowseRef(
            ref_id=ref_id,
            kind=kind,
            url=url,
            title=_clean_text(title),
            snippet=_clean_text(snippet),
            created_at=self._now(),
        )
        self._prune()
        return ref_id

    def get(self, ref_id: str | None) -> BrowseRef | None:
        if not ref_id:
            return None
        self._prune()
        entry = self._entries.get(str(ref_id).strip())
        if entry:
            self._entries.move_to_end(entry.ref_id)
        return entry

    def find_by_url(self, url: str | None) -> BrowseRef | None:
        if not url:
            return None
        self._prune()
        for entry in reversed(self._entries.values()):
            if _result_matches_target_url(entry.url, str(url)):
                self._entries.move_to_end(entry.ref_id)
                return entry
        return None


_BROWSE_SESSION = BrowseSession()


@dataclass(frozen=True)
class GlobalWebConfig:
    allowed_model_patterns: tuple[str, ...] = ("deepseek",)
    search_provider: str = "duckduckgo"
    search_providers: tuple[str, ...] = DEFAULT_SEARCH_PROVIDERS
    custom_search_apis: dict[str, dict[str, Any]] | None = None
    allow_fetch_url_for_claude: bool = False
    block_native_web_for_allowed_models: bool = True
    searxng_base_url: str = ""
    prefer_technical_sources: bool = True
    default_fetch_chars: int = 10_000
    max_fetch_chars: int = 60_000
    max_search_results: int = 10
    max_brief_sources: int = 3
    brief_chars_per_source: int = 2_500
    enable_jina_fallback: bool = True
    jina_min_chars: int = 300
    enable_fetch_search_fallback: bool = False
    fetch_search_fallback_domains: tuple[str, ...] = ()
    fetch_search_fallback_providers: tuple[str, ...] = ()
    fetch_search_fallback_mode: str = "exact_or_candidates"
    max_fetch_search_fallback_results: int = 3
    allow_private_networks: bool = False
    cache_ttl_seconds: int = 1_800
    search_cache_ttl_seconds: int = 300
    search_backend_cooldown_seconds: int = 60
    search_cooldown_empty_results: bool = True
    search_parallel_enabled: bool = False
    search_parallel_max_backends: int = 2
    trust_tun_fake_ip_dns: bool = False
    cache_dir: str = str(DEFAULT_CACHE_DIR)
    trusted_proxy_domains: tuple[str, ...] = ()
    brief_concurrency: int = 3
    dedupe_domains: bool = True
    enable_pdf_extract: bool = False


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _cfg(config: Any, name: str, default: Any) -> Any:
    return getattr(config, name, default)


def _normalize_search_provider_name(provider: Any) -> str:
    normalized = str(provider or "").strip().lower().replace("-", "_")
    aliases = {
        "ddg": "duckduckgo",
        "duckduckgo_html": "duckduckgo",
        "bingcn": "bing_cn",
        "bing_china": "bing_cn",
        "mojeek_html": "mojeek",
    }
    return aliases.get(normalized, normalized)


def _normalize_search_providers(raw_providers: Any, default_provider: str = "duckduckgo") -> tuple[str, ...]:
    if isinstance(raw_providers, str):
        items = [raw_providers]
    elif isinstance(raw_providers, (list, tuple)):
        items = list(raw_providers)
    else:
        default = _normalize_search_provider_name(default_provider)
        items = list(DEFAULT_SEARCH_PROVIDERS) if default == "duckduckgo" else [default]

    providers: list[str] = []
    for item in items:
        provider = _normalize_search_provider_name(item)
        if provider and provider not in providers:
            providers.append(provider)
    return tuple(providers or DEFAULT_SEARCH_PROVIDERS)


def _normalize_optional_search_providers(raw_providers: Any) -> tuple[str, ...]:
    if isinstance(raw_providers, str):
        items = [raw_providers]
    elif isinstance(raw_providers, (list, tuple)):
        items = list(raw_providers)
    else:
        items = []
    providers: list[str] = []
    for item in items:
        provider = _normalize_search_provider_name(item)
        if provider and provider not in providers:
            providers.append(provider)
    return tuple(providers)


def _normalize_string_tuple(raw_items: Any) -> tuple[str, ...]:
    if isinstance(raw_items, str):
        items = [raw_items]
    elif isinstance(raw_items, (list, tuple)):
        items = list(raw_items)
    else:
        items = []

    normalized: list[str] = []
    for item in items:
        value = str(item or "").strip().lower().strip(".")
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _expand_env_placeholders(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _expand_env_placeholders(item) for key, item in value.items()}
    return value


def _normalize_custom_search_apis(raw_apis: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_apis, dict):
        return {}

    apis: dict[str, dict[str, Any]] = {}
    for raw_name, raw_spec in raw_apis.items():
        name = str(raw_name or "").strip().lower().replace("-", "_")
        if not name or not isinstance(raw_spec, dict):
            continue
        spec = _expand_env_placeholders(raw_spec)
        if isinstance(spec, dict):
            apis[name] = spec
    return apis


def _redact_custom_search_apis(apis: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    sensitive_keys = {"api_key", "apikey", "token", "access_token", "secret", "password", "authorization", "auth"}
    redacted: dict[str, dict[str, Any]] = {}
    for name, spec in (apis or {}).items():
        safe_spec = dict(spec)
        if isinstance(safe_spec.get("headers"), dict):
            safe_spec["headers"] = {str(key): "***" for key in safe_spec["headers"]}
        for container_name in ("params", "json"):
            container = safe_spec.get(container_name)
            if not isinstance(container, dict):
                continue
            safe_container = dict(container)
            for key in list(safe_container):
                normalized_key = str(key).lower().replace("-", "_")
                if normalized_key in sensitive_keys or normalized_key.endswith("_token") or normalized_key.endswith("_secret"):
                    safe_container[key] = "***"
            safe_spec[container_name] = safe_container
        redacted[name] = safe_spec
    return redacted


def _custom_search_api_name(provider: str) -> str | None:
    normalized = _normalize_search_provider_name(provider)
    if not normalized.startswith(CUSTOM_SEARCH_PROVIDER_PREFIX):
        return None
    name = normalized[len(CUSTOM_SEARCH_PROVIDER_PREFIX) :].strip().lower().replace("-", "_")
    return name or None


def _custom_search_api_spec(config: Any, provider: str) -> dict[str, Any] | None:
    custom_name = _custom_search_api_name(provider)
    if not custom_name:
        return None
    spec = (_cfg(config, "custom_search_apis", {}) or {}).get(custom_name)
    return spec if isinstance(spec, dict) else None


def _custom_search_general_enabled(config: Any, provider: str) -> bool:
    spec = _custom_search_api_spec(config, provider)
    if spec is None:
        return True
    return bool(spec.get("enable_general_search", True))


def _render_search_api_template(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in context.items():
            rendered = rendered.replace("{" + key + "}", replacement)
        return rendered
    if isinstance(value, list):
        return [_render_search_api_template(item, context) for item in value]
    if isinstance(value, dict):
        return {str(key): _render_search_api_template(item, context) for key, item in value.items()}
    return value


def _get_by_dot_path(data: Any, path: Any, default: Any = None) -> Any:
    if not path:
        return data
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part, default)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else default
        else:
            return default
        if current is default:
            return default
    return current


def _get_by_dot_path_candidates(data: Any, paths: Any, default: Any = None) -> Any:
    value, _matched_path = _get_by_dot_path_candidates_with_path(data, paths, default)
    return value


def _get_by_dot_path_candidates_with_path(data: Any, paths: Any, default: Any = None) -> tuple[Any, str]:
    if isinstance(paths, (list, tuple)):
        for path in paths:
            value = _get_by_dot_path(data, path, default)
            if value is not default and value not in (None, ""):
                return value, str(path)
        return default, ""
    value = _get_by_dot_path(data, paths, default)
    if value is default or value in (None, ""):
        return default, ""
    return value, str(paths or "")


def _custom_path_candidates(spec: dict[str, Any], key: str, defaults: tuple[str, ...]) -> Any:
    configured = spec.get(key)
    if configured:
        return configured
    return defaults


def _path_hint(paths: Any) -> str:
    if isinstance(paths, (list, tuple)):
        return "|".join(str(path) for path in paths)
    return str(paths or "")


def _coerce_custom_result_items(raw_results: Any) -> list[Any]:
    if isinstance(raw_results, list):
        return raw_results
    if not isinstance(raw_results, dict):
        return []
    for key in ("Items", "items", "Results", "results", "Data", "data", "organic_results"):
        value = raw_results.get(key)
        items = _coerce_custom_result_items(value)
        if items:
            return items
    return []


def _custom_result_metadata(item: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    extra_paths = spec.get("extra_paths")
    if not isinstance(extra_paths, dict):
        return {}
    metadata: dict[str, Any] = {}
    for raw_key, raw_path in extra_paths.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        value = _get_by_dot_path_candidates(item, raw_path)
        if value in (None, ""):
            continue
        metadata[key] = value
    return metadata


def _metadata_label(key: str) -> str:
    label = str(key or "").replace("_", " ").replace("-", " ").strip()
    return label.title() if label else "Metadata"


def _normalize_domains(raw_domains: Any) -> tuple[str, ...]:
    if isinstance(raw_domains, str):
        items = [raw_domains]
    elif isinstance(raw_domains, (list, tuple)):
        items = list(raw_domains)
    else:
        items = []

    domains: list[str] = []
    for item in items:
        raw = str(item or "").strip().lower()
        if not raw:
            continue
        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        domain = (parsed.hostname or raw.split("/", 1)[0]).strip().strip(".")
        if domain.startswith("*."):
            domain = domain[2:]
        if domain and domain not in domains:
            domains.append(domain)
    return tuple(domains)


def _domains_query_suffix(domains: tuple[str, ...]) -> str:
    if not domains:
        return ""
    terms = " OR ".join(f"site:{domain}" for domain in domains)
    return f" ({terms})"


def _query_with_domain_hints(query: str, domains: tuple[str, ...]) -> str:
    if not domains:
        return query
    return f"{query}{_domains_query_suffix(domains)}"


def filter_search_results_by_domains(
    results: list[dict[str, str]],
    domains: tuple[str, ...] | list[str] | str | None,
) -> tuple[list[dict[str, str]], int]:
    normalized_domains = _normalize_domains(domains)
    if not normalized_domains:
        return list(results), 0

    filtered: list[dict[str, str]] = []
    removed = 0
    for result in results:
        hostname = (urlparse(str(result.get("url") or "")).hostname or "").lower().strip(".")
        if hostname and _domain_matches(hostname, normalized_domains):
            filtered.append(result)
        else:
            removed += 1
    return filtered, removed


def load_config(path: str | Path | None = None) -> GlobalWebConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    try:
        raw = default_config_dict()
    except Exception:
        raw = {}
    try:
        if config_path.exists():
            user_raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if isinstance(user_raw, dict):
                raw.update(user_raw)
    except Exception:
        pass

    patterns = raw.get("allowed_model_patterns", ["deepseek"])
    if not isinstance(patterns, list):
        patterns = ["deepseek"]
    allowed_model_patterns = tuple(
        str(item).strip().lower() for item in patterns if str(item).strip()
    ) or ("deepseek",)

    search_providers = _normalize_search_providers(raw.get("search_providers"), raw.get("search_provider") or "duckduckgo")
    legacy_search_provider = raw.get("search_provider")
    search_provider = (
        _normalize_search_provider_name(legacy_search_provider)
        if legacy_search_provider
        else (search_providers[0] if search_providers else "duckduckgo")
    )
    custom_search_apis = _normalize_custom_search_apis(raw.get("custom_search_apis"))

    return GlobalWebConfig(
        allowed_model_patterns=allowed_model_patterns,
        search_provider=search_provider,
        search_providers=search_providers,
        custom_search_apis=custom_search_apis,
        allow_fetch_url_for_claude=bool(raw.get("allow_fetch_url_for_claude", False)),
        block_native_web_for_allowed_models=bool(raw.get("block_native_web_for_allowed_models", True)),
        searxng_base_url=str(raw.get("searxng_base_url") or "").strip().rstrip("/"),
        prefer_technical_sources=bool(raw.get("prefer_technical_sources", True)),
        default_fetch_chars=_bounded_int(raw.get("default_fetch_chars"), 10_000, 1_000, 60_000),
        max_fetch_chars=_bounded_int(raw.get("max_fetch_chars"), 60_000, 1_000, 120_000),
        max_search_results=_bounded_int(raw.get("max_search_results"), 10, 1, 20),
        max_brief_sources=_bounded_int(raw.get("max_brief_sources"), 3, 1, 5),
        brief_chars_per_source=_bounded_int(raw.get("brief_chars_per_source"), 2_500, 100, 20_000),
        enable_jina_fallback=bool(raw.get("enable_jina_fallback", True)),
        jina_min_chars=_bounded_int(raw.get("jina_min_chars"), 300, 0, 5_000),
        enable_fetch_search_fallback=bool(raw.get("enable_fetch_search_fallback", False)),
        fetch_search_fallback_domains=_normalize_domains(raw.get("fetch_search_fallback_domains")),
        fetch_search_fallback_providers=_normalize_optional_search_providers(raw.get("fetch_search_fallback_providers")),
        fetch_search_fallback_mode=str(raw.get("fetch_search_fallback_mode") or "exact_or_candidates").strip().lower(),
        max_fetch_search_fallback_results=_bounded_int(raw.get("max_fetch_search_fallback_results"), 3, 1, 10),
        allow_private_networks=bool(raw.get("allow_private_networks", False)),
        cache_ttl_seconds=_bounded_int(raw.get("cache_ttl_seconds"), 1_800, 0, 86_400),
        search_cache_ttl_seconds=_bounded_int(raw.get("search_cache_ttl_seconds"), 300, 0, 3_600),
        search_backend_cooldown_seconds=_bounded_int(raw.get("search_backend_cooldown_seconds"), 60, 0, 3_600),
        search_cooldown_empty_results=bool(raw.get("search_cooldown_empty_results", True)),
        search_parallel_enabled=bool(raw.get("search_parallel_enabled", False)),
        search_parallel_max_backends=_bounded_int(raw.get("search_parallel_max_backends"), 2, 1, 5),
        trust_tun_fake_ip_dns=bool(raw.get("trust_tun_fake_ip_dns", False)),
        cache_dir=str(raw.get("cache_dir") or DEFAULT_CACHE_DIR),
        trusted_proxy_domains=_normalize_string_tuple(raw.get("trusted_proxy_domains")),
        brief_concurrency=_bounded_int(raw.get("brief_concurrency"), 3, 1, 5),
        dedupe_domains=bool(raw.get("dedupe_domains", True)),
        enable_pdf_extract=bool(raw.get("enable_pdf_extract", False)),
    )


def config_to_dict(config: GlobalWebConfig) -> dict[str, Any]:
    return {
        "allowed_model_patterns": list(config.allowed_model_patterns),
        "search_provider": config.search_provider,
        "search_providers": list(config.search_providers),
        "custom_search_apis": _redact_custom_search_apis(config.custom_search_apis),
        "allow_fetch_url_for_claude": config.allow_fetch_url_for_claude,
        "block_native_web_for_allowed_models": config.block_native_web_for_allowed_models,
        "searxng_base_url": config.searxng_base_url,
        "prefer_technical_sources": config.prefer_technical_sources,
        "default_fetch_chars": config.default_fetch_chars,
        "max_fetch_chars": config.max_fetch_chars,
        "max_search_results": config.max_search_results,
        "max_brief_sources": config.max_brief_sources,
        "brief_chars_per_source": config.brief_chars_per_source,
        "enable_jina_fallback": config.enable_jina_fallback,
        "jina_min_chars": config.jina_min_chars,
        "enable_fetch_search_fallback": config.enable_fetch_search_fallback,
        "fetch_search_fallback_domains": list(config.fetch_search_fallback_domains),
        "fetch_search_fallback_providers": list(config.fetch_search_fallback_providers),
        "fetch_search_fallback_mode": config.fetch_search_fallback_mode,
        "max_fetch_search_fallback_results": config.max_fetch_search_fallback_results,
        "allow_private_networks": config.allow_private_networks,
        "cache_ttl_seconds": config.cache_ttl_seconds,
        "search_cache_ttl_seconds": config.search_cache_ttl_seconds,
        "search_backend_cooldown_seconds": config.search_backend_cooldown_seconds,
        "search_cooldown_empty_results": config.search_cooldown_empty_results,
        "search_parallel_enabled": config.search_parallel_enabled,
        "search_parallel_max_backends": config.search_parallel_max_backends,
        "trust_tun_fake_ip_dns": config.trust_tun_fake_ip_dns,
        "cache_dir": config.cache_dir,
        "trusted_proxy_domains": list(config.trusted_proxy_domains),
        "brief_concurrency": config.brief_concurrency,
        "dedupe_domains": config.dedupe_domains,
        "enable_pdf_extract": config.enable_pdf_extract,
    }


def model_matches_patterns(model: str | None, patterns: tuple[str, ...] | list[str] | None) -> bool:
    normalized = (model or "").lower()
    return any(pattern and pattern.lower() in normalized for pattern in (patterns or ()))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_private_host(host: str) -> bool:
    normalized = (host or "").strip().strip("[]").lower().rstrip(".")
    if not normalized:
        return False
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        if getattr(ip, "ipv4_mapped", None) is not None:
            ip = ip.ipv4_mapped
        return any(ip in network for network in BLOCKED_IP_NETWORKS)
    except ValueError:
        return False


def _resolved_private_hosts(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    private_ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip = str(sockaddr[0])
        if _is_private_host(ip) and ip not in private_ips:
            private_ips.append(ip)
    return private_ips


def _resolved_policy_hosts(hostname: str, port: int) -> tuple[list[str], str]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return [], f"{type(exc).__name__}: {exc}"
    hosts: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        host = str(sockaddr[0])
        if host not in hosts:
            hosts.append(host)
    return hosts, ""


def _is_trusted_proxy_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
        if getattr(parsed, "ipv4_mapped", None) is not None:
            parsed = parsed.ipv4_mapped
        return any(parsed in network for network in TRUSTED_PROXY_IP_NETWORKS)
    except ValueError:
        return False


def _is_ip_literal(hostname: str) -> bool:
    normalized = (hostname or "").strip().strip("[]").lower().rstrip(".")
    if not normalized:
        return False
    try:
        ipaddress.ip_address(normalized)
        return True
    except ValueError:
        return False


def _can_allow_trusted_proxy_resolution(
    hostname: str,
    private_ips: list[str],
    trusted_proxy_domains: tuple[str, ...] | list[str] | None,
) -> bool:
    trusted_domains = _normalize_string_tuple(trusted_proxy_domains)
    if not trusted_domains or not private_ips:
        return False
    return _domain_matches(hostname, trusted_domains) and all(_is_trusted_proxy_ip(ip) for ip in private_ips)


def _can_allow_tun_fake_ip_resolution(hostname: str, private_ips: list[str], trust_tun_fake_ip_dns: bool) -> bool:
    if not trust_tun_fake_ip_dns or not private_ips or _is_ip_literal(hostname):
        return False
    return all(_is_trusted_proxy_ip(ip) for ip in private_ips)


def evaluate_network_policy(
    url: str,
    allow_private_networks: bool = False,
    resolve_dns: bool = True,
    trusted_proxy_domains: tuple[str, ...] | list[str] | None = None,
    trust_tun_fake_ip_dns: bool = False,
) -> dict[str, Any]:
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    trusted_domains = _normalize_string_tuple(trusted_proxy_domains)
    decision: dict[str, Any] = {
        "allowed": False,
        "url": cleaned,
        "scheme": parsed.scheme,
        "hostname": parsed.hostname or "",
        "allow_private_networks": bool(allow_private_networks),
        "resolve_dns": bool(resolve_dns),
        "resolved_ips": [],
        "blocked_ips": [],
        "trusted_proxy": False,
        "trusted_proxy_domains": list(trusted_domains),
        "trust_tun_fake_ip_dns": bool(trust_tun_fake_ip_dns),
        "reason": "",
    }

    if parsed.scheme not in {"http", "https"}:
        decision["reason"] = "unsupported_scheme"
        return decision
    if not parsed.netloc:
        decision["reason"] = "missing_host"
        return decision

    hostname = parsed.hostname or ""
    if not allow_private_networks and _is_private_host(hostname):
        decision["reason"] = "restricted_host"
        decision["blocked_ips"] = [hostname]
        return decision

    if resolve_dns:
        port = parsed.port or _default_port(parsed.scheme)
        resolved_ips, dns_error = _resolved_policy_hosts(hostname, port)
        decision["resolved_ips"] = resolved_ips
        if dns_error:
            decision["dns_error"] = dns_error
        blocked_ips = [ip for ip in resolved_ips if _is_private_host(ip)]
        decision["blocked_ips"] = blocked_ips
        if blocked_ips and not allow_private_networks:
            if _can_allow_tun_fake_ip_resolution(hostname, blocked_ips, trust_tun_fake_ip_dns):
                decision["allowed"] = True
                decision["trusted_proxy"] = True
                decision["reason"] = "trusted_tun_fake_ip_dns"
                return decision
            if _can_allow_trusted_proxy_resolution(hostname, blocked_ips, trusted_domains):
                decision["allowed"] = True
                decision["trusted_proxy"] = True
                decision["reason"] = "trusted_proxy"
                return decision
            decision["reason"] = "restricted_dns"
            return decision

    decision["allowed"] = True
    decision["reason"] = "allowed"
    return decision


async def evaluate_network_policy_async(
    url: str,
    allow_private_networks: bool = False,
    resolve_dns: bool = True,
    trusted_proxy_domains: tuple[str, ...] | list[str] | None = None,
    trust_tun_fake_ip_dns: bool = False,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        evaluate_network_policy,
        url,
        allow_private_networks=allow_private_networks,
        resolve_dns=resolve_dns,
        trusted_proxy_domains=trusted_proxy_domains,
        trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
    )


def _network_policy_error_message(decision: dict[str, Any]) -> str:
    reason = decision.get("reason")
    if reason == "unsupported_scheme":
        return "仅允许抓取 http/https URL"
    if reason == "missing_host":
        return "URL 缺少主机名"
    if reason == "restricted_host":
        return "默认禁止抓取本机、内网、链路本地或云 metadata 地址"
    if reason == "restricted_dns":
        blocked_ips = ", ".join(decision.get("blocked_ips") or [])
        return f"域名解析到受限地址，已阻止抓取: {blocked_ips}"
    return "URL 被网络策略阻止"


def validate_fetch_url(
    url: str,
    allow_private_networks: bool = False,
    resolve_dns: bool = True,
    trusted_proxy_domains: tuple[str, ...] | list[str] | None = None,
    trust_tun_fake_ip_dns: bool = False,
) -> str:
    decision = evaluate_network_policy(
        url,
        allow_private_networks=allow_private_networks,
        resolve_dns=resolve_dns,
        trusted_proxy_domains=trusted_proxy_domains,
        trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
    )
    if not decision["allowed"]:
        raise FetchSafetyError(_network_policy_error_message(decision))
    return str(decision["url"])


async def validate_fetch_url_async(
    url: str,
    allow_private_networks: bool = False,
    resolve_dns: bool = True,
    trusted_proxy_domains: tuple[str, ...] | list[str] | None = None,
    trust_tun_fake_ip_dns: bool = False,
) -> str:
    cleaned = validate_fetch_url(
        url,
        allow_private_networks=allow_private_networks,
        resolve_dns=False,
        trusted_proxy_domains=trusted_proxy_domains,
        trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
    )
    if resolve_dns:
        hostname = urlparse(cleaned).hostname or ""
        private_ips = await asyncio.to_thread(_resolved_private_hosts, hostname)
        if private_ips and not allow_private_networks:
            if _can_allow_tun_fake_ip_resolution(hostname, private_ips, trust_tun_fake_ip_dns):
                return cleaned
            if _can_allow_trusted_proxy_resolution(hostname, private_ips, trusted_proxy_domains):
                return cleaned
            raise FetchSafetyError(f"域名解析到受限地址，已阻止抓取: {', '.join(private_ips)}")
    return cleaned


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _host_header(hostname: str, port: int, scheme: str) -> str:
    if port == _default_port(scheme):
        return hostname
    return f"{hostname}:{port}"


def _connect_netloc(connect_host: str, port: int, scheme: str) -> str:
    host = f"[{connect_host}]" if ":" in connect_host else connect_host
    if port == _default_port(scheme):
        return host
    return f"{host}:{port}"


def _request_target(parsed_url) -> str:
    path = parsed_url.path or "/"
    if parsed_url.query:
        return f"{path}?{parsed_url.query}"
    return path


def _resolved_fetch_hosts(hostname: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchSafetyError(f"域名解析失败: {type(exc).__name__}: {exc}") from exc
    hosts: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        host = str(sockaddr[0])
        if host not in hosts:
            hosts.append(host)
    return hosts


def build_fetch_target(
    url: str,
    allow_private_networks: bool = False,
    trusted_proxy_domains: tuple[str, ...] | list[str] | None = None,
    trust_tun_fake_ip_dns: bool = False,
) -> FetchTarget:
    safe_url = validate_fetch_url(
        url,
        allow_private_networks=allow_private_networks,
        trusted_proxy_domains=trusted_proxy_domains,
        trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
    )
    parsed = urlparse(safe_url)
    hostname = parsed.hostname or ""
    port = parsed.port or _default_port(parsed.scheme)
    resolved_hosts = _resolved_fetch_hosts(hostname, port)

    connect_host = ""
    for host in resolved_hosts:
        if (
            allow_private_networks
            or not _is_private_host(host)
            or _can_allow_tun_fake_ip_resolution(hostname, [host], trust_tun_fake_ip_dns)
            or _can_allow_trusted_proxy_resolution(hostname, [host], trusted_proxy_domains)
        ):
            connect_host = host
            break
    if not connect_host:
        raise FetchSafetyError("域名没有解析到允许抓取的地址")

    connect_url = urlunparse(
        (
            parsed.scheme,
            _connect_netloc(connect_host, port, parsed.scheme),
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )
    return FetchTarget(
        url=safe_url,
        connect_url=connect_url,
        connect_host=connect_host,
        hostname=hostname,
        host_header=_host_header(hostname, port, parsed.scheme),
        request_target=_request_target(parsed),
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
    }


def _search_headers(language: str = "zh-cn") -> dict[str, str]:
    index_seed = int(time.time() * 1000)
    user_agent = SEARCH_USER_AGENTS[index_seed % len(SEARCH_USER_AGENTS)]
    return {
        **_headers(),
        "User-Agent": user_agent,
        "Accept-Language": language or "zh-cn",
        "Referer": "https://duckduckgo.com/",
    }


def _duckduckgo_result_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if "duckduckgo.com" in parsed.netloc.lower() and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return unquote(query["uddg"][0])
    return raw_url


def _bing_result_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    hostname = (parsed.hostname or "").lower()
    if not (hostname == "bing.com" or hostname.endswith(".bing.com")):
        return raw_url
    if not parsed.path.startswith("/ck/"):
        return raw_url

    query = parse_qs(parsed.query)
    raw_target = (query.get("u") or [""])[0]
    if not raw_target:
        return raw_url

    target = unquote(raw_target).strip()
    if target.startswith(("http://", "https://")):
        return target

    encoded = target[2:] if target.startswith("a1") else target
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{encoded}{padding}").decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return raw_url
    decoded = unquote(decoded)
    if decoded.startswith(("http://", "https://")):
        return decoded
    return raw_url


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_multiline(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    return "\n\n".join(lines)


def normalize_search_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []

    anchors = soup.select("a.result__a")
    for anchor in anchors:
        title = _clean_text(anchor.get_text(" "))
        href = anchor.get("href") or ""
        if not title or not href:
            continue

        snippet = ""
        parent = anchor.find_parent(class_=re.compile(r"result"))
        if parent:
            snippet_node = parent.select_one(".result__snippet")
            if snippet_node:
                snippet = _clean_text(snippet_node.get_text(" "))

        if not snippet:
            next_snippet = anchor.find_next(class_="result__snippet")
            if next_snippet:
                snippet = _clean_text(next_snippet.get_text(" "))

        results.append(SearchResult(title=title, url=_duckduckgo_result_url(href), snippet=snippet))
        if len(results) >= max_results:
            break

    return [result.__dict__ for result in results]


def normalize_duckduckgo_lite_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        title = _clean_text(anchor.get_text(" "))
        if not title or not href:
            continue
        if href.startswith(("#", "javascript:")):
            continue
        if "/l/?" not in href and not href.startswith(("http://", "https://")):
            continue

        url = _duckduckgo_result_url(urljoin("https://lite.duckduckgo.com", href))
        if not url.startswith(("http://", "https://")) or url in seen_urls:
            continue

        snippet = ""
        parent = anchor.find_parent(["tr", "td", "div"])
        snippet_node = parent.find_next(class_=re.compile(r"result-snippet|snippet")) if parent else None
        if not snippet_node:
            snippet_node = anchor.find_next(class_=re.compile(r"result-snippet|snippet"))
        if snippet_node:
            snippet = _clean_text(snippet_node.get_text(" "))

        results.append(SearchResult(title=title, url=url, snippet=snippet))
        seen_urls.add(url)
        if len(results) >= max_results:
            break

    return [result.__dict__ for result in results]


def _duckduckgo_challenge_reason(status_code: int, html: str) -> str:
    text = (html or "").lower()
    signals: list[str] = []
    if status_code == 202:
        signals.append("status=202")
    for marker in (
        "anomaly-modal",
        "unfortunately, bots use duckduckgo too",
        "challenge-form",
        "anomaly.js",
    ):
        if marker in text:
            signals.append(marker)
    if signals:
        return "duckduckgo_challenge: " + ", ".join(signals)
    return ""


def _bing_challenge_reason(status_code: int, html: str) -> str:
    text = (html or "").lower()
    signals: list[str] = []
    if status_code in {403, 429}:
        signals.append(f"status={status_code}")
    for marker in (
        "b_captchaform",
        "/turing/captcha",
        "are you a human",
        "one last step",
        "unusual traffic",
        "verify you are",
        "captcha",
    ):
        if marker in text:
            signals.append(marker)
    if signals:
        return "bing_challenge: " + ", ".join(signals)
    return ""


def normalize_searxng_results(payload: dict[str, Any], max_results: int = 5) -> list[dict[str, str]]:
    results: list[dict[str, Any]] = []
    for item in payload.get("results", []):
        title = _clean_text(str(item.get("title") or ""))
        url = str(item.get("url") or "").strip()
        snippet = _clean_text(str(item.get("content") or item.get("snippet") or ""))
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return [result.__dict__ for result in results]


def normalize_searxng_html_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []

    for item in soup.select("article.result"):
        anchor = item.select_one("h3 a[href], a[href]")
        if not anchor:
            continue
        title = _clean_text(anchor.get_text(" "))
        url = str(anchor.get("href") or "").strip()
        if not title or not url:
            continue

        snippet = ""
        snippet_node = item.select_one(".content, .result-content, p")
        if snippet_node:
            snippet = _clean_text(snippet_node.get_text(" "))

        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break

    return [result.__dict__ for result in results]


def normalize_custom_search_api_results(
    payload: Any,
    spec: dict[str, Any],
    max_results: int = 5,
) -> list[dict[str, str]]:
    results, _diagnostics = normalize_custom_search_api_results_with_diagnostics(payload, spec, max_results=max_results)
    return results


def normalize_custom_search_api_results_with_diagnostics(
    payload: Any,
    spec: dict[str, Any],
    max_results: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results_path = _custom_path_candidates(spec, "results_path", DEFAULT_CUSTOM_RESULTS_PATHS)
    raw_results, matched_results_path = _get_by_dot_path_candidates_with_path(payload, results_path, [])
    raw_items = _coerce_custom_result_items(raw_results)

    title_path = _custom_path_candidates(spec, "title_path", DEFAULT_CUSTOM_TITLE_PATHS)
    url_path = _custom_path_candidates(spec, "url_path", DEFAULT_CUSTOM_URL_PATHS)
    snippet_path = _custom_path_candidates(spec, "snippet_path", DEFAULT_CUSTOM_SNIPPET_PATHS)

    results: list[dict[str, Any]] = []
    missing_title = 0
    missing_url = 0
    matched_title_path = ""
    matched_url_path = ""
    matched_snippet_path = ""
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_title, current_title_path = _get_by_dot_path_candidates_with_path(item, title_path, "")
        raw_url, current_url_path = _get_by_dot_path_candidates_with_path(item, url_path, "")
        raw_snippet, current_snippet_path = _get_by_dot_path_candidates_with_path(item, snippet_path, "")
        title = _clean_text(str(raw_title or ""))
        url = str(raw_url or "").strip()
        snippet = _clean_text(str(raw_snippet or ""))
        if current_title_path and not matched_title_path:
            matched_title_path = current_title_path
        if current_url_path and not matched_url_path:
            matched_url_path = current_url_path
        if current_snippet_path and not matched_snippet_path:
            matched_snippet_path = current_snippet_path
        if not title:
            missing_title += 1
        if not url:
            missing_url += 1
        if not title or not url:
            continue
        result: dict[str, Any] = {"title": title, "url": url, "snippet": snippet}
        metadata = _custom_result_metadata(item, spec)
        if metadata:
            result["metadata"] = metadata
        results.append(result)
        if len(results) >= max_results:
            break

    diagnostics = {
        "results_path": matched_results_path or _path_hint(results_path),
        "title_path": matched_title_path or _path_hint(title_path),
        "url_path": matched_url_path or _path_hint(url_path),
        "snippet_path": matched_snippet_path or _path_hint(snippet_path),
        "raw_result_count": len(raw_items),
        "usable_result_count": len(results),
        "missing_title": missing_title,
        "missing_url": missing_url,
    }
    return results, diagnostics


def _custom_search_empty_results_reason(diagnostics: dict[str, Any]) -> str:
    parts = [
        f"raw_result_count={diagnostics.get('raw_result_count', 0)}",
        f"usable_result_count={diagnostics.get('usable_result_count', 0)}",
    ]
    for key in ("results_path", "title_path", "url_path", "snippet_path"):
        value = diagnostics.get(key)
        if value:
            parts.append(f"{key}={value}")
    for key in ("missing_title", "missing_url"):
        value = int(diagnostics.get(key) or 0)
        if value:
            parts.append(f"{key}={value}")
    return "custom api returned no usable results: " + ", ".join(parts)


def _validate_custom_search_api_payload(payload: Any, spec: dict[str, Any]) -> None:
    code_path = spec.get("success_code_path")
    if not code_path:
        return

    actual_code = _get_by_dot_path_candidates(payload, code_path)
    expected_codes = spec.get("success_codes", [0, 200])
    if not isinstance(expected_codes, (list, tuple, set)):
        expected_codes = [expected_codes]
    normalized_expected = {str(code) for code in expected_codes}
    if str(actual_code) in normalized_expected:
        return

    message = _get_by_dot_path_candidates(payload, spec.get("message_path", "message"), "")
    detail = f": {message}" if message else ""
    raise SearchBackendUnavailableError(f"custom api response code mismatch: {actual_code}{detail}")


async def _search_duckduckgo(
    query: str,
    max_results: int,
    region: str,
    language: str,
) -> tuple[str, list[dict[str, str]]]:
    attempts = (
        (
            "duckduckgo_html_post",
            "POST",
            "https://html.duckduckgo.com/html/",
            {"q": query, "b": "", "l": region or "wt-wt"},
            normalize_search_results,
        ),
        (
            "duckduckgo_html_get",
            "GET",
            "https://html.duckduckgo.com/html/",
            {"q": query, "kl": region or "wt-wt"},
            normalize_search_results,
        ),
        (
            "duckduckgo_lite",
            "POST",
            "https://lite.duckduckgo.com/lite/",
            {"q": query, "kl": region or "wt-wt"},
            normalize_duckduckgo_lite_results,
        ),
    )
    errors: list[str] = []
    async with httpx.AsyncClient(headers=_search_headers(language), timeout=REQUEST_TIMEOUT, max_redirects=5) as client:
        for attempt_name, method, url, payload, parser in attempts:
            try:
                if method == "POST":
                    response = await client.post(url, data=payload, follow_redirects=True)
                else:
                    response = await client.get(url, params=payload, follow_redirects=True)
                challenge_reason = _duckduckgo_challenge_reason(response.status_code, response.text)
                if challenge_reason:
                    raise SearchBackendUnavailableError(challenge_reason)
                response.raise_for_status()
                results = parser(response.text, max_results=max_results)
                if not results:
                    raise EmptySearchResultsError("empty_results")
                backend = "duckduckgo_lite" if attempt_name == "duckduckgo_lite" else "duckduckgo_html"
                return backend, results
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{attempt_name}: {type(exc).__name__}: {exc}")
    raise SearchBackendUnavailableError("duckduckgo attempts failed: " + "; ".join(errors))


def normalize_mojeek_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []

    for anchor in soup.select("a.title[href]"):
        title = _clean_text(anchor.get_text(" "))
        url = str(anchor.get("href") or "").strip()
        if not title or not url:
            continue

        snippet = ""
        parent = anchor.find_parent(["li", "div", "article"])
        snippet_node = parent.select_one("p.s, .s, p") if parent else None
        if not snippet_node:
            snippet_node = anchor.find_next("p", class_="s") or anchor.find_next("p")
        if snippet_node:
            snippet = _clean_text(snippet_node.get_text(" "))

        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break

    return [result.__dict__ for result in results]


def normalize_bing_cn_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []

    for item in soup.select("li.b_algo"):
        anchor = item.select_one("h2 a[href]") or item.select_one("a[href]")
        if not anchor:
            continue
        title = _clean_text(anchor.get_text(" "))
        url = _bing_result_url(str(anchor.get("href") or "").strip())
        if not title or not url:
            continue

        snippet = ""
        snippet_node = item.select_one(".b_caption p") or item.select_one("p")
        if snippet_node:
            snippet = _clean_text(snippet_node.get_text(" "))

        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break

    return [result.__dict__ for result in results]


def normalize_bing_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    return normalize_bing_cn_results(html, max_results=max_results)


def _technical_source_score(url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    score = 0
    if host == "github.com" or host.endswith(".github.com"):
        score += 65
    if host.startswith("docs.") or ".docs." in host or "readthedocs.io" in host:
        score += 40
    if host in {"pypi.org", "www.npmjs.com", "crates.io", "pkg.go.dev"}:
        score += 35
    if host in {"stackoverflow.com", "developer.mozilla.org"}:
        score += 30
    if any(part in host for part in ("docs", "developer", "dev", "api")):
        score += 15
    if any(part in path for part in ("/docs", "/documentation", "/guide", "/reference", "/api")):
        score += 10
    if any(bad in host for bad in ("blogspot.", "medium.com", "csdn.", "51cto.", "jianshu.")):
        score -= 15
    return score


def rank_search_results(results: list[dict[str, str]], query: str = "") -> list[dict[str, str]]:
    ranked = list(results)
    query_terms = _search_query_terms(query)
    scores = {
        id(item): _technical_source_score(item.get("url", "")) + _search_result_query_score(item, query_terms)
        for item in ranked
    }

    for index in range(1, len(ranked)):
        current = ranked[index]
        current_score = scores[id(current)]
        if current_score <= 0:
            continue
        max_shift = 2 if current_score >= 60 else 1
        new_index = index
        while new_index > 0 and index - new_index < max_shift:
            previous = ranked[new_index - 1]
            previous_score = scores[id(previous)]
            if current_score - previous_score < 30:
                break
            new_index -= 1
        if new_index != index:
            ranked.pop(index)
            ranked.insert(new_index, current)

    return ranked


SEARCH_QUERY_STOPWORDS = {
    "about",
    "and",
    "api",
    "best",
    "comparison",
    "deep",
    "dive",
    "explained",
    "guide",
    "how",
    "introduction",
    "intro",
    "mechanism",
    "overview",
    "performance",
    "the",
    "tutorial",
    "what",
    "with",
}
SEARCH_QUERY_COMPARISON_TERMS = {"vs", "versus"}


def _search_query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in re.findall(r"[\w.+#-]+", query.lower()):
        term = raw.strip("._-")
        if term in SEARCH_QUERY_COMPARISON_TERMS:
            if term not in terms:
                terms.append(term)
            continue
        if len(term) < 3 or term in SEARCH_QUERY_STOPWORDS:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _short_search_retry_query(query: str) -> str | None:
    terms = _search_query_terms(query)
    if len(terms) < 5:
        return None
    short_length = 3
    for index, term in enumerate(terms[:4]):
        if term in SEARCH_QUERY_COMPARISON_TERMS and index + 1 < len(terms):
            short_length = max(short_length, index + 2)
            break
    short_terms = terms[:short_length]
    short_query = " ".join(short_terms)
    if short_query and short_query != query.lower():
        return short_query
    return None


def _query_result_relevance_score(query: str, results: list[dict[str, str]], limit: int = 3) -> int:
    terms = _search_query_terms(query)[:5]
    if not terms:
        return 0
    matched_terms: set[str] = set()
    for result in results[:limit]:
        haystack = " ".join(
            str(result.get(field) or "").lower()
            for field in ("title", "snippet", "url")
        )
        matched_terms.update(term for term in terms if term in haystack)
    return len(matched_terms)


def _search_result_query_score(result: dict[str, str], terms: list[str]) -> int:
    if not terms:
        return 0
    haystack = " ".join(
        str(result.get(field) or "").lower()
        for field in ("title", "snippet", "url")
    )
    matched = sum(1 for term in terms[:6] if term in haystack)
    return matched * 12


def _should_retry_search_with_short_query(query: str, results: list[dict[str, str]]) -> str | None:
    short_query = _short_search_retry_query(query)
    if not short_query or not results:
        return None
    original_core_score = _query_result_relevance_score(short_query, results)
    if original_core_score <= 2:
        return short_query
    return None


def _provider_backend_name(provider: str) -> str:
    normalized = _normalize_search_provider_name(provider)
    custom_name = _custom_search_api_name(normalized)
    if custom_name:
        return f"{CUSTOM_SEARCH_PROVIDER_PREFIX}{custom_name}"
    if normalized == "duckduckgo":
        return "duckduckgo_html"
    return normalized


def _search_backend_cooldown_status(backend: str) -> dict[str, Any] | None:
    entry = _SEARCH_BACKEND_COOLDOWNS.get(backend)
    if not entry:
        return None
    retry_after = int(max(0, float(entry.get("until", 0)) - time.time()) + 0.999)
    if retry_after <= 0:
        _SEARCH_BACKEND_COOLDOWNS.pop(backend, None)
        return None
    return {
        "reason": str(entry.get("reason") or "previous backend failure"),
        "retry_after_seconds": retry_after,
        "failures": int(entry.get("failures") or 1),
    }


def _should_cooldown_search_error(exc: Exception, config: GlobalWebConfig | Any) -> bool:
    if isinstance(exc, EmptySearchResultsError):
        return bool(_cfg(config, "search_cooldown_empty_results", True))
    if isinstance(exc, SearchBackendUnavailableError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        return status in {403, 429} or 500 <= status <= 599
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException))


def _record_search_backend_failure(backend: str, exc: Exception, config: GlobalWebConfig | Any) -> int | None:
    if not _should_cooldown_search_error(exc, config):
        return None
    base_seconds = _bounded_int(_cfg(config, "search_backend_cooldown_seconds", 60), 60, 0, 3_600)
    if base_seconds <= 0:
        return None
    previous = _SEARCH_BACKEND_COOLDOWNS.get(backend) or {}
    failures = int(previous.get("failures") or 0) + 1
    cooldown_seconds = min(base_seconds * (2 ** max(0, failures - 1)), MAX_SEARCH_BACKEND_COOLDOWN_SECONDS)
    _SEARCH_BACKEND_COOLDOWNS[backend] = {
        "until": time.time() + cooldown_seconds,
        "reason": f"{type(exc).__name__}: {exc}",
        "failures": failures,
    }
    return cooldown_seconds


def _clear_search_backend_cooldown(backend: str) -> None:
    _SEARCH_BACKEND_COOLDOWNS.pop(backend, None)


def _search_backend_cooldown_report() -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for backend in list(_SEARCH_BACKEND_COOLDOWNS):
        status = _search_backend_cooldown_status(backend)
        if status:
            report[backend] = status
    return report


def _search_backend_health_request(provider: str, config: GlobalWebConfig | Any) -> tuple[str, str, dict[str, str], dict[str, str]]:
    """Return backend name, URL, query params, and headers for a lightweight search probe."""
    provider = _normalize_search_provider_name(provider)
    custom_name = _custom_search_api_name(provider)
    if custom_name:
        spec = (_cfg(config, "custom_search_apis", {}) or {}).get(custom_name)
        if not isinstance(spec, dict):
            raise ValueError(f"custom search api not configured: {custom_name}")
        context = {"query": "cc-web health", "max_results": "1", "language": "zh-cn", "region": "wt-wt"}
        context["unix_timestamp"] = str(int(time.time()))
        url = str(_render_search_api_template(spec.get("url", ""), context)).strip()
        if not url:
            raise ValueError(f"custom search api url is empty: {custom_name}")
        params = _render_search_api_template(spec.get("params", {"q": "{query}"}), context)
        headers = _render_search_api_template(spec.get("headers", {}), context)
        return (
            f"{CUSTOM_SEARCH_PROVIDER_PREFIX}{custom_name}",
            url,
            params if isinstance(params, dict) else {},
            headers if isinstance(headers, dict) else {},
        )
    if provider == "searxng":
        base_url = _cfg(config, "searxng_base_url", "").rstrip("/")
        if not base_url:
            raise ValueError("searxng_base_url 不能为空")
        return provider, f"{base_url}/search", {"q": "cc-web health", "format": "json"}, {}
    if provider == "bing":
        return provider, "https://www.bing.com/search", {"q": "cc-web health", "mkt": "zh-CN", "setlang": "zh-cn"}, {}
    if provider == "bing_cn":
        return provider, "https://cn.bing.com/search", {"q": "cc-web health", "mkt": "zh-CN", "setlang": "zh-cn"}, {}
    if provider == "duckduckgo":
        return provider, "https://html.duckduckgo.com/html/", {"q": "cc-web health", "kl": "wt-wt"}, {}
    if provider == "mojeek":
        return provider, "https://www.mojeek.com/search", {"q": "cc-web health"}, {}
    raise ValueError(f"不支持的搜索后端: {provider}")


async def _search_with_provider(
    provider: str,
    query: str,
    max_results: int,
    region: str,
    language: str,
    config: GlobalWebConfig | Any,
) -> tuple[str, list[dict[str, str]]]:
    provider = _normalize_search_provider_name(provider)
    custom_name = _custom_search_api_name(provider)

    if custom_name:
        spec = (_cfg(config, "custom_search_apis", {}) or {}).get(custom_name)
        if not isinstance(spec, dict):
            raise ValueError(f"custom search api not configured: {custom_name}")
        context = {
            "query": query,
            "max_results": str(max_results),
            "language": language or "zh-cn",
            "region": region or "wt-wt",
            "unix_timestamp": str(int(time.time())),
        }
        url = str(_render_search_api_template(spec.get("url", ""), context)).strip()
        if not url:
            raise ValueError(f"custom search api url is empty: {custom_name}")
        method = str(spec.get("method") or "GET").strip().upper()
        headers = _render_search_api_template(spec.get("headers", {}), context)
        params = _render_search_api_template(spec.get("params", {"q": "{query}"}), context)
        json_body = _render_search_api_template(spec.get("json"), context) if "json" in spec else None
        request_headers = {**_headers(), **(headers if isinstance(headers, dict) else {})}
        async with httpx.AsyncClient(headers=request_headers, timeout=REQUEST_TIMEOUT, max_redirects=5) as client:
            if method == "POST":
                response = await client.post(
                    url,
                    params=params if isinstance(params, dict) else None,
                    json=json_body,
                    follow_redirects=True,
                )
            else:
                response = await client.get(
                    url,
                    params=params if isinstance(params, dict) else None,
                    follow_redirects=True,
                )
            response.raise_for_status()
            payload = response.json()
            _validate_custom_search_api_payload(payload, spec)
            results, diagnostics = normalize_custom_search_api_results_with_diagnostics(payload, spec, max_results=max_results)
            if not results:
                raise EmptySearchResultsError(_custom_search_empty_results_reason(diagnostics))
            return (
                f"{CUSTOM_SEARCH_PROVIDER_PREFIX}{custom_name}",
                results,
            )

    if provider == "searxng":
        base_url = _cfg(config, "searxng_base_url", "").rstrip("/")
        if not base_url:
            raise ValueError("searxng_base_url 不能为空")
        async with httpx.AsyncClient(headers=_headers(), timeout=REQUEST_TIMEOUT, max_redirects=5) as client:
            json_error: Exception | None = None
            try:
                response = await client.get(
                    f"{base_url}/search",
                    params={"q": query, "format": "json", "language": language or "zh-cn"},
                    follow_redirects=True,
                )
                response.raise_for_status()
                return "searxng", normalize_searxng_results(response.json(), max_results=max_results)
            except Exception as exc:
                json_error = exc

            response = await client.get(
                f"{base_url}/search",
                params={"q": query, "format": "html", "language": language or "zh-cn"},
                follow_redirects=True,
            )
            response.raise_for_status()
            results = normalize_searxng_html_results(response.text, max_results=max_results)
            if not results and json_error:
                raise json_error
            return "searxng_html", results

    if provider == "bing":
        async with httpx.AsyncClient(
            headers={**_headers(), "Accept-Language": language or "zh-cn"},
            timeout=REQUEST_TIMEOUT,
            max_redirects=5,
        ) as client:
            response = await client.get(
                "https://www.bing.com/search",
                params={"q": query, "mkt": "zh-CN", "setlang": language or "zh-cn"},
                follow_redirects=True,
            )
            challenge_reason = _bing_challenge_reason(response.status_code, response.text)
            if challenge_reason:
                raise SearchBackendUnavailableError(challenge_reason)
            response.raise_for_status()
            return "bing", normalize_bing_results(response.text, max_results=max_results)

    if provider == "bing_cn":
        async with httpx.AsyncClient(
            headers={**_headers(), "Accept-Language": language or "zh-cn"},
            timeout=REQUEST_TIMEOUT,
            max_redirects=5,
        ) as client:
            response = await client.get(
                "https://cn.bing.com/search",
                params={"q": query, "mkt": "zh-CN", "setlang": language or "zh-cn"},
                follow_redirects=True,
            )
            challenge_reason = _bing_challenge_reason(response.status_code, response.text)
            if challenge_reason:
                raise SearchBackendUnavailableError(challenge_reason)
            response.raise_for_status()
            return "bing_cn", normalize_bing_cn_results(response.text, max_results=max_results)

    if provider == "duckduckgo":
        return await _search_duckduckgo(query, max_results=max_results, region=region, language=language)

    if provider == "mojeek":
        async with httpx.AsyncClient(
            headers={**_headers(), "Accept-Language": language or "zh-cn"},
            timeout=REQUEST_TIMEOUT,
            max_redirects=5,
        ) as client:
            response = await client.get(
                "https://www.mojeek.com/search",
                params={"q": query},
                follow_redirects=True,
            )
            response.raise_for_status()
            return "mojeek", normalize_mojeek_results(response.text, max_results=max_results)

    raise ValueError(f"不支持的搜索后端: {provider}")


def _best_content_node(soup: BeautifulSoup):
    for selector in ("main", "article", "[role=main]", ".content", "#content"):
        node = soup.select_one(selector)
        if node and _clean_text(node.get_text(" ")):
            return node
    return soup.body or soup


def _absolute_links(soup: BeautifulSoup, base_url: str) -> None:
    if not base_url:
        return
    for node in soup.find_all("a"):
        href = node.get("href")
        if href:
            node["href"] = urljoin(base_url, href)


def _domain_matches(host: str, domains: tuple[str, ...]) -> bool:
    normalized = (host or "").lower().strip(".")
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def _add_signal(signals: list[str], signal: str) -> None:
    if signal and signal not in signals:
        signals.append(signal)


def _extract_html_title(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    if soup.title:
        return _clean_text(soup.title.get_text(" "))
    return ""


def _safe_response_text(response: httpx.Response, limit: int = 5000) -> str:
    try:
        if not response.content:
            return ""
        return response.text[:limit]
    except httpx.ResponseNotRead:
        return ""


def _diagnostics_response(
    issue_type: str,
    confidence: str,
    signals: list[str],
) -> dict[str, Any]:
    recommendation = "抓取失败原因不明确；建议稍后重试，或换用搜索结果摘要和其他来源。"
    if issue_type in {"captcha_or_challenge", "blocked_or_waf", "login_required", "timeout_suspected_antibot"}:
        recommendation = "目标站点疑似启用了反爬、人机验证或登录墙；建议改用搜索摘要、官方来源或其他可访问来源。"
    elif issue_type == "js_required":
        recommendation = "目标页面可能需要浏览器渲染；当前轻量 HTTP 抓取不支持重型浏览器模式，建议换用可访问来源。"
    elif issue_type == "network_timeout":
        recommendation = "请求超时；建议稍后重试，或改用搜索摘要和其他来源。"
    return {
        "type": issue_type,
        "confidence": confidence,
        "signals": signals,
        "recommendation": recommendation,
    }


def _fetch_failure_guidance(error_type: str, recommendation: str | None = None) -> dict[str, Any]:
    if error_type == "network_timeout":
        return {
            "retryable": True,
            "retry_after_seconds": 30,
            "do_not_retry_reason": "Transient timeout; do not repeat immediately with the same URL.",
            "recommended_next_action": recommendation
            or "Retry later, run health_check if failures persist, or use research_brief/search results.",
        }

    if error_type == "fetch_safety":
        return {
            "retryable": False,
            "do_not_retry_reason": "Blocked by fetch safety policy; do not retry the same URL.",
            "recommended_next_action": recommendation or "Use an absolute http/https URL from a public source.",
        }

    if error_type in {"captcha_or_challenge", "blocked_or_waf", "login_required", "timeout_suspected_antibot", "js_required"}:
        return {
            "retryable": False,
            "do_not_retry_reason": f"Target returned {error_type}; repeating fetch_url with the same URL is unlikely to help.",
            "recommended_next_action": recommendation or "Use search summaries, official sources, or another accessible source.",
        }

    return {
        "retryable": False,
        "do_not_retry_reason": "Fetch failed; do not repeat the identical call unless the URL or parameters change.",
        "recommended_next_action": recommendation or "Try research_brief, use another source, or narrow the request.",
    }


def _diagnose_fetch_response(requested_url: str, response: httpx.Response, markdown: str = "") -> dict[str, Any] | None:
    final_url = str(response.url or requested_url)
    parsed = urlparse(final_url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    status_code = response.status_code
    text_sample = _safe_response_text(response)
    title = _extract_html_title(text_sample)
    haystack = " ".join([requested_url, final_url, title, text_sample[:3000], markdown[:1000]]).lower()
    signals: list[str] = []

    if status_code in {401, 403, 429, 503}:
        _add_signal(signals, f"status_code={status_code}")
    if status_code == 403:
        _add_signal(signals, "forbidden")
    if status_code == 429:
        _add_signal(signals, "rate_limited")
    if _domain_matches(host, ANTI_BOT_DOMAINS):
        _add_signal(signals, f"known anti-bot domain: {host}")
    for hint in CHALLENGE_PATH_HINTS:
        if hint in path:
            _add_signal(signals, f"challenge path: {hint}")
    for hint in LOGIN_PATH_HINTS:
        if hint in path:
            _add_signal(signals, f"login path: {hint}")
    for keyword in CHALLENGE_KEYWORDS:
        if keyword.lower() in haystack:
            _add_signal(signals, f"challenge keyword: {keyword}")
    for keyword in LOGIN_KEYWORDS:
        if keyword.lower() in haystack:
            _add_signal(signals, f"login keyword: {keyword}")
    for keyword in JS_REQUIRED_KEYWORDS:
        if keyword.lower() in haystack:
            _add_signal(signals, f"js keyword: {keyword}")

    if any(signal.startswith("challenge ") for signal in signals):
        return _diagnostics_response("captcha_or_challenge", "high", signals)
    if any(signal.startswith("login ") for signal in signals):
        return _diagnostics_response("login_required", "high", signals)
    if status_code in {403, 429}:
        confidence = "high" if _domain_matches(host, ANTI_BOT_DOMAINS) else "medium"
        return _diagnostics_response("blocked_or_waf", confidence, signals)
    if status_code in {401}:
        return _diagnostics_response("login_required", "medium", signals)
    if any(signal.startswith("js keyword") for signal in signals):
        return _diagnostics_response("js_required", "medium", signals)
    if markdown != "" and len(_clean_text(markdown)) < 200 and _domain_matches(host, ANTI_BOT_DOMAINS):
        _add_signal(signals, f"short extracted content: {len(_clean_text(markdown))} chars")
        return _diagnostics_response("captcha_or_challenge", "medium", signals)
    return None


def _diagnose_fetch_exception(url: str, exc: Exception) -> dict[str, Any] | None:
    if isinstance(exc, FetchDiagnosticError):
        return exc.diagnostics
    if isinstance(exc, httpx.HTTPStatusError):
        return _diagnose_fetch_response(url, exc.response)
    if isinstance(exc, (httpx.ReadTimeout, httpx.TimeoutException)):
        host = (urlparse(url).hostname or "").lower()
        signals = [f"{type(exc).__name__}: {exc}"]
        if _domain_matches(host, ANTI_BOT_DOMAINS):
            _add_signal(signals, f"known anti-bot domain: {host}")
            return _diagnostics_response("timeout_suspected_antibot", "medium", signals)
        return _diagnostics_response("network_timeout", "low", signals)
    return None


def extract_markdown(html: str, base_url: str = "", extract_mode: str = "auto") -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "template", "svg"]):
        node.decompose()
    _absolute_links(soup, base_url)

    mode = (extract_mode or "auto").lower()
    if mode == "text":
        return _clean_multiline(soup.get_text("\n"))

    content_node = soup.body or soup if mode == "body" else _best_content_node(soup)
    markdown = html_to_markdown(str(content_node), heading_style="ATX", strip=["img"])
    return _clean_multiline(markdown)


def slice_text_window(text: str, max_chars: int, start_index: int = 0) -> dict[str, Any]:
    content_length = len(text)
    start = max(0, min(int(start_index or 0), content_length))
    end = min(start + max(1, int(max_chars or 1)), content_length)
    truncated = end < content_length
    return {
        "text": text[start:end].rstrip(),
        "content_length": content_length,
        "returned_range": {"start": start, "end": end},
        "truncated": truncated,
        "next_start_index": end if truncated else None,
    }


def _truncation_guidance(url: str, max_chars: int, extract_mode: str, window: dict[str, Any]) -> dict[str, Any] | None:
    if not window.get("truncated"):
        return None
    next_start = window.get("next_start_index")
    remaining = max(0, int(window.get("content_length", 0)) - int(next_start or 0))
    return {
        "remaining_chars": remaining,
        "do_not_retry_reason": "Do not repeat fetch_url with the same start_index; continue from next_start_index.",
        "next_call": {
            "tool": "fetch_url",
            "url": url,
            "max_chars": max_chars,
            "start_index": next_start,
            "extract_mode": extract_mode,
        },
    }


async def _limited_get(
    client: httpx.AsyncClient,
    url: str,
    allow_private_networks: bool = False,
    trusted_proxy_domains: tuple[str, ...] | list[str] | None = None,
    trust_tun_fake_ip_dns: bool = False,
) -> httpx.Response:
    current_url = await validate_fetch_url_async(
        url,
        allow_private_networks=allow_private_networks,
        trusted_proxy_domains=trusted_proxy_domains,
        trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
    )
    redirect_count = 0
    for _ in range(6):
        target = build_fetch_target(
            current_url,
            allow_private_networks=allow_private_networks,
            trusted_proxy_domains=trusted_proxy_domains,
            trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
        )
        scheme = urlparse(target.url).scheme
        request_url = target.connect_url if scheme == "http" else target.url
        request_headers = {"Host": target.host_header}
        async with client.stream(
            "GET",
            request_url,
            headers=request_headers,
            follow_redirects=False,
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    response.raise_for_status()
                current_url = await validate_fetch_url_async(
                    urljoin(target.url, location),
                    allow_private_networks=allow_private_networks,
                    trusted_proxy_domains=trusted_proxy_domains,
                    trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
                )
                redirect_count += 1
                continue

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise FetchSafetyError("页面过大，已停止下载")
                chunks.append(chunk)
            full_response = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
                request=httpx.Request("GET", target.url, headers=response.request.headers),
                extensions={**response.extensions, "cc_web_redirect_count": redirect_count},
            )
            full_response.raise_for_status()
            return full_response
    raise FetchSafetyError("重定向次数过多，已停止抓取")


async def _fetch_jina_reader_markdown(
    client: httpx.AsyncClient,
    url: str,
    trust_tun_fake_ip_dns: bool = False,
) -> dict[str, str]:
    safe_url = await validate_fetch_url_async(
        url,
        allow_private_networks=False,
        trust_tun_fake_ip_dns=trust_tun_fake_ip_dns,
    )
    # Jina Reader 的公开用法是给原 URL 加前缀：https://r.jina.ai/https://example.com
    reader_url = f"https://r.jina.ai/{safe_url}"
    response = await client.get(reader_url, follow_redirects=True)
    response.raise_for_status()
    return {"markdown": _clean_multiline(response.text), "reader_url": str(response.url)}


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise FetchSafetyError("PDF 提取需要安装可选依赖 pypdf") from exc

    try:
        import io

        reader = PdfReader(io.BytesIO(content))
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = _clean_multiline("\n".join(pages))
    except Exception as exc:
        raise FetchSafetyError(f"PDF 提取失败: {type(exc).__name__}: {exc}") from exc
    if not text:
        raise FetchSafetyError("PDF 未提取到可读文本")
    return text


def _format_response_content(response: httpx.Response, extract_mode: str, config: GlobalWebConfig | Any | None = None) -> str:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type in {"text/html", "application/xhtml+xml"} or not content_type:
        return extract_markdown(response.text, str(response.url), extract_mode=extract_mode)
    if content_type in {"text/plain", "text/markdown", "text/x-markdown"}:
        return _clean_multiline(response.text)
    if content_type in {"application/json", "application/ld+json"} or content_type.endswith("+json"):
        try:
            return json.dumps(response.json(), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return _clean_multiline(response.text)
    if content_type == "application/pdf":
        if _cfg(config, "enable_pdf_extract", False):
            return _extract_pdf_text(response.content)
        raise FetchSafetyError("暂不支持 PDF 正文提取，请后续接入 PDF 提取工具")
    if not content_type.startswith("text/"):
        raise FetchSafetyError(f"拒绝抓取二进制或暂不支持的内容类型: {content_type or 'unknown'}")
    return _clean_multiline(response.text)


def _cache_key(
    url: str,
    extract_mode: str,
    backend_hint: str = "direct",
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> str:
    raw = json.dumps(
        {
            "schema_version": schema_version,
            "url": url,
            "extract_mode": extract_mode,
            "backend": backend_hint,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _search_cache_key(
    query: str,
    max_results: int,
    region: str,
    language: str,
    providers: tuple[str, ...],
    domains: tuple[str, ...] = (),
    schema_version: int = SEARCH_CACHE_SCHEMA_VERSION,
) -> str:
    raw = json.dumps(
        {
            "schema_version": schema_version,
            "query": query,
            "max_results": max_results,
            "region": region,
            "language": language,
            "providers": list(providers),
            "domains": list(domains),
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(config: GlobalWebConfig | Any, key: str) -> Path:
    return Path(_cfg(config, "cache_dir", str(DEFAULT_CACHE_DIR))) / f"{key}.json"


def _read_cache(config: GlobalWebConfig, key: str) -> dict[str, Any] | None:
    if _cfg(config, "cache_ttl_seconds", 0) <= 0 or _cfg(config, "allow_private_networks", False):
        return None
    path = _cache_path(config, key)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(data.get("cached_at", 0))
        if datetime.now(timezone.utc).timestamp() - fetched_at > _cfg(config, "cache_ttl_seconds", 0):
            return None
        return data
    except Exception:
        return None


def _write_cache(config: GlobalWebConfig, key: str, data: dict[str, Any]) -> None:
    if _cfg(config, "cache_ttl_seconds", 0) <= 0 or _cfg(config, "allow_private_networks", False):
        return
    try:
        path = _cache_path(config, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {**data, "cached_at": datetime.now(timezone.utc).timestamp()}
        path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def _read_search_cache(config: GlobalWebConfig | Any, key: str) -> dict[str, Any] | None:
    ttl = _cfg(config, "search_cache_ttl_seconds", 0)
    if ttl <= 0:
        return None
    path = _cache_path(config, f"search-{key}")
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(data.get("cached_at", 0))
        if datetime.now(timezone.utc).timestamp() - fetched_at > ttl:
            return None
        return data
    except Exception:
        return None


def _write_search_cache(config: GlobalWebConfig | Any, key: str, data: dict[str, Any]) -> None:
    ttl = _cfg(config, "search_cache_ttl_seconds", 0)
    if ttl <= 0:
        return
    try:
        path = _cache_path(config, f"search-{key}")
        path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {**data, "cached_at": datetime.now(timezone.utc).timestamp()}
        path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def _strip_result_ref_ids(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in result.items() if key != "ref_id"} for result in results]


def _attach_search_ref_ids(response: dict[str, Any]) -> dict[str, Any]:
    copied = {**response}
    results: list[dict[str, Any]] = []
    for result in response.get("results", []):
        clean_result = {key: value for key, value in dict(result).items() if key != "ref_id"}
        url = str(clean_result.get("url") or "")
        if url:
            clean_result["ref_id"] = _BROWSE_SESSION.add(
                "search",
                url,
                title=str(clean_result.get("title") or ""),
                snippet=str(clean_result.get("snippet") or ""),
            )
        results.append(clean_result)
    copied["results"] = results
    return copied


def _ref_not_found_response(ref_id: str, status: StatusRecorder) -> dict[str, Any]:
    return {
        "ok": False,
        "ref_id": ref_id,
        "error": f"ref_id not found or expired: {ref_id}",
        "error_type": "ref_not_found",
        "status_summary": "fetch failed: ref_id not found",
        "steps": status.steps,
        "retryable": False,
        "do_not_retry_reason": "The ref_id is missing or expired; do not retry the same ref_id.",
        "recommended_next_action": "Run web_search again or pass a direct URL.",
    }


def _looks_like_ref_id(value: str | None) -> bool:
    return bool(str(value or "").strip().startswith("ccweb-"))


async def _resolve_fetch_input(
    url: str | None,
    ref_id: str | None,
    status: StatusRecorder,
) -> tuple[str, str]:
    candidate_ref_id = str(ref_id or "").strip()
    raw_url = str(url or "").strip()
    if not candidate_ref_id and _looks_like_ref_id(raw_url):
        candidate_ref_id = raw_url
    if not candidate_ref_id:
        return raw_url, ""

    entry = _BROWSE_SESSION.get(candidate_ref_id)
    if not entry:
        await status.add("cc-web: ref_id not found")
        raise KeyError(candidate_ref_id)
    await status.add(f"cc-web: resolved {candidate_ref_id} to {entry.url}")
    return entry.url, candidate_ref_id


def _canonical_url_for_match(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    hostname = (parsed.hostname or "").lower().strip(".")
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), hostname, path, "", "", ""))


def _result_matches_target_url(result_url: str, target_url: str) -> bool:
    return bool(result_url and target_url and _canonical_url_for_match(result_url) == _canonical_url_for_match(target_url))


def _fetch_search_fallback_allowed(url: str, config: Any) -> bool:
    if not _cfg(config, "enable_fetch_search_fallback", False):
        return False
    domains = _normalize_domains(_cfg(config, "fetch_search_fallback_domains", ()))
    if not domains:
        return False
    hostname = (urlparse(url).hostname or "").lower().strip(".")
    return bool(hostname and _domain_matches(hostname, domains))


def _config_with_search_providers(config: Any, providers: tuple[str, ...], force: bool = False) -> Any:
    if isinstance(config, GlobalWebConfig) and not force:
        return replace(config, search_provider=providers[0], search_providers=providers)

    class SearchProviderConfigProxy:
        search_provider = providers[0]
        search_providers = providers
        force_search_provider = force

        def __getattr__(self, name: str) -> Any:
            return getattr(config, name)

    return SearchProviderConfigProxy()


def _non_fallback_search_providers(config: Any, fallback_providers: tuple[str, ...]) -> tuple[str, ...]:
    configured = _normalize_search_providers(
        _cfg(config, "search_providers", None),
        _cfg(config, "search_provider", "duckduckgo"),
    )
    fallback_set = set(fallback_providers)
    providers = tuple(provider for provider in configured if provider not in fallback_set)
    if providers:
        return providers
    return tuple(provider for provider in DEFAULT_SEARCH_PROVIDERS if provider not in fallback_set)


def _search_result_key(result: dict[str, Any]) -> str:
    url = str(result.get("url") or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme.lower(), (parsed.netloc or "").lower(), parsed.path or "/", "", parsed.query, ""))


def _merge_parallel_search_results(
    successful_results: list[tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    merged: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for backend, results in successful_results:
        for result in results:
            key = _search_result_key(result)
            if not key:
                continue
            source_backends = [backend]
            candidate = dict(result)
            candidate["source_backends"] = source_backends
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
                continue

            existing_backends = existing.setdefault("source_backends", [])
            if backend not in existing_backends:
                existing_backends.append(backend)
            existing_snippet = str(existing.get("snippet") or "")
            candidate_snippet = str(candidate.get("snippet") or "")
            if len(candidate_snippet) > len(existing_snippet):
                candidate["source_backends"] = existing_backends
                merged[key] = candidate
    return list(merged.values())


def _parallel_search_backend_name(successful_backends: list[str]) -> str:
    if not successful_backends:
        return "parallel"
    return "parallel:" + "+".join(successful_backends)


def _parallel_search_candidate_providers(
    providers: tuple[str, ...],
    config: GlobalWebConfig | Any,
) -> tuple[list[str], list[dict[str, Any]], str]:
    max_backends = _bounded_int(_cfg(config, "search_parallel_max_backends", 2), 2, 1, 5)
    candidates: list[str] = []
    attempted_backends: list[dict[str, Any]] = []
    fallback_reason = ""
    for provider in providers:
        backend = _provider_backend_name(provider)
        if (
            _custom_search_api_name(provider)
            and not _cfg(config, "force_search_provider", False)
            and not _custom_search_general_enabled(config, provider)
        ):
            attempted_backends.append(
                {
                    "backend": backend,
                    "ok": False,
                    "skipped": True,
                    "error": "general_search_disabled",
                }
            )
            if not fallback_reason:
                fallback_reason = f"{backend} skipped: general_search_disabled"
            continue

        cooldown = _search_backend_cooldown_status(backend)
        if cooldown:
            attempted_backends.append(
                {
                    "backend": backend,
                    "ok": False,
                    "skipped": True,
                    "error": f"cooldown: {cooldown['reason']}",
                    "retry_after_seconds": cooldown["retry_after_seconds"],
                }
            )
            if not fallback_reason:
                fallback_reason = f"{backend} skipped: cooldown {cooldown['retry_after_seconds']}s remaining"
            continue

        candidates.append(provider)
        if len(candidates) >= max_backends:
            break
    return candidates, attempted_backends, fallback_reason


def _search_result_to_surrogate_markdown(result: dict[str, Any]) -> str:
    title = _clean_text(str(result.get("title") or "Search fallback result"))
    url = str(result.get("url") or "").strip()
    snippet = _clean_multiline(str(result.get("snippet") or ""))
    parts = [f"# {title}"]
    if url:
        parts.append(f"Source: {url}")
    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        lines = []
        for key, value in metadata.items():
            if value in (None, ""):
                continue
            if isinstance(value, (dict, list)):
                value_text = json.dumps(value, ensure_ascii=False)
            else:
                value_text = str(value)
            lines.append(f"{_metadata_label(str(key))}: {_clean_text(value_text)}")
        if lines:
            parts.append("\n".join(lines))
    if snippet:
        parts.append(snippet)
    return "\n\n".join(parts)


async def _search_web_parallel(
    query: str,
    provider_query: str,
    providers: tuple[str, ...],
    max_results: int,
    provider_result_limit: int,
    region: str,
    language: str,
    normalized_domains: tuple[str, ...],
    config: GlobalWebConfig | Any,
    status: StatusRecorder,
) -> dict[str, Any] | None:
    candidate_providers, attempted_backends, fallback_reason = _parallel_search_candidate_providers(providers, config)
    if len(candidate_providers) < 2:
        return None

    await status.add(
        "cc-web: parallel search "
        + ", ".join(_provider_backend_name(provider) for provider in candidate_providers)
        + f" for {query}"
    )

    async def run_provider(provider: str) -> tuple[str, str, list[dict[str, Any]] | None, dict[str, Any] | None, Exception | None]:
        backend = _provider_backend_name(provider)
        try:
            backend, results = await _search_with_provider(
                provider,
                provider_query,
                provider_result_limit,
                region,
                language,
                config,
            )
            backend, results, retry_info = await _retry_provider_with_short_query_if_needed(
                provider,
                backend,
                provider_query,
                list(results or []),
                provider_result_limit,
                region,
                language,
                config,
            )
            if retry_info:
                await status.add(f"cc-web: {backend} retried with shorter query {retry_info['query']}")
            return provider, backend, results, retry_info, None
        except Exception as exc:  # noqa: BLE001
            return provider, backend, None, None, exc

    provider_results = await asyncio.gather(*(run_provider(provider) for provider in candidate_providers))
    successful_results: list[tuple[str, list[dict[str, Any]]]] = []
    successful_backends: list[str] = []
    query_retries: list[dict[str, Any]] = []
    last_error = ""
    for _provider, backend, results, retry_info, exc in provider_results:
        if exc is not None:
            last_error = f"{type(exc).__name__}: {exc}"
            attempted = {"backend": backend, "ok": False, "error": last_error}
            cooldown_seconds = _record_search_backend_failure(backend, exc, config)
            if cooldown_seconds:
                attempted["cooldown_seconds"] = cooldown_seconds
            attempted_backends.append(attempted)
            if not fallback_reason:
                fallback_reason = f"{backend} failed: {last_error}"
            continue
        _clear_search_backend_cooldown(backend)
        attempted_backends.append({"backend": backend, "ok": True})
        successful_backends.append(backend)
        successful_results.append((backend, list(results or [])))
        if retry_info:
            query_retries.append(retry_info)

    if not successful_results:
        return {
            "ok": False,
            "query": query,
            "backend": _parallel_search_backend_name(successful_backends),
            "status_summary": "search failed: all parallel search backends failed",
            "steps": status.steps,
            "fetched_at": now_iso(),
            "error": last_error or "all parallel search providers failed",
            "fallback_reason": fallback_reason,
            "attempted_backends": attempted_backends,
            "retryable": True,
            "retry_after_seconds": 30,
            "do_not_retry_reason": "All configured search backends failed; do not repeat the same search immediately.",
            "recommended_next_action": "Run health_check to inspect search backends, retry later, or change search_providers.",
            "results": [],
        }

    results = _merge_parallel_search_results(successful_results)
    raw_result_count = len(results[:provider_result_limit])
    if _cfg(config, "prefer_technical_sources", True):
        results = rank_search_results(results, provider_query)
    removed_by_domain = 0
    if normalized_domains:
        results, removed_by_domain = filter_search_results_by_domains(results, normalized_domains)
    usable_result_count = len(results[:max_results])
    backend = _parallel_search_backend_name(successful_backends)
    await status.add(f"cc-web: {backend} returned {usable_result_count} usable results")

    response: dict[str, Any] = {
        "ok": True,
        "query": query,
        "backend": backend,
        "status_summary": f"search complete: {usable_result_count} results from {backend}",
        "steps": status.steps,
        "fetched_at": now_iso(),
        "results": results[:max_results],
        "attempted_backends": attempted_backends,
        "aggregation": {
            "mode": "parallel",
            "successful_backends": successful_backends,
        },
    }
    if normalized_domains:
        response["domain_filter"] = {
            "domains": list(normalized_domains),
            "removed_results": removed_by_domain,
        }
    if "bing_cn" in successful_backends:
        response["search_scope_note"] = BING_CN_SCOPE_NOTE
    if query_retries:
        response["query_retries"] = query_retries
    if fallback_reason:
        response["fallback_reason"] = fallback_reason
    if usable_result_count == 0:
        response.update(
            {
                "ok": False,
                "status_summary": "search failed: parallel search returned no usable results",
                "error": f"empty_results_after_parallel_aggregation: raw={raw_result_count}, removed_by_domain={removed_by_domain}",
                "retryable": True,
                "retry_after_seconds": 30,
                "do_not_retry_reason": "Parallel search returned no usable results; do not repeat the same search immediately.",
                "recommended_next_action": "Try a broader query, remove domain filters, or run health_check.",
            }
        )
    return response


async def _retry_provider_with_short_query_if_needed(
    provider: str,
    backend: str,
    provider_query: str,
    results: list[dict[str, str]],
    provider_result_limit: int,
    region: str,
    language: str,
    config: GlobalWebConfig | Any,
) -> tuple[str, list[dict[str, str]], dict[str, Any] | None]:
    retry_query = _should_retry_search_with_short_query(provider_query, results)
    if not retry_query:
        return backend, results, None
    retry_backend, retry_results = await _search_with_provider(
        provider,
        retry_query,
        provider_result_limit,
        region,
        language,
        config,
    )
    original_score = _query_result_relevance_score(retry_query, results)
    retry_score = _query_result_relevance_score(retry_query, retry_results)
    if retry_results and retry_score > original_score:
        return retry_backend, retry_results, {
            "backend": retry_backend,
            "reason": "low_relevance_results",
            "original_query": provider_query,
            "query": retry_query,
            "original_score": original_score,
            "retry_score": retry_score,
        }
    raise LowRelevanceSearchResultsError(
        f"low_relevance_results: query={provider_query!r}, retry_query={retry_query!r}, "
        f"original_score={original_score}, retry_score={retry_score}"
    )


def _exact_search_result(candidates: list[dict[str, Any]], safe_url: str) -> dict[str, Any] | None:
    return next((result for result in candidates if _result_matches_target_url(str(result.get("url") or ""), safe_url)), None)


async def _discover_fetch_search_query(
    safe_url: str,
    config: Any,
    fallback_providers: tuple[str, ...],
    max_results: int,
    status: StatusRecorder,
) -> tuple[str, dict[str, Any]] | None:
    discovery_providers = _non_fallback_search_providers(config, fallback_providers)
    if not discovery_providers:
        return None
    await status.add(f"cc-web: discovering fetch fallback title via {', '.join(discovery_providers)}")
    discovery = await search_web(
        safe_url,
        max_results=max_results,
        config=_config_with_search_providers(config, discovery_providers),
    )
    if not isinstance(discovery, dict) or not discovery.get("ok"):
        return None
    exact = _exact_search_result(discovery.get("results", []), safe_url)
    if not exact:
        return None
    query = _clean_text(f"{exact.get('title', '')} {exact.get('snippet', '')}")
    if not query or query == safe_url:
        return None
    return query, {
        "backend": discovery.get("backend", _provider_backend_name(discovery_providers[0])),
        "url": exact.get("url"),
        "title": exact.get("title"),
        "snippet": exact.get("snippet"),
    }


async def _try_fetch_search_fallback(
    safe_url: str,
    config: Any,
    status: StatusRecorder,
    search_query: str | None = None,
) -> dict[str, Any] | None:
    if not _fetch_search_fallback_allowed(safe_url, config):
        return None
    providers = _normalize_optional_search_providers(_cfg(config, "fetch_search_fallback_providers", ()))
    if not providers:
        return None

    max_results = _bounded_int(_cfg(config, "max_fetch_search_fallback_results", 3), 3, 1, 10)
    mode = str(_cfg(config, "fetch_search_fallback_mode", "exact_or_candidates") or "exact_or_candidates").strip().lower()
    fallback_config = _config_with_search_providers(config, providers, force=True)
    query = _clean_text(search_query or safe_url)
    await status.add(f"cc-web: trying fetch search fallback via {', '.join(providers)}")
    search = await search_web(
        query,
        max_results=max_results,
        config=fallback_config,
    )
    candidates = search.get("results", []) if isinstance(search, dict) else []
    search_fallback = {
        "backend": search.get("backend", _provider_backend_name(providers[0])) if isinstance(search, dict) else _provider_backend_name(providers[0]),
        "providers": list(providers),
        "query": query,
        "exact_url_match": False,
        "candidates": candidates[:max_results],
    }
    if not isinstance(search, dict) or not search.get("ok"):
        search_fallback["error"] = search.get("error", "search fallback failed") if isinstance(search, dict) else "search fallback failed"
        return {"ok": False, "search_fallback": search_fallback}

    exact = _exact_search_result(candidates, safe_url)
    discovered_from: dict[str, Any] | None = None
    if not exact and not search_query:
        discovered = await _discover_fetch_search_query(safe_url, config, providers, max_results, status)
        if discovered:
            query, discovered_from = discovered
            await status.add("cc-web: retrying fetch search fallback with discovered title")
            search = await search_web(
                query,
                max_results=max_results,
                config=fallback_config,
            )
            candidates = search.get("results", []) if isinstance(search, dict) else []
            search_fallback.update(
                {
                    "backend": search.get("backend", _provider_backend_name(providers[0])) if isinstance(search, dict) else _provider_backend_name(providers[0]),
                    "query": query,
                    "candidates": candidates[:max_results],
                    "discovered_from": discovered_from,
                }
            )
            if not isinstance(search, dict) or not search.get("ok"):
                search_fallback["error"] = search.get("error", "search fallback failed") if isinstance(search, dict) else "search fallback failed"
                return {"ok": False, "search_fallback": search_fallback}
            exact = _exact_search_result(candidates, safe_url)
    if exact:
        search_fallback["exact_url_match"] = True
        search_fallback["matched_url"] = str(exact.get("url") or "")
        search_fallback["matched_by"] = "url"
        if discovered_from:
            search_fallback["discovered_from"] = discovered_from
        return {
            "ok": True,
            "backend": f"search_fallback:{search_fallback['backend']}",
            "source_type": "search_result_surrogate",
            "exact_url_match": True,
            "matched_url": search_fallback["matched_url"],
            "markdown_full": _search_result_to_surrogate_markdown(exact),
            "search_fallback": search_fallback,
        }
    if mode == "exact_only":
        search_fallback["candidates"] = []
    return {"ok": False, "search_fallback": search_fallback}


async def search_web(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
    language: str = "zh-cn",
    domains: tuple[str, ...] | list[str] | str | None = None,
    config: GlobalWebConfig | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    status = StatusRecorder(status_callback)
    query = _clean_text(query)
    if not query:
        await status.add("cc-web: search query is empty")
        return {
            "ok": False,
            "error": "query 不能为空",
            "error_type": "invalid_query",
            "status_summary": "search failed: empty query",
            "steps": status.steps,
            "retryable": False,
            "do_not_retry_reason": "Empty query; do not retry until a non-empty query is provided.",
            "recommended_next_action": "Provide a concise search query.",
            "results": [],
        }

    max_results = max(1, min(int(max_results or 5), config.max_search_results))
    providers = _normalize_search_providers(
        _cfg(config, "search_providers", None),
        _cfg(config, "search_provider", "duckduckgo"),
    )
    normalized_domains = _normalize_domains(domains)
    provider_query = _query_with_domain_hints(query, normalized_domains)
    provider_result_limit = min(_cfg(config, "max_search_results", 10), max_results * 3 if normalized_domains else max_results)
    search_cache_key = _search_cache_key(
        query,
        max_results,
        region or "wt-wt",
        language or "zh-cn",
        providers,
        normalized_domains,
    )
    cached = _read_search_cache(config, search_cache_key)
    if cached:
        await status.add(f"cc-web: search cache hit for {query}")
        cached_response = {key: value for key, value in cached.items() if key != "cached_at"}
        cached_response["cache"] = "hit"
        cached_response["steps"] = status.steps
        cached_response["results"] = _strip_result_ref_ids(cached_response.get("results", []))
        return _attach_search_ref_ids(cached_response)

    attempted_backends: list[dict[str, Any]] = []
    fallback_reason = ""
    last_error = ""

    if _cfg(config, "search_parallel_enabled", False):
        parallel_response = await _search_web_parallel(
            query,
            provider_query,
            providers,
            max_results,
            provider_result_limit,
            region,
            language,
            normalized_domains,
            config,
            status,
        )
        if parallel_response is not None:
            if parallel_response.get("ok") and _cfg(config, "search_cache_ttl_seconds", 0) > 0:
                parallel_response["cache"] = "miss"
                _write_search_cache(config, search_cache_key, parallel_response)
            return _attach_search_ref_ids(parallel_response)

    for provider_index, provider in enumerate(providers):
        backend = _provider_backend_name(provider)
        if (
            _custom_search_api_name(provider)
            and not _cfg(config, "force_search_provider", False)
            and not _custom_search_general_enabled(config, provider)
        ):
            attempted_backends.append(
                {
                    "backend": backend,
                    "ok": False,
                    "skipped": True,
                    "error": "general_search_disabled",
                }
            )
            await status.add(f"cc-web: skipping {backend}, general search disabled")
            if not fallback_reason:
                fallback_reason = f"{backend} skipped: general_search_disabled"
            continue
        cooldown = _search_backend_cooldown_status(backend)
        if cooldown and provider_index < len(providers) - 1:
            attempted_backends.append(
                {
                    "backend": backend,
                    "ok": False,
                    "skipped": True,
                    "error": f"cooldown: {cooldown['reason']}",
                    "retry_after_seconds": cooldown["retry_after_seconds"],
                }
            )
            await status.add(f"cc-web: skipping {backend}, cooldown {cooldown['retry_after_seconds']}s remaining")
            if not fallback_reason:
                fallback_reason = f"{backend} skipped: cooldown {cooldown['retry_after_seconds']}s remaining"
            continue
        try:
            await status.add(f"cc-web: searching {backend} for {query}")
            backend, results = await _search_with_provider(provider, provider_query, provider_result_limit, region, language, config)
            retry_info = None
            backend, results, retry_info = await _retry_provider_with_short_query_if_needed(
                provider,
                backend,
                provider_query,
                list(results or []),
                provider_result_limit,
                region,
                language,
                config,
            )
            if retry_info:
                await status.add(f"cc-web: {backend} retried with shorter query {retry_info['query']}")
            _clear_search_backend_cooldown(backend)
            raw_result_count = len(results[:provider_result_limit])

            if _cfg(config, "prefer_technical_sources", True):
                results = rank_search_results(results, provider_query)
            removed_by_domain = 0
            if normalized_domains:
                results, removed_by_domain = filter_search_results_by_domains(results, normalized_domains)
            usable_result_count = len(results[:max_results])
            await status.add(f"cc-web: {backend} returned {usable_result_count} usable results")
            if usable_result_count == 0:
                reason = "empty_results"
                if normalized_domains and removed_by_domain:
                    reason = f"empty_results_after_domain_filter: raw={raw_result_count}, removed={removed_by_domain}"
                raise EmptySearchResultsError(reason)
            attempted_backends.append({"backend": backend, "ok": True})

            response: dict[str, Any] = {
                "ok": True,
                "query": query,
                "backend": backend,
                "status_summary": f"search complete: {usable_result_count} results from {backend}",
                "steps": status.steps,
                "fetched_at": now_iso(),
                "results": results[:max_results],
                "attempted_backends": attempted_backends,
            }
            if normalized_domains:
                response["domain_filter"] = {
                    "domains": list(normalized_domains),
                    "removed_results": removed_by_domain,
                }
            if backend == "bing_cn":
                response["search_scope_note"] = BING_CN_SCOPE_NOTE
            if retry_info:
                response["query_retry"] = retry_info
            if fallback_reason:
                response["fallback_reason"] = fallback_reason
            if _cfg(config, "search_cache_ttl_seconds", 0) > 0:
                response["cache"] = "miss"
                _write_search_cache(config, search_cache_key, response)
            return _attach_search_ref_ids(response)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            attempted = {"backend": backend, "ok": False, "error": last_error}
            cooldown_seconds = _record_search_backend_failure(backend, exc, config)
            if cooldown_seconds:
                attempted["cooldown_seconds"] = cooldown_seconds
            attempted_backends.append(attempted)
            await status.add(f"cc-web: {backend} failed, trying next backend")
            if not fallback_reason:
                fallback_reason = f"{backend} failed: {last_error}"

    await status.add("cc-web: all search backends failed")
    return {
        "ok": False,
        "query": query,
        "backend": _provider_backend_name(providers[-1]) if providers else "unknown",
        "status_summary": "search failed: all configured backends failed",
        "steps": status.steps,
        "fetched_at": now_iso(),
        "error": last_error or "all search providers failed",
        "fallback_reason": fallback_reason,
        "attempted_backends": attempted_backends,
        "retryable": True,
        "retry_after_seconds": 30,
        "do_not_retry_reason": "All configured search backends failed; do not repeat the same search immediately.",
        "recommended_next_action": "Run health_check to inspect search backends, retry later, or change search_providers.",
        "results": [],
    }


async def fetch_page(
    url: str | None = None,
    max_chars: int | None = None,
    start_index: int = 0,
    extract_mode: str = "auto",
    ref_id: str | None = None,
    search_fallback_query: str | None = None,
    config: GlobalWebConfig | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    status = StatusRecorder(status_callback)
    trust_tun_fake_ip_dns = bool(_cfg(config, "trust_tun_fake_ip_dns", False))
    fetch_policy_kwargs = {
        "allow_private_networks": _cfg(config, "allow_private_networks", False),
        "trusted_proxy_domains": _cfg(config, "trusted_proxy_domains", ()),
    }
    if trust_tun_fake_ip_dns:
        fetch_policy_kwargs["trust_tun_fake_ip_dns"] = True
    try:
        target_url, resolved_from_ref_id = await _resolve_fetch_input(url, ref_id, status)
    except KeyError as exc:
        return _ref_not_found_response(str(exc.args[0]), status)
    ref_entry = _BROWSE_SESSION.get(resolved_from_ref_id) if resolved_from_ref_id else None
    if not ref_entry:
        ref_entry = _BROWSE_SESSION.find_by_url(target_url)
    if not search_fallback_query and ref_entry:
        search_fallback_query = _clean_text(f"{ref_entry.title} {ref_entry.snippet}")

    network_policy = await evaluate_network_policy_async(
        target_url,
        **fetch_policy_kwargs,
    )
    try:
        safe_url = await validate_fetch_url_async(
            target_url,
            **fetch_policy_kwargs,
        )
    except FetchSafetyError as exc:
        await status.add("cc-web: fetch blocked by URL safety policy")
        result = {
            "ok": False,
            "url": target_url,
            "error": str(exc),
            "error_type": "fetch_safety",
            "status_summary": "fetch failed: URL safety policy",
            "steps": status.steps,
            "network_policy": network_policy,
        }
        if resolved_from_ref_id:
            result["resolved_from_ref_id"] = resolved_from_ref_id
        result.update(_fetch_failure_guidance("fetch_safety"))
        return result

    max_chars = max(1, min(int(max_chars or _cfg(config, "default_fetch_chars", 10_000)), _cfg(config, "max_fetch_chars", 60_000)))
    fallback_reason = ""
    reader_url = ""
    cache_key = _cache_key(safe_url, extract_mode)
    cached = _read_cache(config, cache_key)

    try:
        if cached:
            await status.add(f"cc-web: cache hit for {safe_url}")
            markdown_full = str(cached.get("markdown_full", ""))
            backend = str(cached.get("backend", "direct"))
            final_url = str(cached.get("final_url", safe_url))
            status_code = cached.get("status_code")
            content_type = str(cached.get("content_type", ""))
            reader_url = str(cached.get("reader_url", ""))
            fallback_reason = str(cached.get("fallback_reason", ""))
            redirect_count = int(cached.get("redirect_count", 0) or 0)
            cache_state = "hit"
        else:
            async with httpx.AsyncClient(headers=_headers(), timeout=REQUEST_TIMEOUT, max_redirects=5) as client:
                try:
                    await status.add(f"cc-web: fetching {safe_url}")
                    response = await _limited_get(
                        client,
                        safe_url,
                        **fetch_policy_kwargs,
                    )
                    final_url = await validate_fetch_url_async(
                        str(response.url),
                        **fetch_policy_kwargs,
                    )
                    content_type = response.headers.get("content-type", "")
                    await status.add(f"cc-web: extracting markdown from {safe_url}")
                    markdown_full = _format_response_content(response, extract_mode=extract_mode, config=config)
                    diagnostics = _diagnose_fetch_response(safe_url, response, markdown=markdown_full)
                    if diagnostics:
                        raise FetchDiagnosticError(diagnostics["recommendation"], diagnostics)
                    backend = "direct"
                    status_code: int | None = response.status_code
                    redirect_count = int(response.extensions.get("cc_web_redirect_count", 0) or 0)

                    if _cfg(config, "enable_jina_fallback", True) and len(markdown_full) < _cfg(config, "jina_min_chars", 300):
                        fallback_reason = f"direct content too short: {len(markdown_full)} chars"
                        await status.add("cc-web: direct content too short, trying Jina Reader")
                        jina = await _fetch_jina_reader_markdown(
                            client,
                            safe_url,
                            **({"trust_tun_fake_ip_dns": True} if trust_tun_fake_ip_dns else {}),
                        )
                        markdown_full = jina["markdown"]
                        reader_url = jina["reader_url"]
                        backend = "jina_reader"
                        content_type = "text/markdown"
                except Exception as exc:
                    if not _cfg(config, "enable_jina_fallback", True):
                        raise
                    primary_diagnostics = _diagnose_fetch_exception(safe_url, exc)
                    fallback_reason = f"{type(exc).__name__}: {exc}"
                    await status.add("cc-web: direct fetch failed, trying Jina Reader")
                    try:
                        jina = await _fetch_jina_reader_markdown(
                            client,
                            safe_url,
                            **({"trust_tun_fake_ip_dns": True} if trust_tun_fake_ip_dns else {}),
                        )
                    except Exception as fallback_exc:
                        if primary_diagnostics:
                            _add_signal(
                                primary_diagnostics["signals"],
                                f"jina_fallback_failed={type(fallback_exc).__name__}: {fallback_exc}",
                            )
                            raise FetchDiagnosticError(primary_diagnostics["recommendation"], primary_diagnostics) from fallback_exc
                        raise
                    markdown_full = jina["markdown"]
                    reader_url = jina["reader_url"]
                    backend = "jina_reader"
                    final_url = safe_url
                    status_code = None
                    content_type = "text/markdown"
                    redirect_count = 0
            cache_state = "miss"
            if backend != "jina_reader":
                _write_cache(
                    config,
                    cache_key,
                    {
                        "markdown_full": markdown_full,
                        "backend": backend,
                        "final_url": final_url,
                        "status_code": status_code,
                        "content_type": content_type,
                        "reader_url": reader_url,
                        "fallback_reason": fallback_reason,
                        "redirect_count": redirect_count,
                    },
                )

        window = slice_text_window(markdown_full, max_chars=max_chars, start_index=start_index)
        result = {
            "ok": True,
            "url": safe_url,
            "final_url": final_url,
            "backend": backend,
            "status_summary": f"fetch complete: {backend}, {window['content_length']} chars",
            "steps": status.steps,
            "status_code": status_code,
            "content_type": content_type,
            "fetched_at": now_iso(),
            "markdown": window["text"],
            "content_length": window["content_length"],
            "returned_range": window["returned_range"],
            "truncated": window["truncated"],
            "next_start_index": window["next_start_index"],
            "cache": cache_state,
            "network_policy": network_policy,
            "redirect_count": redirect_count,
        }
        if resolved_from_ref_id:
            result["resolved_from_ref_id"] = resolved_from_ref_id
        if reader_url:
            result["reader_url"] = reader_url
        if fallback_reason:
            result["fallback_reason"] = fallback_reason
        truncation = _truncation_guidance(safe_url, max_chars, extract_mode, window)
        if truncation:
            result["truncation"] = truncation
        return result
    except Exception as exc:
        diagnostics = _diagnose_fetch_exception(safe_url, exc)
        error_type = diagnostics["type"] if diagnostics else "fetch_failed"
        result = {
            "ok": False,
            "url": safe_url,
            "fetched_at": now_iso(),
            "error": f"{type(exc).__name__}: {exc}",
            "error_type": error_type,
            "status_summary": f"fetch failed: {error_type}",
            "steps": status.steps,
            "network_policy": network_policy,
        }
        if resolved_from_ref_id:
            result["resolved_from_ref_id"] = resolved_from_ref_id
        if diagnostics:
            result["fetch_diagnostics"] = diagnostics
        search_fallback = await _try_fetch_search_fallback(safe_url, config, status, search_query=search_fallback_query)
        if search_fallback:
            if search_fallback.get("ok"):
                markdown_full = str(search_fallback.get("markdown_full") or "")
                window = slice_text_window(markdown_full, max_chars=max_chars, start_index=start_index)
                fallback_result = {
                    "ok": True,
                    "url": safe_url,
                    "final_url": search_fallback.get("matched_url") or safe_url,
                    "backend": search_fallback["backend"],
                    "source_type": search_fallback.get("source_type", "search_result_surrogate"),
                    "exact_url_match": bool(search_fallback.get("exact_url_match")),
                    "matched_url": search_fallback.get("matched_url"),
                    "status_summary": f"fetch fallback complete: {search_fallback['backend']}, {window['content_length']} chars",
                    "steps": status.steps,
                    "status_code": None,
                    "content_type": "text/markdown",
                    "fetched_at": now_iso(),
                    "markdown": window["text"],
                    "content_length": window["content_length"],
                    "returned_range": window["returned_range"],
                    "truncated": window["truncated"],
                    "next_start_index": window["next_start_index"],
                    "cache": "miss",
                    "network_policy": network_policy,
                    "redirect_count": 0,
                    "fallback_reason": result["error"],
                    "search_fallback": search_fallback.get("search_fallback", {}),
                }
                if resolved_from_ref_id:
                    fallback_result["resolved_from_ref_id"] = resolved_from_ref_id
                truncation = _truncation_guidance(safe_url, max_chars, extract_mode, window)
                if truncation:
                    fallback_result["truncation"] = truncation
                return fallback_result
            result["search_fallback"] = search_fallback.get("search_fallback", search_fallback)
        guidance = _fetch_failure_guidance(error_type, diagnostics.get("recommendation") if diagnostics else None)
        fallback_info = result.get("search_fallback")
        if (
            isinstance(fallback_info, dict)
            and fallback_info.get("candidates")
            and not fallback_info.get("exact_url_match")
        ):
            guidance["recommended_next_action"] = (
                "Search by title/snippet first and fetch the returned ref_id; "
                "search fallback returned candidates but none matched the requested URL exactly."
            )
            guidance["do_not_retry_reason"] = (
                "Fetch search fallback found only inexact candidates; repeating fetch_url with the same URL is unlikely to help."
            )
        result.update(guidance)
        return result


async def research_brief(
    query: str,
    max_sources: int = 3,
    max_chars_per_source: int | None = None,
    region: str = "wt-wt",
    language: str = "zh-cn",
    domains: tuple[str, ...] | list[str] | str | None = None,
    config: GlobalWebConfig | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    status = StatusRecorder(status_callback)
    max_sources = max(1, min(int(max_sources or _cfg(config, "max_brief_sources", 3)), _cfg(config, "max_brief_sources", 3)))
    max_chars_per_source = max(
        1,
        min(int(max_chars_per_source or _cfg(config, "brief_chars_per_source", 2_500)), _cfg(config, "max_fetch_chars", 60_000)),
    )

    search = await _call_with_optional_status(
        search_web,
        query,
        max_results=max(_cfg(config, "max_search_results", 10), max_sources),
        region=region,
        language=language,
        domains=domains,
        config=config,
        status_callback=status.add,
    )
    if not search.get("ok"):
        return {
            "ok": False,
            "query": query,
            "status_summary": "research brief failed: search failed",
            "steps": status.steps,
            "fetched_at": now_iso(),
            "search": search,
            "sources": [],
        }

    selected_results: list[dict[str, str]] = []
    skipped_results: list[dict[str, str]] = []
    seen_domains: set[str] = set()
    trust_tun_fake_ip_dns = bool(_cfg(config, "trust_tun_fake_ip_dns", False))
    validate_policy_kwargs = {
        "allow_private_networks": _cfg(config, "allow_private_networks", False),
        "trusted_proxy_domains": _cfg(config, "trusted_proxy_domains", ()),
    }
    if trust_tun_fake_ip_dns:
        validate_policy_kwargs["trust_tun_fake_ip_dns"] = True
    for result in search.get("results", []):
        raw_url = result.get("url", "")
        try:
            safe_url = await validate_fetch_url_async(
                raw_url,
                **validate_policy_kwargs,
            )
        except FetchSafetyError as exc:
            skipped_results.append(
                {
                    "title": result.get("title", ""),
                    "url": raw_url,
                    "reason": str(exc),
                }
            )
            continue
        result = {**result, "url": safe_url}
        parsed = urlparse(safe_url)
        domain = (parsed.hostname or "").lower()
        if _cfg(config, "dedupe_domains", True) and domain:
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
        selected_results.append(result)
        if len(selected_results) >= max_sources:
            break

    semaphore = asyncio.Semaphore(_cfg(config, "brief_concurrency", 3))

    async def fetch_source(index: int, result: dict[str, str]) -> dict[str, Any]:
        async with semaphore:
            await status.add(f"cc-web: fetching {index}/{len(selected_results)} {result.get('url', '')}")
            fetched = await _call_with_optional_status(
                fetch_page,
                result.get("url", ""),
                max_chars=max_chars_per_source,
                start_index=0,
                extract_mode="auto",
                search_fallback_query=_clean_text(f"{result.get('title', '')} {result.get('snippet', '')}"),
                config=config,
                status_callback=status.add,
            )
            source: dict[str, Any] = {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "snippet": result.get("snippet", ""),
                "ok": bool(fetched.get("ok")),
            }
            if fetched.get("ok"):
                source.update(
                    {
                        "final_url": fetched.get("final_url"),
                        "backend": fetched.get("backend"),
                        "markdown": fetched.get("markdown", ""),
                        "content_length": fetched.get("content_length"),
                        "truncated": fetched.get("truncated"),
                        "next_start_index": fetched.get("next_start_index"),
                    }
                )
                if fetched.get("truncation"):
                    source["truncation"] = fetched["truncation"]
            else:
                source["error"] = fetched.get("error", "fetch failed")
                if fetched.get("error_type"):
                    source["error_type"] = fetched.get("error_type")
                if fetched.get("fetch_diagnostics"):
                    source["fetch_diagnostics"] = fetched.get("fetch_diagnostics")
                if fetched.get("search_fallback"):
                    source["search_fallback"] = fetched.get("search_fallback")
                for key in ("retryable", "retry_after_seconds", "do_not_retry_reason", "recommended_next_action"):
                    if key in fetched:
                        source[key] = fetched[key]
            return source

    sources = await asyncio.gather(*(fetch_source(index, result) for index, result in enumerate(selected_results, start=1)))

    result = {
        "ok": True,
        "query": query,
        "backend": search.get("backend", "unknown"),
        "status_summary": f"research brief complete: {len(sources)} sources from {search.get('backend', 'unknown')}",
        "steps": status.steps,
        "fetched_at": now_iso(),
        "sources": sources,
        "skipped_results": skipped_results,
    }
    if search.get("domain_filter"):
        result["domain_filter"] = search["domain_filter"]
    return result


async def check_health(config_path: str | Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    search_providers = _normalize_search_providers(
        _cfg(config, "search_providers", None),
        _cfg(config, "search_provider", "duckduckgo"),
    )
    checks: dict[str, Any] = {
        "ok": True,
        "fetched_at": now_iso(),
        "config": config_to_dict(config),
        "search_providers": list(search_providers),
        "search_backend_status": {},
        "first_available_search_backend": None,
        "dependencies": {
            "mcp": True,
            "httpx": True,
            "beautifulsoup4": True,
            "markdownify": True,
        },
        "network_policy": {
            "allow_private_networks": config.allow_private_networks,
            "blocked_networks": [str(network) for network in BLOCKED_IP_NETWORKS],
            "trusted_proxy_networks": [str(network) for network in TRUSTED_PROXY_IP_NETWORKS],
            "trusted_proxy_domains": list(config.trusted_proxy_domains),
            "resolve_dns": True,
        },
        "network": {},
    }
    cooldown_report = _search_backend_cooldown_report()
    if cooldown_report:
        checks["search_backend_cooldowns"] = cooldown_report
    async with httpx.AsyncClient(headers=_headers(), timeout=REQUEST_TIMEOUT) as client:
        for provider in search_providers:
            try:
                backend, url, params, headers = _search_backend_health_request(provider, config)
                request_kwargs = {"params": params, "follow_redirects": True}
                if headers:
                    request_kwargs["headers"] = headers
                response = await client.get(url, **request_kwargs)
                ok = 200 <= response.status_code < 400
                if ok and backend.startswith(CUSTOM_SEARCH_PROVIDER_PREFIX):
                    custom_name = backend[len(CUSTOM_SEARCH_PROVIDER_PREFIX) :]
                    spec = (_cfg(config, "custom_search_apis", {}) or {}).get(custom_name)
                    if isinstance(spec, dict):
                        try:
                            payload = response.json()
                            _validate_custom_search_api_payload(payload, spec)
                        except Exception as exc:
                            ok = False
                            status = {"ok": False, "status": response.status_code, "error": f"{type(exc).__name__}: {exc}"}
                            checks["search_backend_status"][backend] = status
                            continue
                        results, diagnostics = normalize_custom_search_api_results_with_diagnostics(
                            payload,
                            spec,
                            max_results=1,
                        )
                        status = {
                            "ok": ok,
                            "status": response.status_code,
                            "raw_result_count": diagnostics["raw_result_count"],
                            "usable_result_count": len(results),
                        }
                        for key in ("results_path", "title_path", "url_path", "snippet_path"):
                            if diagnostics.get(key):
                                status[key] = diagnostics[key]
                        checks["search_backend_status"][backend] = status
                        if status["ok"] and checks["first_available_search_backend"] is None:
                            checks["first_available_search_backend"] = backend
                        continue
                if not ok and backend == "searxng":
                    html_response = await client.get(
                        url,
                        params={**params, "format": "html"},
                        follow_redirects=True,
                    )
                    response = html_response
                    ok = 200 <= response.status_code < 400
                status = {"ok": ok, "status": response.status_code}
                checks["search_backend_status"][backend] = status
                if status["ok"] and checks["first_available_search_backend"] is None:
                    checks["first_available_search_backend"] = backend
            except Exception as exc:
                backend = _normalize_search_provider_name(provider)
                checks["search_backend_status"][backend] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        for name, url in {
            "duckduckgo": "https://duckduckgo.com/",
            "bing_cn": "https://cn.bing.com/",
            "bing": "https://www.bing.com/",
            "github": "https://github.com/",
            "anthropic": "https://www.anthropic.com/",
            "jina_reader": "https://r.jina.ai/https://example.com/",
        }.items():
            try:
                response = await client.get(url, follow_redirects=True)
                checks["network"][name] = {"ok": response.status_code < 500, "status": response.status_code}
            except Exception as exc:
                checks["ok"] = False
                checks["network"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return checks


def to_json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
