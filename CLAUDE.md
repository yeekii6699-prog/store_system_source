# CLAUDE.md

此文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。

**重要：请始终使用简体中文进行所有交流和代码注释。**

## 项目概述

这是一个**门店数字化运营系统** - 面向零售/诊所门店的自动化平台，集成飞书与微信 RPA 以自动化客户获取和管理流程。该系统通过桥接云端 CRM（飞书）与本地桌面自动化（微信）解决客户数据孤岛问题。

## 开发命令

### 运行应用程序
```bash
# 安装依赖
pip install -r requirements.txt

# 从源码运行
python -m src.main

# 检查飞书表格结构
python -m src.utils.table_inspector
```

### 构建分发版本
```bash
# 构建可执行文件（仅限 Windows）
pyinstaller -F -w src/main.py -n main_bot --clean --noconfirm
```

## 核心架构

### 关键组件
- **入口点**: `src/main.py` - 初始化日志 → 系统检查 → 控制台应用
- **任务引擎**: `src/core/engine.py` - 管理双队列处理（申请队列 + 欢迎队列）
- **飞书服务**: `src/services/feishu.py` - 处理飞书 API 集成和令牌管理
- **微信 RPA**: `src/services/wechat.py` - 微信操作的 Windows UI 自动化
- **配置管理**: `src/config/settings.py` - 基于 GUI 的配置管理与持久化

### 处理流程
1. **申请队列**: 处理"待添加"任务 → 发送微信好友请求
2. **欢迎队列**: 处理"已申请"任务 → 向新好友发送欢迎包
3. **被动监控**: 扫描微信聊天记录中的"已添加你为朋友"通知并创建客户档案

### 重要设计模式
- **双队列系统**: 好友请求和欢迎消息的独立队列
- **被动检测**: 监控微信通知以处理手动添加的好友
- **令牌管理**: 自动飞书令牌刷新，支持 Wiki→Base 令牌转换
- **热更新系统**: `launcher.py` 检查远程版本并自动更新可执行文件

## 配置

### 必需的环境变量
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` - 飞书应用凭据
- `FEISHU_TABLE_URL` - 任务表 URL（支持 Wiki 链接）
- `FEISHU_PROFILE_TABLE_URL` - 客户档案表 URL
- `WECHAT_EXEC_PATH` - 微信可执行文件路径

### 可选配置
- `SKIP_CONFIG_UI=1` - 跳过 GUI 配置窗口
- 通过 GUI 或环境变量配置欢迎包设置
- 用于错误通知的飞书 webhook URL

## 开发环境

### 平台要求
- **仅限 Windows** - 使用 Windows UI 自动化 (`uiautomation`)
- 需要 Python 3.10+
- 必须安装微信 PC 客户端用于 RPA 测试
- 需要飞书 API 访问权限

### 安全注意事项
- 此系统对微信执行 RPA 自动化，可能违反微信服务条款
- 客户数据存储在飞书表格中
- 配置包含需要保护的 API 密钥
- 系统需要访问客户手机号和微信档案

## 项目结构
```
src/
├── main.py              # 入口点
├── config/
│   ├── settings.py      # GUI 配置与持久化
│   └── logger.py        # 日志与飞书 webhook 接收器
├── core/
│   ├── system.py        # DPI、自检、环境检测
│   └── engine.py        # TaskEngine（飞书轮询 + 微信 RPA）
├── services/
│   ├── feishu.py        # 飞书客户端封装
│   └── wechat.py        # 微信 RPA 实现
├── ui/
│   └── console.py       # Tk 控制台（日志/按钮/状态）
└── utils/
    └── table_inspector.py # 飞书表格结构辅助工具
```

## 业务背景

- **目标客户**: 深圳 33+ 家服务型门店（诊所、美容院等）
- **价值**: 每家门店每日自动化 1-2 小时的重复性任务
- **核心指标**: 追踪电话 → 微信 → 到店转化率
- **数据安全**: 将客户数据集中存储在飞书表格中