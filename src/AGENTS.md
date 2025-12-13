# src · AGENT NOTES

## Module Map
- `main.py`：Tkinter GUI + 业务主循环，负责加载配置、启动后台线程、管理日志/停止事件。
- `feishu_client.py`：封装飞书 OpenAPI / Wiki→Base Token 逻辑，统一处理身份、表结构、字段映射。
- `wechat_bot.py`：PC 微信 RPA（uiautomation/pyautogui），包含搜号、加好友、设置备注、发送欢迎语等动作。
- `inspect_tables.py`：辅助脚本，输出飞书多维表字段，便于排查配置。
- `config.py`（仓库根目录）：GUI 配置界面与持久化逻辑，与 `main.py` 中的 UI 交互保持一致。

## Implementation Guardrails
- **线程模型**：GUI 运行在主线程，业务轮询/日志监听在守护线程；涉及跨线程更新 Tk 控件要用队列或 `after`。
- **RPA 操作**：所有坐标或控件定位必须考虑 Windows DPI，必要时通过 `uiautomation` 名称/ControlType 绑定，避免硬编码像素。
- **飞书客户端**：统一在 `feishu_client.py` 处理 token 刷新、表字段映射；新增字段/表时先扩展这里再调用。
- **日志**：继续使用 `queue.Queue` + Tk 文本框刷新，保持用户可视化反馈；磁盘日志使用 `logs/run.log`（自动轮转）。
- **配置**：优先读取 `.env` / 环境变量，其次 GUI 输入，最后回落 `config.ini`；新增配置项时同步更新 README。

## Testing Tips
- 源码运行：`python -m src.main`，确认 GUI 能加载配置 & 线程退出调用 `os._exit(0)`。
- API 排查：用 `python -m src.inspect_tables` 查看飞书表schema，再对照 `PROJECT_OVERVIEW.md`。
- RPA 调试：使用 Windows 前台环境，必要时在 `wechat_bot.py` 中增加可控延迟，确保兼容店内 PC。

保持这些约定，任何模块改动都能与整套门店自动化方案协同运行。 ***
