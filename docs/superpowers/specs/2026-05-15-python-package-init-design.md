# cc-web MCP Python Package 与首次初始化设计

## 背景

当前项目已经具备可运行的 MCP server、网页搜索/抓取逻辑、Claude Code hook 守卫、安装说明写入脚本和 doctor 检查脚本。但代码仍是“仓库内脚本集合”形态：`server.py`、`web.py`、`hooks/`、`scripts/` 位于项目根目录，没有 `pyproject.toml`、包目录、console scripts，也没有统一的用户配置路径。

目标是把项目整理成标准 Python package，让用户可以通过 `pipx install` 或 `pip install` 安装，并通过一个明确的初始化命令完成 Claude Code MCP 注册、routing instructions 写入和 hook 配置。`scripts/install_hook.py` 与 `scripts/install_instructions.py` 不再作为用户日常入口，避免用户频繁手动调用导致重复写入、路径漂移或配置污染。

## 设计目标

- 提供标准 Python package 结构，支持 editable install、普通 pip install 和后续 PyPI 发布。
- 提供单一用户入口 `cc-web-mcp init`，用于首次初始化 Claude Code 集成。
- 初始化命令必须幂等：已经完成且内容匹配时不重复写入。
- 所有会修改用户文件的操作都要保留备份、支持 dry-run，并尽量输出清晰的中文说明。
- MCP server、hook guard、doctor 使用同一套配置路径解析规则。
- 保留现有功能和测试覆盖，不做搜索/抓取能力的行为重写。

## 非目标

- 第一阶段不实现 Claude Code plugin 发布包。
- 第一阶段不改变 `web_search`、`fetch_url`、`research_brief` 的工具协议。
- 第一阶段不引入浏览器自动化、Playwright 或新的搜索后端。
- 第一阶段不自动发布到 PyPI，只让本地 package 结构和构建验证通过。

## 官方依据

- Python package 使用 `pyproject.toml` 定义项目元数据、依赖和 console scripts。
- Claude Code 本地 MCP 使用 stdio transport，可通过 user scope 配置为全局可用。
- Claude Code hooks 写入用户 settings，适合由初始化命令一次性配置，后续由 doctor 检查状态。

## 推荐文件结构

```text
cc_web_mcp/
  docs/
  tests/
  src/
    cc_web_mcp/
      __init__.py
      __main__.py
      cli.py
      config.py
      install.py
      doctor.py
      server.py
      web.py
      hooks/
        __init__.py
        guard.py
      data/
        default_config.json
  pyproject.toml
  README.md
  requirements-dev.txt
```

根目录旧文件迁移关系：

- `server.py` -> `src/cc_web_mcp/server.py`
- `web.py` -> `src/cc_web_mcp/web.py`
- `hooks/guard.py` -> `src/cc_web_mcp/hooks/guard.py`
- `scripts/install_hook.py` 与 `scripts/install_instructions.py` -> `src/cc_web_mcp/install.py`
- `scripts/doctor.py` -> `src/cc_web_mcp/doctor.py`
- `config.json` -> `src/cc_web_mcp/data/default_config.json`

旧 `scripts/` 可在第一阶段删除，或保留极薄兼容 wrapper。推荐删除用户入口，只在 README 中说明新命令；如果担心已有测试或旧用户习惯，可临时保留 wrapper 并输出迁移提示。

## 命令设计

`pyproject.toml` 暴露一个主命令：

```text
cc-web-mcp
```

子命令：

- `cc-web-mcp serve`：启动 stdio MCP server。
- `cc-web-mcp init`：执行首次初始化。
- `cc-web-mcp doctor`：检查本地安装与 Claude Code 配置。
- `cc-web-mcp config path`：显示当前用户配置路径。
- `cc-web-mcp config show`：显示合并后的有效配置。
- `cc-web-mcp config init`：只初始化用户配置文件，不写 Claude Code。

为了让 `claude mcp add` 使用最短稳定入口，`cc-web-mcp` 无参数时默认等价于 `cc-web-mcp serve`。这样 Claude Code 配置可以写成：

```powershell
claude mcp add --scope user --transport stdio cc-web -- cc-web-mcp
```

## 初始化命令行为

`cc-web-mcp init` 负责以下步骤：

1. 检查 `claude` CLI 是否可用。
2. 初始化用户配置文件。
3. 注册 Claude Code MCP server。
4. 写入或刷新 `~/.claude/CLAUDE.md` 中的 cc-web routing block。
5. 写入或刷新 `~/.claude/settings.json` 中的 SessionStart / PreToolUse hook。
6. 运行轻量 doctor 检查，并提示用户下一步验证命令。

支持参数：

- `--dry-run`：只展示计划修改，不写文件、不调用 `claude mcp add`。
- `--force`：强制刷新 cc-web 管理的 block 和 hook。
- `--skip-hooks`：只注册 MCP 与说明，不安装 hook。
- `--skip-instructions`：只注册 MCP 与 hook，不写 CLAUDE.md。
- `--scope user|project|local`：默认 `user`，第一版主测 user。
- `--config PATH`：指定用户配置路径。
- `--claude-memory PATH`：指定 CLAUDE.md 路径，便于测试。
- `--settings PATH`：指定 settings.json 路径，便于测试。

