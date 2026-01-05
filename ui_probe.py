import time

import uiautomation as auto


def _rect_to_str(rect) -> str:
    try:
        return f"{rect.left},{rect.top},{rect.right},{rect.bottom}"
    except Exception:
        return ""


def _control_info(ctrl) -> tuple:
    if not ctrl:
        return ()
    return (
        ctrl.ControlTypeName,
        ctrl.Name,
        ctrl.AutomationId,
        ctrl.ClassName,
        _rect_to_str(getattr(ctrl, "BoundingRectangle", None)),
    )


def _control_chain(ctrl, depth: int = 4) -> list[tuple]:
    chain = []
    current = ctrl
    for _ in range(depth):
        if not current:
            break
        chain.append(_control_info(current))
        try:
            current = current.GetParentControl()
        except Exception:
            break
    return chain


def main() -> None:
    print("Move mouse to the popup. Ctrl+C to stop.")
    last = None
    while True:
        x, y = auto.GetCursorPos()
        ctrl = auto.ControlFromPoint(x, y)
        chain = _control_chain(ctrl)
        if chain and chain != last:
            print("----")
            for idx, info in enumerate(chain):
                print(f"{idx}: {info}")
            last = chain
        time.sleep(0.3)


if __name__ == "__main__":
    main()
