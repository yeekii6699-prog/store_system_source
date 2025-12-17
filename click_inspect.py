"""
简单实用的控件检查工具
点击3秒后获取鼠标位置的控件信息
"""

from __future__ import annotations

import time
from typing import Optional
import uiautomation as auto


def inspect_control_at_cursor():
    """获取鼠标位置的控件信息"""
    print("🎯 控件检查工具")
    print("=" * 40)
    print("3秒后点击目标控件...")

    # 倒计时
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1)

    print("📍 获取鼠标位置的控件...")

    try:
        # 获取当前鼠标位置
        cursor_pos = auto.GetCursorPos()
        x, y = cursor_pos
        print(f"鼠标位置: ({x}, {y})")

        # 获取鼠标位置的控件
        control = auto.ControlFromPoint(x, y)
        print("\n✅ 控件信息:")
        print("-" * 40)

        # 基本信息
        print(f"控件类型: {control.ControlTypeName}")
        print(f"控件名称: {control.Name or '(无名称)'}")
        print(f"AutomationId: {control.AutomationId or '(无ID)'}")
        print(f"ClassName: {control.ClassName or '(无类名)'}")

        # 位置信息
        rect = control.BoundingRectangle
        print(f"位置: ({rect.left}, {rect.top})")
        print(f"大小: {rect.width()} x {rect.height()}")

        # 获取控件路径
        path = get_control_path(control)
        print(f"\n🔧 推荐路径:")
        print(path)

        # 检查是否有子控件
        try:
            children = control.GetChildren()
            print(f"\n📊 子控件数量: {len(children)}")

            if children:
                print("前3个子控件:")
                for i, child in enumerate(children[:3], 1):
                    child_name = child.Name or "(无名称)"
                    child_type = child.ControlTypeName
                    print(f"  {i}. {child_type} - {child_name}")
        except:
            pass

    except Exception as e:
        print(f"❌ 获取控件失败: {e}")


def get_control_path(control, max_depth=3) -> str:
    """获取控件路径"""
    if not control:
        return "控件为空"

    path_parts = []
    current = control

    try:
        # 从当前控件开始向上查找
        for depth in range(max_depth):
            if not current:
                break

            control_type = current.ControlTypeName
            name = current.Name or ""

            # 构建路径部分
            if name:
                path_part = f'{control_type}("{name}")'
            else:
                path_part = control_type

            path_parts.insert(0, path_part)

            # 获取父控件
            try:
                current = current.GetParentControl()
                # 如果是微信窗口，停止
                if current and current.Name == "微信":
                    path_parts.insert(0, 'WindowControl("微信")')
                    break
            except:
                break

    except:
        pass

    return ".".join(path_parts) if path_parts else "无法获取路径"


if __name__ == "__main__":
    inspect_control_at_cursor()
    input("\n按回车键退出...")