# Flet UI 兼容性经验总结（0.80.2）

## 背景
这次 UI 报错的核心原因不是图标本身，而是**运行时 Flet 版本与 UI 代码使用的 API 版本不一致**。代码更偏向新版 Flet API，但当前环境是 0.80.2，导致多处参数/属性不存在而连环炸。

## 典型报错与对应修复
1. 图标属性不存在
   - 现象：`AttributeError: module 'flet.controls.material.icons' has no attribute 'CIRCLE'`
   - 原因：0.80.2 里图标用 `ft.Icons.*` 枚举，不是 `ft.icons.*`
   - 处理：`ft.icons.CIRCLE` → `ft.Icons.CIRCLE`

2. NavigationRailDestination 参数不匹配
   - 现象：`unexpected keyword argument 'selected_icon_content' / 'label_content'`
   - 原因：0.80.2 只支持 `selected_icon` 和 `label`
   - 处理：`selected_icon_content` → `selected_icon`，`label_content` → `label`（可传 `ft.Text`）

3. CrossAxisAlignment 枚举大小写
   - 现象：`AttributeError: start`
   - 原因：0.80.2 使用大写枚举
   - 处理：`ft.CrossAxisAlignment.start` → `ft.CrossAxisAlignment.START`

4. Column 不支持 padding
   - 现象：`Column.__init__() got an unexpected keyword argument 'padding'`
   - 原因：0.80.2 的 `ft.Column` 没有 `padding` 参数
   - 处理：用外层 `ft.Container(padding=...)` 包一层

5. Expanded 缺失
   - 现象：`AttributeError: module 'flet' has no attribute 'Expanded'`
   - 原因：0.80.2 没有 `ft.Expanded`
   - 处理：`ft.Container(expand=True)` 代替

6. alignment 常量缺失
   - 现象：`AttributeError: module 'flet.controls.alignment' has no attribute 'top_left'`
   - 原因：0.80.2 没有 `ft.alignment.*` 常量
   - 处理：`ft.Alignment(-1, -1)` 代表 top_left，`ft.Alignment(0, 0)` 代表 center

7. set_task_delay 不存在
   - 现象：`AttributeError: 'Page' object has no attribute 'set_task_delay'`
   - 原因：0.80.2 仅提供 `page.run_task`
   - 处理：用 `run_task` + `asyncio.sleep` 实现延迟调度

## 快速排查流程（低成本）
1. 确认版本：运行时打印 `flet.__version__`
2. 查签名：`inspect.signature(ft.XXX)` 看当前版本支持哪些参数
3. 对照报错栈：从第一处抛错往下改，优先修 API 参数/属性

## 版本策略建议
- **短期**：锁定 `flet==0.80.2`，UI 代码只用 0.80.2 支持的 API
- **长期**：升级 Flet 后统一对齐 API（避免“混用新老写法”）

## 可复用命令
```python
import inspect
import flet as ft

print(ft.__version__)
print(inspect.signature(ft.NavigationRailDestination))
print(hasattr(ft, "Expanded"))
```

> 结论：这次不是“图标坏了”，而是**API 版本错位**。以后 UI 报错先看版本和签名，能省掉 80% 的无效替换。
