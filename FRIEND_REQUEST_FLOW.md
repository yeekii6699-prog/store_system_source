# 微信好友添加 RPA 操作流程说明

> 本文档详细描述门店系统中 **主动添加好友** 和 **被动监控新好友** 的 RPA 实现逻辑。

---

## 一、系统架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        门店数字化运营系统                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌──────────────┐         ┌──────────────┐         ┌────────────┐  │
│   │   飞书任务表   │ ◄────► │   任务引擎    │ ◄────► │  微信 RPA  │  │
│   │  (状态管理)    │  API   │  (双队列)    │  RPC   │  (UI自动化) │  │
│   └──────────────┘         └──────────────┘         └────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、状态流转图

### 2.1 主动添加流程（手动录入 → 发送申请）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           主动添加好友流程                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ① 飞书任务表录入                    ② 引擎轮询"待添加"状态               │
│   ┌──────────────────┐               ┌────────────────────────────┐     │
│   │ 客户信息录入      │               │ fetch_tasks_by_status()   │     │
│   │ 手机号/姓名       │ ────────►     │ ["待添加"]                 │     │
│   └──────────────────┘               └────────────────────────────┘     │
│                                              │                           │
│                                              ▼                           │
│                                    ┌────────────────────┐               │
│                                    │ check_relationship │               │
│                                    │ 检测目标关系状态    │               │
│                                    └────────────────────┘               │
│                                              │                           │
│                           ┌──────────────────┼──────────────────┐       │
│                           ▼                  ▼                  ▼       │
│                      ┌─────────┐        ┌─────────┐        ┌────────┐  │
│                      │ 已是好友 │        │  陌生人  │        │ 未找到  │  │
│                      │ friend  │        │ stranger │        │        │  │
│                      └────┬────┘        └────┬────┘        └────┬───┘  │
│                           │                 │                  │       │
│                           ▼                 ▼                  ▼       │
│                     更新"已申请"      apply_friend()       更新"未找到" │
│                     进入欢迎队列       发送好友申请                    │
│                           │                 │                       │
│                           │                 ▼                       │
│                           │           更新"已申请"                    │
│                           │           进入欢迎队列                     │
│                           │                 │                       │
│                           └─────────────────┴───────────────────────┘
│                                             │
│                                             ▼
│                                   ┌────────────────────┐
│                                   │ send_welcome_package │
│                                   │ 发送欢迎包（可选）   │
│                                   └────────────────────┘
│                                             │
│                                             ▼
│                                   ┌────────────────────┐
│                                   │   更新为"已绑定"    │
│                                   │   流程结束 ✓       │
│                                   └────────────────────┘
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 被动监控流程（扫码/被添加）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           被动监控新好友流程                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ① 用户扫码/被添加好友              ② 引擎轮询"等待验证"列表              │
│   ┌──────────────────┐               ┌────────────────────────────┐     │
│   │ 微信"新的朋友"    │               │ scan_new_friends_via_     │     │
│   │ "等待验证"列表    │ ◄───────     │ contacts()                 │     │
│   └──────────────────┘               └────────────────────────────┘     │
│                                              │                           │
│                                              ▼                           │
│                                    ┌────────────────────┐               │
│                                    │ 遍历待验证列表项    │               │
│                                    │ 点击"前往验证"     │               │
│                                    │ 点击"确定"通过    │               │
│                                    └────────────────────┘               │
│                                              │                           │
│                                              ▼                           │
│                                    ┌────────────────────┐               │
│                                    │ 提取微信号/昵称     │               │
│                                    │ 正则匹配: ^[A-Za-z0-│               │
│                                    │ 9_.-]{4,20}$       │               │
│                                    └────────────────────┘               │
│                                              │                           │
│                                              ▼                           │
│                                    ┌────────────────────┐               │
│                                    │ upsert_contact_    │               │
│                                    │ profile()          │               │
│                                    │ 写入飞书(状态="未发送")             │
│                                    └────────────────────┘               │
│                                              │                           │
│                                              ▼                           │
│                                    ┌────────────────────┐               │
│                                    │ 欢迎队列处理       │               │
│                                    │ send_welcome_package │              │
│                                    └────────────────────┘               │
│                                              │                           │
│                                              ▼                           │
│                                    ┌────────────────────┐               │
│                                    │   更新为"已绑定"    │               │
│                                    │   流程结束 ✓       │               │
│                                    └────────────────────┘               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、主动添加好友详细流程

