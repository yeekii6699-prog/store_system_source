# CLAUDE.md

此文件为 Claude Code 在此代码库中工作提供指导。

> **提示**：详细使用说明请参阅 [README.md](./README.md)

---

## 项目概述

**门店数字化运营系统** - 面向零售/诊所门店的自动化平台，集成飞书与微信 RPA 以自动化客户获取和管理流程。

## 技术栈

| 类别 | 技术 |
|-----|------|
| 语言 | Python 3.10+ |
| 数据存储 | 飞书多维表格 API |
| 自动化 | 微信 UI 自动化 (uiautomation) |
| GUI | Tkinter |
| 日志 | loguru |

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行程序（开发模式）
python -m src.main

# 运行启动器（带自动更新）
python launcher.py

# 检查飞书表格结构
python -m src.utils.table_inspector

# UI 控件调试（鼠标悬停3秒输出控件信息）
python ui_probe.py

# 打包成 exe（需先安装 pyinstaller）
pyinstaller --onefile --name main_bot --clean src/main.py
# 或使用 specs 文件
pyinstaller main_bot.spec
```

## 架构概览

### 核心模块

```
src/main.py              # 入口：初始化日志 → 系统自检 → 启动 GUI 控制台
├── src/config/          # 配置层
│   ├── settings.py      # GUI 配置持久化 (config.ini)
│   ├── logger.py        # 日志 & 飞书 webhook 告警
│   └── network.py       # 网络配置与 SSL 代理
├── src/core/            # 业务核心
│   ├── system.py        # DPI、自检、环境检测
│   └── engine.py        # TaskEngine（双线程任务引擎）
└── src/services/        # 外部服务
    ├── feishu.py        # 飞书多维表格 API 客户端
    ├── wechat.py        # 微信 RPA 主类（业务流程编排）
    ├── wechat_ui.py     # UI 操作基类（窗口、按钮、对话框）
    ├── wechat_profile.py # 资料卡操作
    ├── wechat_chat.py   # 聊天消息操作
    └── wechat_contacts.py # 通讯录操作（新的朋友、验证）
```

### 微信 RPA 组合模式设计

`WeChatRPA` 主类采用组合模式，将具体操作委托给各专门模块：

| 模块 | 职责 | 关键方法 |
|-----|------|---------|
| `wechat.py` | 主类，业务流程编排 | `check_relationship()`, `apply_friend()`, `send_welcome_package()` |
| `wechat_ui.py` | UI 操作基类 | `_activate_window()`, `_click_button()`, `_send_text()`, `_send_image()` |
| `wechat_profile.py` | 资料卡操作 | `_extract_nickname_from_profile()`, `_open_profile_from_chat()` |
| `wechat_chat.py` | 聊天消息操作 | `_find_chat_message_list()`, `_chat_has_keywords()` |
| `wechat_contacts.py` | 通讯录操作 | `scan_new_friends_via_contacts()`, `_process_verified_friend()`, `_process_pending_verification()` |

这种设计的好处：职责分离、易于维护、模块可独立测试。

### 双线程并发模型

`TaskEngine` 启动两个后台线程：

| 线程 | 职责 | 触发方式 |
|-----|------|---------|
| `task-engine` | 飞书轮询 + 主动添加好友 | 每 5 秒检查"待添加"任务 |
| `passive-monitor` | 监控"新的好友"列表 | 每 30 秒扫描通讯录 |

两线程共享 `wechat_lock`，确保同一时间只有一个线程操作微信 UI。

### 线程安全与 COM 资源管理

- 每个线程（`task-engine` 和 `passive-monitor`）**独立初始化 COM**：`pythoncom.CoInitialize()`
- 退出时必须调用 `pythoncom.CoUninitialize()`，否则资源泄漏
- `wechat_lock` 是类级别的 `threading.Lock`，确保 UI 操作互斥
- 暂停时会释放 COM 资源，恢复时重新初始化

### 数据流

```
飞书任务表 ──轮询──> TaskEngine._handle_apply_queue()
                               │
                               ▼
                        微信搜索手机号 ──点击"添加到通讯录"──> 更新飞书"已申请"
                               │
                               ▼
                        被动监控 (scan_new_friends_via_contacts)
                               │
                               ▼
                        匹配飞书记录 ──发送welcome──> 更新飞书"已绑定"
```

### 飞书表格状态流转

```
待添加 ──主动添加成功──> 已申请 ──被动通过验证──> 已绑定
                │
                └──已是好友──> 已绑定
