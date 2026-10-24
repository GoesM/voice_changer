# 开发与发布

长期约束：GitHub `GoesM/voice_changer` 管理源码、Issue、CI 和 Releases。见 AGENTS.md。

## 模块

- `gui.py`：Tk 中文 UI、配置和首次准备。
- `assets.py`：显式下载、固定 SHA-256 和安全解压；推理时不调用下载。
- `beatrice.py`：Pedalboard 标准 VST3 宿主，版本固定的预设适配与启动自检。
- `audio.py`：WASAPI、48 kHz/20 ms 块、独立输入输出、有界队列和后台推理。
- `config.py`：本地 JSON，不自动开启麦克风。

Python/PortAudio/VST 并非硬实时保证。时钟漂移当前通过有界队列及过期丢块控制，尚无自适应重采样。原生插件崩溃会影响进程；尚无插件进程隔离。

## 验证与构建

Python 3.12 x64，安装 `requirements-build.txt`，运行 `python -m unittest discover -s tests -v`。

真实 AI 集成测试：`python scripts/benchmark.py <插件路径> <模型TOML路径> --output benchmark.json`。插件/模型由用户从官方获取，测试用合成信号，不读麦克风，不代表音质和端到端延迟。

运行 `scripts/build.ps1`：测试 → 许可证收集 → PyInstaller → EXE 自检 → ZIP 和 SHA-256。

GitHub Actions 在 main/PR 构建 Artifact，`v*` 标签发布预览版。下一版本需同步版本号、ZIP 名称、Release notes 和下载链接。源码 GPL-3.0 与 Pedalboard 兼容，保留标签对应源码与依赖许可证。发布包不捆绑模型/插件/驱动。

正式版门禁：实测麦克风到目标应用、自然度、完整延迟、硬件、长稳、安装恢复；预览版未完成这些门禁，不宣称正式验收通过。
