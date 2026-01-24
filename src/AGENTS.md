# src · AGENT NOTES

## Module Map
- `src/main.py`：轻量入口，负责初始化日志、自检、Flet UI 与 TaskEngine。
- `src/config/settings.py`：配置读取与 `.env/config.ini` 持久化。
- `src/config/logger.py`：loguru 设置 + 飞书 webhook 告警（60s 冷却）。
- `src/core/system.py`：DPI 感知、环境检测、`run_self_check`。
- `src/core/engine.py`：`TaskEngine`，封装飞书轮询与微信 RPA 双队列流程。
- `src/services/feishu.py`：飞书 API/Wiki → Base Token 封装。
- `src/services/wechat.py`：PC 微信 RPA（uiautomation），包含搜号、加好友、欢迎包发送。
- `src/ui/flet_app.py`：Flet 现代 UI（日志、状态、参数配置）。
- `src/ui/flet_error.py`：启动失败/环境错误提示页。
- `src/utils/table_inspector.py`：辅助脚本，打印飞书表字段/样例数据。

## Implementation Guardrails
- **线程模型**：Flet UI 在主线程，`TaskEngine`（后台轮询）在守护线程；跨线程刷新 UI 通过日志队列 + `page.update`。
- **RPA 操作**：全部控件定位依赖 `uiautomation`，并在 `core/system.py` 配置 DPI 感知；禁止硬编码像素坐标。
- **飞书客户端**：token 刷新、表字段映射统一藏在 `src/services/feishu.py`，新增字段前先扩展此处。
- **日志**：`src/config/logger.py` 负责本地文件 + 飞书 webhook；UI 侧仍用 `queue.Queue` 取日志，避免直接操作 loguru。
- **配置**：依次读取 `.env` → `config.ini` → Flet 配置界面；新增配置记得同步 README/设置界面与 `TaskEngine` 参数。

## Testing Tips
- 源码运行：`python -m src.main`，观察 Flet UI、TaskEngine 是否正常拉起并能停止。
- API 排查：`python -m src.utils.table_inspector` 查看飞书表 schema，再对照 `PROJECT_OVERVIEW.md`。
- RPA 调试：使用 Windows 前台环境，可在 `src/services/wechat.py` 中临时增加延迟或日志，确认控件定位。

保持这些约定，任何模块改动都能与整套门店自动化方案协同运行。 ***