幂等规则：

- CLAUDE.md 使用 `<!-- cc-web-mcp:start -->` 和 `<!-- cc-web-mcp:end -->` 管理自己的 block。
- settings.json 只替换能识别为 cc-web 的旧 hook，保留无关 hook。
- MCP server 注册前先通过 `claude mcp get cc-web` 或等价检测判断是否已存在。
- 已存在且 command 与 args 匹配时，输出“无需更新”。
- 已存在但 command 不匹配时，默认提示使用 `--force` 刷新，不静默覆盖。

## 配置路径

默认配置从 package data 中的 `default_config.json` 复制到用户配置目录。建议路径：

```text
Windows: %APPDATA%\cc-web-mcp\config.json
其他系统: ~/.config/cc-web-mcp/config.json
```

配置路径解析优先级：

1. 命令行 `--config`
2. 环境变量 `CC_WEB_MCP_CONFIG`
3. 默认用户配置路径
4. package 内置默认配置

MCP server、hook guard 和 doctor 都调用同一个 `cc_web_mcp.config` 模块解析配置，避免各文件自行猜路径。

## Hook 设计

hook 命令不再写仓库绝对路径，而使用安装后的稳定入口：

```powershell
cc-web-mcp hook-guard
```

如果 Claude Code hooks 对 PATH 的继承不稳定，可退回到更稳的解释器形式：

```powershell
<当前 Python 可执行文件> -m cc_web_mcp.hooks.guard
```

第一版推荐写入 Python module 形式，因为它不依赖当前工作目录，也不依赖源码仓库路径。

hook guard 继续处理：

- `SessionStart`：记录当前 session 的 model。
- `PreToolUse`：根据配置拦截不合适的 `WebFetch` 或 cc-web 工具调用。

## Doctor 设计

`cc-web-mcp doctor` 输出文本报告，`cc-web-mcp doctor --json` 输出机器可读 JSON。检查项：

- Python executable 与版本。
- package 是否可 import。
- 用户配置文件是否存在、能否解析。
- Claude Code MCP server 是否注册。
- CLAUDE.md routing block 是否存在。
- settings.json hook 是否存在且 matcher 覆盖目标工具。
- 可选网络检查，默认保留 `--skip-network` 用于快速本地验证。

doctor 的建议文本要改为新命令，例如：

```text
Run `cc-web-mcp init` to configure Claude Code integration.
Run `cc-web-mcp init --force` to refresh existing cc-web hooks.
```

## 测试策略

必须新增或迁移以下测试：

- package import 测试：`import cc_web_mcp.server`、`import cc_web_mcp.web`。
- console script 测试：`python -m cc_web_mcp --help`、`python -m cc_web_mcp doctor --json --skip-network`。
- init dry-run 测试：不写文件、不调用真实 `claude`。
- init 幂等测试：重复执行不会重复 block 或 hook。
- hook command 测试：写入命令不包含源码仓库路径。
- doctor 迁移测试：推荐命令不再出现 `scripts/install_hook.py` 或 `scripts/install_instructions.py`。
- 现有 server/web/guard 行为测试迁移到 package import 路径。

验证命令：

```powershell
py -3.11 -m pip install -e .
py -3.11 -m pytest .\tests -q
py -3.11 -m build
```

如果本机没有 `build`，先安装：

```powershell
py -3.11 -m pip install build
```

## README 与文档更新

README 快速开始改为：

```powershell
pipx install cc-web-mcp
cc-web-mcp init
cc-web-mcp doctor
```

开发安装改为：

```powershell
py -3.11 -m pip install -e .
cc-web-mcp init --dry-run
```

文档需要同步更新：

- `docs/installation.md`
- `docs/configuration.md`
- `docs/routing-and-permissions.md`
- `docs/capabilities.md` 如有入口命令示例也要更新

## 风险与处理

- 风险：Claude Code hook 运行环境找不到 `cc-web-mcp`。
  - 处理：hook 默认写 `<sys.executable> -m cc_web_mcp.hooks.guard`。
- 风险：用户已有 cc-web MCP 配置但 command 不同。
  - 处理：默认不覆盖，提示 `--force`。
- 风险：移动配置文件后旧配置失效。
  - 处理：首次初始化时如果根目录 `config.json` 存在，可提示迁移；package 内不依赖仓库根目录。
- 风险：Windows 中文输出乱码。
  - 处理：源码统一 UTF-8，测试用 UTF-8 读写；README 明确 PowerShell 示例。
- 风险：包结构迁移导致相对 import 失效。
  - 处理：全部改为 package-relative imports，并用测试覆盖。

## 第一阶段验收标准

- `py -3.11 -m pip install -e .` 成功。
- `python -m cc_web_mcp --help` 正常。
- `cc-web-mcp doctor --json --skip-network` 可运行。
- `cc-web-mcp init --dry-run` 展示完整计划且不写真实用户文件。
- 测试套件通过。
- README 不再把直接运行 `server.py` 和 `scripts/install_*.py` 作为主要安装路径。

