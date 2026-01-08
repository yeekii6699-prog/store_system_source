"""
UI 探测工具：实时输出鼠标位置控件信息
用于查找微信窗口控件名称和位置
"""

import time
import uiautomation as auto


def get_control_info(control: auto.Control, depth: int = 0) -> list:
    """递归收集控件信息"""
    results = []

    try:
        # 获取控件基本信息
        ctrl_type = control.ControlTypeName or ""
        name = control.Name or ""
        aid = getattr(control, "AutomationId", "") or ""
        cls = control.ClassName or ""

        # 获取边界矩形
        rect = control.BoundingRectangle
        rect_str = f"{rect.left},{rect.top},{rect.right},{rect.bottom}"

        results.append((ctrl_type, name, aid, cls, rect_str))

        # 递归获取子控件
        if depth < 10:
            try:
                children = control.GetChildren()
                for child in children:
                    results.extend(get_control_info(child, depth + 1))
            except Exception:
                pass
    except Exception:
        pass

    return results


def probe_mouse_position():
    """探测鼠标位置的控件"""
    print("=" * 60)
    print("UI 探测工具 - 实时查找控件信息")
    print("=" * 60)
    print("将鼠标移动到目标位置，3秒后开始探测...")
    print("按 Ctrl+C 退出")
    print("=" * 60)

    time.sleep(3)

    while True:
        try:
            # 获取鼠标位置的控件 (新版API)
            x, y = auto.GetCursorPos()
            control = auto.ControlFromPoint(x, y)

            if control:
                # 获取所有祖先控件和自身
                all_controls = []
                current = control
                depth = 0

                while current and depth < 15:
                    try:
                        ctrl_type = current.ControlTypeName or ""
                        name = current.Name or ""
                        aid = getattr(current, "AutomationId", "") or ""
                        cls = current.ClassName or ""

                        rect = current.BoundingRectangle
                        rect_str = f"{rect.left},{rect.top},{rect.right},{rect.bottom}"

                        all_controls.append((ctrl_type, name, aid, cls, rect_str))

                        parent = current.GetParentControl()
                        current = parent
                        depth += 1
                    except Exception:
                        break

                # 倒序输出（从根到叶）
                all_controls.reverse()

                print("\n" + "=" * 60)
                print(f"探测到 {len(all_controls)} 个控件:")
                print("=" * 60)

                for i, (ctrl_type, name, aid, cls, rect_str) in enumerate(all_controls):
                    print(f"{i}: ('{ctrl_type}', '{name}', '{aid}', '{cls}', '{rect_str}')")

                print("=" * 60)

            time.sleep(2)

        except KeyboardInterrupt:
            print("\n退出探测")
            break
        except Exception as e:
            print(f"探测错误: {e}")
            time.sleep(1)


def probe_window(window_name: str = "微信"):
    """探测指定窗口的所有控件"""
    print("=" * 60)
    print(f"UI 探测工具 - 探测窗口 [{window_name}]")
    print("=" * 60)

    # 查找窗口
    window = auto.WindowControl(searchDepth=1, Name=window_name)

    if not window.Exists(2):
        print(f"未找到窗口: {window_name}")
        return

    print(f"找到窗口: {window.Name}")
    print(f"句柄: {window.NativeWindowHandle}")
    print(f"位置: {window.BoundingRectangle}")
    print("-" * 60)

    # 收集所有控件
    all_controls = []
    get_control_info(window, all_controls)

    print(f"共收集到 {len(all_controls)} 个控件:")
    print("-" * 60)

    for i, (ctrl_type, name, aid, cls, rect_str) in enumerate(all_controls):
        print(f"{i}: ('{ctrl_type}', '{name}', '{aid}', '{cls}', '{rect_str}')")

    print("=" * 60)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 命令行参数指定窗口名
        probe_window(sys.argv[1])
    else:
        # 默认使用鼠标探测
        probe_mouse_position()
