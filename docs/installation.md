# 安装与验证

以下命令以 Windows PowerShell 和 `py -3.11` 为例。`<安装目录>` 请替换为你自己的项目路径。

## 安装

1. 克隆仓库：

```powershell
git clone https://github.com/JcDizzy/CC-Web-MCP.git <安装目录>
cd <安装目录>
```

2. 安装依赖：

```powershell
py -3.11 -m pip install -r requirements.txt
```

如果要运行测试，再安装开发依赖：

```powershell
py -3.11 -m pip install -r requirements-dev.txt
```

3. 注册到 Claude Code：

```powershell
claude mcp add --scope user --transport stdio cc-web -- py -3.11 .\server.py
```

如果要使用指定 Python，请把路径替换为你自己的解释器位置：

```powershell
claude mcp add --scope user --transport stdio cc-web -- <Python解释器路径> .\server.py
```

4. 确认 MCP 已注册：

```powershell
claude mcp get cc-web
```

5. 安装 Claude Code 启动指令：

```powershell
py -3.11 .\scripts\install_instructions.py
```

这个脚本会把 cc-web 路由说明写入用户级 `~\.claude\CLAUDE.md`。它的作用是让 DeepSeek、Qwen、Kimi 等第三方模型在第一次思考时就避开原生 `WebSearch`，直接使用 cc-web。

6. 安装 Claude Code hook 守卫：

```powershell
py -3.11 .\scripts\install_hook.py
```

这个脚本会合并更新用户级 `~\.claude\settings.json`，并在写入前创建 `settings.json.cc-web-backup.<时间戳>` 备份。它可以重复运行，不会重复添加同一条 hook。

Claude Code 可能用 bash 执行 hook，即使你平时在 Windows PowerShell 里使用 Claude Code。安装脚本会把 hook command 里的 Windows 路径自动归一化为 bash 友好的正斜杠形式，并给含空格的路径加 shell 引号，避免出现 `E:anacondapython.exe: command not found` 这类错误。

7. 在 Claude Code 中调用 `health_check`，确认依赖和网络连通性。

## 本地诊断

也可以在命令行先做一次本地诊断：

```powershell
py -3.11 .\scripts\doctor.py
```

默认诊断会检查本地配置、Claude Code 指令、hook 守卫和网络连通性。如果只想看 JSON 结果，便于贴给模型分析，并且暂时跳过真实网络访问：

```powershell
py -3.11 .\scripts\doctor.py --json --skip-network
```

如需限制只有 DeepSeek 等第三方模型能调用本 MCP，请保留启动指令和 hook 守卫，并在 `config.json` 的 `allowed_model_patterns` 中维护允许模型。

## 测试

```powershell
py -3.11 -m pip install -r requirements-dev.txt
py -3.11 -m pytest .\tests -q
```