### 3.1 核心方法调用链

```
任务引擎 (_handle_apply_queue)
        │
        ▼
┌───────────────────┐
│ fetch_tasks_by_   │  拉取飞书任务表中"待添加"状态的任务
│ status(["待添加"]) │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│   遍历每个任务     │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ _extract_phone_   │  从飞书字段提取手机号和姓名
│ and_name(fields)  │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ check_relationship│  检测目标微信账号关系状态
│ (phone)           │
└─────────┬─────────┘
          │
     ┌────┴────┐
     │         │
     ▼         ▼
  已是好友   是陌生人
     │         │
     ▼         ▼
update_status  apply_friend
("已申请")    发送好友申请
     │         │
     │         ▼
     │    update_status
     │    ("已申请")
     │         │
     └────┬────┘
          │
          ▼
    进入欢迎队列处理
```

### 3.2 搜索与打开资料卡

**方法**: `_search_and_open_profile(keyword)` - [wechat.py:153-299](src/services/wechat.py#L153-L299)

| 步骤 | 操作 | 代码实现 |
|-----|------|---------|
| 1 | 激活微信窗口 | `WindowControl(Name="微信")` |
| 2 | 发送 `Ctrl+F` 快捷键 | `SendKeys("^f")` |
| 3 | 输入搜索关键词 | `pyperclip.copy(keyword)` → `SendKeys("^v")` |
| 4 | 点击"网络查找" | `ListItemControl(SubName="网络查找")` |
| 5 | 等待资料卡加载 | 循环检测窗口标题 |

**资料卡窗口标题检测**:
```python
# 可能的窗口标题
profile_titles = ("详细资料", "基本资料", "资料")
```

### 3.3 发送好友申请

**方法**: `apply_friend(keyword)` - [wechat.py:320-364](src/services/wechat.py#L320-L364)

| 步骤 | 操作 | 控件定位 |
|-----|------|---------|
| 1 | 查找"添加到通讯录"按钮 | `ButtonControl(Name="添加到通讯录", searchDepth=10)` |
| 2 | 点击按钮 | `Click()` |
| 3 | 等待验证窗口 | `time.sleep(1)` |
| 4 | 查找确认窗口 | `("申请添加朋友", "发送好友申请", "好友验证", "通过朋友验证")` |
| 5 | 点击确认按钮 | `("确定", "发送", "Send", "确定(&O)", "确定(&S)")` |
| 6 | 关闭资料卡 | `SendKeys("{Esc}")` |

---

## 四、被动监控新好友详细流程

### 4.1 核心方法调用链

```
任务引擎 (_handle_passive_new_friends)
              │
              ▼
┌───────────────────────────────┐
│ scan_new_friends_via_         │  扫描"新的朋友"列表
│ contacts()                    │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│ _click_contacts_tab()         │  点击"通讯录"Tab
│ _click_new_friends_entry()    │  点击"新的朋友"入口
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│ _get_pending_verification_    │  获取"等待验证"列表
│ items()                       │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│ 遍历每个待验证项               │
└───────────────┬───────────────┘
                │
                ▼
    ┌───────────┴───────────┐
    │                       │
    ▼                       ▼
  处理单个项              处理完成
    │                       │
    ▼                       ▼
_open_verification_      返回结果列表
detail(item)             (微信号+昵称)
    │
    ▼
_click_verify_button()   点击"前往验证"
    │
    ▼
_confirm_verification()  点击"确定"前往验证
    │
    ▼
_extract_wechat_id()     提取微信号
```

### 4.2 控件定位详情

**方法**: `scan_new_friends_via_contacts()` - [wechat.py:1494-1611](src/services/wechat.py#L1494-L1611)

| 功能 | 控件类型 | Name | ClassName |
|-----|---------|------|-----------|
| 通讯录 Tab | ButtonControl | 通讯录 | `mmui::XTabBarItem` |
| 新的朋友入口 | ListItemControl | 新的朋友 | `mmui::ContactsCellGroupView` |
| 待验证列表项 | ListItemControl | `*等待验证*` | - |
| 前往验证按钮 | ButtonControl | 前往验证 | `mmui::XOutlineButton` |
| 确定按钮 | ButtonControl | 确定 | `mmui::XOutlineButton` |
| 微信号文本 | TextControl | 微信号 | `mmui::ContactProfileTextView` |
| 返回聊天 Tab | ButtonControl | 微信 | `mmui::XTabBarItem` |

### 4.3 关键步骤实现

#### Step 1: 点击通讯录 Tab

```python
def _click_contacts_tab(self) -> bool:
    contacts_tab = auto.ButtonControl(
        Name="通讯录",
        ClassName="mmui::XTabBarItem",
        searchDepth=8
    )
    if contacts_tab.Exists(2):
        contacts_tab.Click()
        return True
    return False
```

#### Step 2: 点击"新的朋友"入口

```python
def _click_new_friends_entry(self) -> bool:
    # 先检查是否已展开
    pending_items = self._get_pending_verification_items(check_only=True)
    if pending_items and len(pending_items) > 0:
        return True  # 已展开

    # 未展开则点击展开
    new_friends = auto.ListItemControl(
        Name="新的朋友",
        ClassName="mmui::ContactsCellGroupView",
        searchDepth=15
    )
    new_friends.Click()
```

#### Step 3: 获取待验证列表

```python
def _get_pending_verification_items(self, check_only=False):
    # 方法1: 使用 AutomationId
    list_container = auto.ListControl(
        AutomationId="primary_table_.contact_list",
        searchDepth=12
    )

    # 方法2: 备用 ClassName
    # ClassName="mmui::StickyHeaderRecyclerListView"

    # 遍历查找名称包含"等待验证"的项
    items = []
    for child in list_container.GetChildren():
        item_name = getattr(child, "Name", "") or ""
        if "等待验证" in item_name:
            items.append(child)
    return items
```

#### Step 4-6: 处理单个待验证项

```python
def _process_single_pending_item(self, item) -> Optional[ContactProfile]:
    # 点击进入详情
    item.Click()
    time.sleep(0.5)

    # 点击"前往验证"
    verify_btn = auto.ButtonControl(
        Name="前往验证",
        ClassName="mmui::XOutlineButton",
        searchDepth=20
    )
    verify_btn.Click()

    # 等待资料卡加载
    time.sleep(1.5)  # 增加等待时间，确保资料卡完全加载

    # 点击"确定"前往验证
    confirm_btn = auto.ButtonControl(
        Name="确定",
        ClassName="mmui::XOutlineButton",
        searchDepth=15
    )
    confirm_btn.Click()

    # 提取微信号
    wechat_id = self._extract_wechat_id_from_profile()
    nickname = self._extract_nickname_from_profile()

    return ContactProfile(wechat_id=wechat_id, nickname=nickname)
```

#### Step 7: 提取微信号

```python
def _extract_wechat_id_from_profile(self) -> Optional[str]:
    # 使用 AutomationId 定位
    wechat_id_control = auto.TextControl(
        AutomationId="right_v_view.user_info_center_view.basic_line_view.ContactProfileTextView",
        searchDepth=15
    )

    if wechat_id_control.Exists(5):
        wechat_id = wechat_id_control.Name
        # 正则验证微信号格式
        if re.match(r"^[A-Za-z0-9_.-]{4,20}$", wechat_id):
            return wechat_id

    # 备用方案: 遍历所有 TextControl 匹配格式
    for ctrl in auto.WindowControl(Name="详细资料").GetChildren():
        text = getattr(ctrl, "Name", "") or ""
        if re.match(r"^[A-Za-z0-9_.-]{4,20}$", text):
            return text
```

---

## 五、飞书数据同步

### 5.1 客户档案表操作

**方法**: `upsert_contact_profile()` - [feishu.py:432-468](src/services/feishu.py#L432-L468)

| 参数 | 说明 | 字段映射 |
|-----|------|---------|
| `phone` | 微信号（作为唯一标识） | "手机号"字段 |
| `name` | 昵称 | "姓名"字段 |
| `remark` | 备注 | "微信备注"字段 |
| `status` | 状态值 | "微信绑定状态"字段 |

### 5.2 状态更新

**方法**: `update_status()` - [feishu.py:401-408](src/services/feishu.py#L401-L408)

```python
def update_status(self, record_id: str, status: str) -> None:
    url = f"{self.profile_table_url}/{record_id}"
    payload = {"fields": {"微信绑定状态": status}}
    self._request("PUT", url, json=payload)
```

### 5.3 状态定义

| 状态 | 含义 | 触发场景 |
|-----|------|---------|
| `待添加` | 等待系统发送好友申请 | 手动录入/API写入 |
| `已申请` | 已发送好友申请，等待对方通过 | `apply_friend()` 成功后 |
| `未发送` | 被动扫描发现的好友，未发送欢迎包 | 被动监控写入 |
| `已绑定` | 好友已通过，欢迎包已发送 | `send_welcome_package()` 成功后 |
| `未找到` | 微信中未找到该用户 | `check_relationship()` 返回 `not_found` |

---

## 六、异常处理机制

### 6.1 控件不存在

- **备用方案**: 使用 ClassName 或 Name 的不同匹配方式
- **日志记录**: `logger.warning("控件不存在，使用备用方案")`

### 6.2 微信号提取超时

- **超时设置**: 等待 30 秒
- **处理**: 抛出 `TimeoutError` 并记录详细日志
- **恢复**: 继续处理下一个待验证项

### 6.3 飞书 API 错误

| 错误类型 | 处理策略 |
|---------|---------|
| 网络错误 | 跳过本次重试，记录日志 |
| 业务错误 | 继续处理下一个任务 |
| 数据验证错误 | 跳过，跳过该记录 |

### 6.4 线程安全

- 使用 `wechat_lock` 锁保护微信 RPA 操作
- 确保同一时间只有一个任务操作微信客户端

---

## 七、配置参数

### 7.1 扫描间隔配置

| 参数 | 说明 | 默认值 |
|-----|------|-------|
| `NEW_FRIEND_SCAN_INTERVAL` | 新的好友监控间隔(秒) | 30 |
| `PASSIVE_SCAN_JITTER` | 扫描间隔随机抖动(秒) | 5 |

### 7.2 运行时调整

监控频率可在 GUI 运行时实时调节，范围：**5-300秒**

---

## 八、调试工具

### UI 探测工具

运行 `python ui_probe.py` 将鼠标移动到目标位置，3秒后输出控件信息（Name, ClassName, AutomationId 等）。

---

## 九、文件索引

| 功能 | 文件路径 | 行号 |
|-----|---------|------|
| 微信 RPA 核心 | [src/services/wechat.py](src/services/wechat.py) | - |
| 搜索与打开资料卡 | [src/services/wechat.py](src/services/wechat.py#L153-L299) | 153-299 |
| 发送好友申请 | [src/services/wechat.py](src/services/wechat.py#L320-L364) | 320-364 |
| 被动扫描好友 | [src/services/wechat.py](src/services/wechat.py#L1494-L1611) | 1494-1611 |
| 飞书客户端 | [src/services/feishu.py](src/services/feishu.py) | - |
| 任务引擎 | [src/core/engine.py](src/core/engine.py) | - |
| 申请队列处理 | [src/core/engine.py](src/core/engine.py#L323-L358) | 323-358 |
| 欢迎队列处理 | [src/core/engine.py](src/core/engine.py#L360-L408) | 360-408 |
| 被动监控处理 | [src/core/engine.py](src/core/engine.py#L410-L451) | 410-451 |
