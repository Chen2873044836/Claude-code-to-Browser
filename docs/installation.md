# 安装与验证

以下命令以 Windows PowerShell 和 `py -3.11` 为例。

## 安装

### 开发目录安装

```powershell
git clone https://github.com/JcDizzy/CC-Web-MCP.git <安装目录>
cd <安装目录>
py -3.11 -m pip install -e .
```

如果 Windows 提示 `cc-web-mcp.exe` 安装到了不在 `PATH` 中的目录，例如 `E:\anaconda\Scripts`，安装本身仍然成功。后续命令可以直接使用模块形式：

```powershell
py -3.11 -m cc_web_mcp init
py -3.11 -m cc_web_mcp doctor
```

### uvx 安装

项目发布到 PyPI 后，推荐用 `uvx` 直接运行，不需要提前创建虚拟环境：

```powershell
uvx cc-web-mcp init --runner uvx
uvx cc-web-mcp doctor
```

`--runner uvx` 很重要：它会把 Claude Code MCP 注册成 `uvx cc-web-mcp`，避免把 uvx 临时缓存目录里的 `python.exe` 写进长期配置。

### pipx 或 pip 安装

如果想把命令长期安装到本机，也可以使用 `pipx`：

```powershell
pipx install cc-web-mcp
cc-web-mcp init
cc-web-mcp doctor
```

也可以安装到当前 Python 环境：

```powershell
py -3.11 -m pip install cc-web-mcp
py -3.11 -m cc_web_mcp init
py -3.11 -m cc_web_mcp doctor
```

## 首次初始化

只需要运行一次：

```powershell
cc-web-mcp init
```

如果通过 `uvx` 使用，推荐运行：

```powershell
uvx cc-web-mcp init --runner uvx
```

如果 `cc-web-mcp` 命令不在 `PATH` 中，使用等价命令：

```powershell
py -3.11 -m cc_web_mcp init
```

这个命令会完成四件事：

- 创建用户配置文件。
- 注册 Claude Code 用户级 stdio MCP。普通 Python 安装会注册为当前 Python 的 `-m cc_web_mcp`；`--runner uvx` 会注册为 `uvx cc-web-mcp`。
- 写入用户级 `~\.claude\CLAUDE.md` 路由提示。
- 合并更新用户级 `~\.claude\settings.json` hook 守卫，并在写入前备份。

先预览、不改文件：

```powershell
cc-web-mcp init --dry-run
```

预览 uvx 注册命令：

```powershell
uvx cc-web-mcp init --runner uvx --dry-run
```

不注册 MCP，只写配置和 hook：

```powershell
cc-web-mcp init --skip-mcp
```

刷新已存在的 cc-web hook：

```powershell
cc-web-mcp init --force
```

## 本地诊断

```powershell
cc-web-mcp doctor
```

如果 `cc-web-mcp` 命令不在 `PATH` 中，使用：

```powershell
py -3.11 -m cc_web_mcp doctor
```

只看 JSON，且跳过真实网络访问：

```powershell
cc-web-mcp doctor --json --skip-network
```

确认 Claude Code MCP 注册：

```powershell
claude mcp get cc-web
```

## 配置文件

查看当前配置路径：

```powershell
cc-web-mcp config path
```

只初始化配置文件，不写 Claude Code：

```powershell
cc-web-mcp config init
```

显示当前配置内容：

```powershell
cc-web-mcp config show
```

默认配置路径：

- Windows：`%APPDATA%\cc-web-mcp\config.json`
- macOS/Linux：`~/.config/cc-web-mcp/config.json`

也可以通过环境变量覆盖：

```powershell
$env:CC_WEB_MCP_CONFIG="D:\path\to\config.json"
cc-web-mcp doctor
```

## 旧脚本兼容

`scripts/install_instructions.py`、`scripts/install_hook.py` 和 `scripts/doctor.py` 现在只是兼容包装。新安装和日常维护请使用：

```powershell
cc-web-mcp init
cc-web-mcp doctor
```

## 开发测试

```powershell
py -3.11 -m pip install -e .
py -3.11 -m pytest .\tests -q
```
