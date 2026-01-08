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

### 被动监控（新的好友）

通过微信「通讯录 → 新的好友 → 等待验证」监控新好友请求：

```
点击通讯录 → 点击新的朋友 → 遍历等待验证列表 → 点击前往验证 → 点击确定 → 获取微信号 → 写入飞书(未发送) → 返回聊天列表
```

- 监控频率可在 GUI 实时调节（5-300秒）
- 无需额外去重，微信通过好友后自动从列表移除

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
| `WELCOME_TEXT` | - | 欢迎文案（多行用 `\n` 分隔） |
| `WELCOME_IMAGE_PATHS` | - | 图片路径（多张用 `|` 分隔） |
| `NEW_FRIEND_SCAN_INTERVAL` | 30 | 新的好友监控间隔(秒) |
| `PASSIVE_SCAN_JITTER` | 5 | 扫描间隔随机抖动(秒) |
| `FEISHU_WEBHOOK_URL` | - | 飞书 webhook URL（告警推送） |
| `VERSION_URL` | - | 远程版本号地址（启动器） |
| `ZIP_URL` | - | 远程压缩包地址（启动器） |
| `SKIP_CONFIG_UI` | 0 | 跳过 GUI 配置界面 |

> **提示**：运行 `python -m src.main` 后会自动弹出配置 GUI，监控频率可在运行时实时调整。

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

### 微信 RPA 失败

1. 检查微信是否运行
2. 确认 UI 自动化权限
3. 尝试配置 `WECHAT_EXEC_PATH`

### 飞书 API 错误

1. 检查网络连接
2. 验证 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
3. 确认应用已开通必要权限

### 新的好友监控无响应

1. 检查"新的朋友"列表是否可正常展开/收起
2. 确认微信窗口在前台且可见
3. 查看 DEBUG 级别日志排查

### 相关文件

- [README.md](./README.md) - 完整使用文档
- [RELEASE_GUIDE.md](./RELEASE_GUIDE.md) - 发布与回滚指南
- [.env.example](./.env.example) - 环境变量示例
