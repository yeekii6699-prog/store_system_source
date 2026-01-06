# CLAUDE.md

此文件为 Claude Code 在此代码库中工作时提供指导。

**重要：请始终使用简体中文进行所有交流和代码注释。**

## 项目概述

**门店数字化运营系统** - 面向零售/诊所门店的自动化平台，集成飞书与微信 RPA 以自动化客户获取和管理流程。

## 技术栈

- **Python 3.10+**
- **飞书多维表格 API** - 客户数据存储
- **微信 UI 自动化 (uiautomation)** - 微信 RPA 操作
- **Tkinter** - GUI 配置界面

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行程序
python -m src.main

# 启动器（带自动更新）
python launcher.py

# 检查飞书表格结构
python -m src.utils.table_inspector
```

## 项目结构

```
src/
├── main.py              # 入口点
├── config/
│   ├── settings.py      # GUI 配置与持久化
│   ├── logger.py        # 日志与飞书 webhook
│   └── network.py       # 网络配置与 SSL
├── core/
│   ├── system.py        # DPI、自检、环境检测
│   └── engine.py        # 任务引擎（双队列处理）
├── services/
│   ├── feishu.py        # 飞书客户端
│   └── wechat.py        # 微信 RPA
├── ui/
│   └── console.py       # Tk 控制台
└── utils/
    └── table_inspector.py # 飞书表格结构工具

launcher.py              # 自动更新启动器
ui_probe.py              # UI 调试工具
```

## 核心概念

### 双队列系统

| 队列 | 来源 | 状态流转 |
|-----|------|---------|
| 申请队列 | 飞书任务表"待添加" | 待添加 → 已申请 → 已绑定 |
| 欢迎队列 | 飞书任务表"已申请"/"未发送" | 未发送 → 已绑定 |

### 被动监控

扫描微信聊天列表，检测"已添加你为朋友"等系统消息，自动创建客户档案。

## 配置说明

### 必需环境变量

| 变量 | 说明 |
|-----|------|
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |
| `FEISHU_TABLE_URL` | 任务表 URL |
| `FEISHU_PROFILE_TABLE_URL` | 客户档案表 URL |

### 可选配置

| 变量 | 默认值 | 说明 |
|-----|-------|------|
| `WECHAT_EXEC_PATH` | - | 微信可执行文件路径 |
| `WELCOME_ENABLED` | 0 | 是否启用欢迎包 |
| `MONITOR_MAX_CHATS` | 6 | 被动扫描会话数 |
| `MONITOR_SCAN_INTERVAL` | 30 | 被动扫描间隔(秒) |
| `FEISHU_WEBHOOK_URL` | - | 飞书 webhook URL（告警推送） |
| `VERSION_URL` | - | 远程版本号地址（启动器） |
| `ZIP_URL` | - | 远程压缩包地址（启动器） |

### GUI 配置

运行 `python -m src.main` 后会自动弹出配置界面，也可通过 `SKIP_CONFIG_UI=1` 环境变量跳过。

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

## 常见问题

### 微信 RPA 失败

1. 检查微信是否运行
2. 确认 UI 自动化权限
3. 尝试配置 `WECHAT_EXEC_PATH`

### 飞书 API 错误

1. 检查网络连接
2. 验证 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
3. 确认应用已开通必要权限