```

## 核心概念

### 主动添加（申请队列）

从飞书拉取"待添加"状态的记录：
1. 微信搜索手机号
2. 判断好友关系：
   - 已是好友 → 直接发送 welcome → "已绑定"
   - 陌生人 → 发送好友申请 → "已申请"
   - 未找到 → "未找到"

### 被动监控（新的好友）

通过微信「通讯录 → 新的朋友 → 等待验证」监控，采用**两阶段处理**：

**第一阶段**：处理所有"已添加"的好友（我主动添加后对方通过）
- 点击列表项 → 获取微信号 → 写入飞书 → 发送 welcome → 删除记录

**第二阶段**：处理所有"等待验证"的好友（对方加我）
- 点击列表项 → 点击"前往验证" → 获取微信号 → 写入飞书 → 发送 welcome → 删除记录

### 飞书 Upsert 搜索优先级

`FeishuClient.upsert_contact_profile()` 的搜索逻辑优先级：
1. **先按手机号搜索**（如果有手机号）
2. **再按昵称搜索**（用于被动加好友时匹配主动添加的记录）
3. **都找不到才新建**

### 欢迎包

支持 JSON 配置多步骤欢迎内容：
```json
[
  {"type": "text", "content": "欢迎语"},
  {"type": "image", "path": "D:\\guide\\a.png"},
  {"type": "link", "url": "https://...", "title": "标题"}
]
```

### 网络环境自动检测

`NetworkConfig` 自动检测：
- 系统代理
- VPN/代理环境（通过环境变量和系统代理判断）
- VPN 环境下增加超时时间并使用宽松 SSL 配置
- 支持手动配置代理、禁用 SSL 验证

## 配置说明

必需的环境变量配置在 `.env.example` 中，GUI 会引导填写。

| 变量 | 说明 |
|-----|------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书应用凭证 |
| `FEISHU_TABLE_URL` / `FEISHU_PROFILE_TABLE_URL` | 任务表和客户档案表链接（支持 Wiki 链接自动转换） |
| `WECHAT_EXEC_PATH` | 微信可执行文件路径（可选） |
| `WELCOME_ENABLED` | 是否启用欢迎包 (0/1) |
| `WELCOME_STEPS` | JSON 格式的欢迎步骤（支持 text/image/link） |
| `NEW_FRIEND_SCAN_INTERVAL` | 被动监控间隔，默认 30 秒 |
| `FEISHU_WEBHOOK_URL` | 错误告警推送地址 |

GUI 可实时调节：监控频率、抖动时间、飞书轮询间隔、欢迎包开关。

## 开发规范

### 代码风格

- 使用类型注解 (Type Hints)
- 日志使用 loguru，使用中文消息
- 异常处理：记录日志后继续或抛出

### Git 提交规范

```
feat: 新功能
fix: 修复 bug
refactor: 重构
docs: 文档更新
chore: 其他修改
```

## 微信 RPA 控件定位

### 通讯录监控相关控件

| 功能 | 控件类型 | Name | ClassName |
|-----|---------|------|-----------|
| 通讯录 Tab | ButtonControl | 通讯录 | mmui::XTabBarItem |
| 新的朋友入口 | ListItemControl | 新的朋友 | mmui::ContactsCellGroupView |
| 待验证列表项 | ListItemControl | *等待验证 | mmui::XTableCell |
| 前往验证按钮 | ButtonControl | 前往验证 | mmui::XOutlineButton |
| 确定按钮 | ButtonControl | 确定 | mmui::XOutlineButton |
| 微信号 | TextControl | 微信号 | mmui::ContactProfileTextView |

### 调试工具

运行 `python ui_probe.py` 将鼠标移动到目标位置，3秒后输出控件信息。

## 常见问题

| 问题 | 排查方向 |
|-----|---------|
| 微信 RPA 无响应 | 微信窗口需在前台可见；检查 DEBUG 日志 |
| 飞书 API 错误 | 检查网络/代理；验证凭证；确认应用权限 |
| 打包 PermissionError | 关闭杀毒软件或结束旧进程 |
| 更新后仍是旧版本 | 删除 `local_version.txt` |

## 相关文件

- [README.md](./README.md) - 完整使用文档
- [RELEASE_GUIDE.md](./RELEASE_GUIDE.md) - 发布与回滚指南
- [.env.example](./.env.example) - 环境变量示例
