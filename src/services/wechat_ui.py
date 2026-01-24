"""
微信RPA通用UI操作模块
封装常用的UI自动化操作：控件查找、点击、发送消息等
"""

from __future__ import annotations

import time
import struct
import ctypes
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence, List, Any, cast

import uiautomation as auto
from loguru import logger

from ..config.logger import push_feishu_screenshot
from ..config.settings import BASE_DIR, get_config

# 依赖检查
try:
    import pyperclip
except ImportError:
    logger.error("缺少 pyperclip 依赖，请运行: pip install pyperclip")
    pyperclip = None

try:
    import win32clipboard
    import win32con
except ImportError:
    win32clipboard = None
    win32con = None
    logger.warning("未安装 pywin32，图片发送功能将不可用")


class WeChatUIOperations:
    """微信UI自动化操作基类，提供通用UI操作方法"""

    WINDOW_NAME = "微信"

    def __init__(self, owner: Any = None):
        """
        初始化UI操作类

        Args:
            owner: 拥有此实例的WeChatRPA对象，用于访问exec_path等属性
        """
        self._owner = owner
        if owner:
            self.exec_path = owner.exec_path
        else:
            config = get_config()
            self.exec_path = None

    # ====================== 窗口操作 ======================

    def _get_window(
        self, name: str = "", class_name: str = "", search_depth: int = 1
    ) -> auto.WindowControl:
        """
        获取微信窗口控件

        Args:
            name: 窗口名称
            class_name: 窗口类名
            search_depth: 搜索深度

        Returns:
            窗口控件，未找到返回None
        """
        kwargs: dict[str, Any] = {"searchDepth": search_depth}
        if name:
            kwargs["Name"] = name
        if class_name:
            kwargs["ClassName"] = class_name
        return auto.WindowControl(**kwargs)

    def _activate_window(self) -> bool:
        """强制激活微信窗口到前台"""
        win = self._get_window(self.WINDOW_NAME, search_depth=5)
        if not win.Exists(0, 0):
            if self.exec_path:
                import subprocess

                subprocess.Popen(self.exec_path)
                # 等待窗口出现，最多等待 15 秒
                for _ in range(15):
                    time.sleep(1)
                    win = self._get_window(self.WINDOW_NAME, search_depth=5)
                    if win.Exists(0, 0):
                        break
                else:
                    logger.error("启动微信后等待超时，未找到窗口")
                    self._report_wechat_not_found("启动微信后等待超时，未找到窗口")
                    return False
            else:
                logger.error("未找到微信窗口且未配置启动路径")
                self._report_wechat_not_found("未找到微信窗口且未配置启动路径")
                return False

        # 激活窗口，带错误处理
        try:
            win.SetActive()
        except Exception as e:
            logger.warning("SetActive 失败: {}", e)

        try:
            win.SetFocus()
        except Exception as e:
            logger.warning("SetFocus 失败: {}", e)

        return True

    def _report_wechat_not_found(self, reason: str) -> None:
        try:
            from PIL import ImageGrab
        except Exception:
            logger.error("截图失败，缺少 Pillow")
            return

        logs_dir = BASE_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = logs_dir / f"wechat_missing_{timestamp}.png"
        try:
            image = ImageGrab.grab()
            image.save(image_path, "PNG")
        except Exception as exc:
            logger.error("截图失败: {}", exc)
            return

        push_feishu_screenshot(reason, image_path)

    def _wait_for_window(
        self,
        name: str = "",
        class_name: str = "",
        timeout: float = 5.0,
        search_depth: int = 3,
    ) -> Optional[Any]:
        """
        等待指定窗口出现

        Args:
            name: 窗口名称（可选）
            class_name: 窗口类名（可选）
            timeout: 超时时间
            search_depth: 搜索深度

        Returns:
            找到的窗口控件，未找到返回None
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            win = self._get_window(name, class_name, search_depth)
            if win.Exists(0.3):
                logger.debug("等待到窗口 [{}]", name or class_name)
                return win
            time.sleep(0.2)
        logger.debug("等待窗口超时 [{}]", name or class_name)
        return None

    # ====================== 按钮点击 ======================

    def _click_button(
        self,
        name: str,
        timeout: float = 3.0,
        search_depth: int = 15,
        class_name: str = "",
    ) -> bool:
        """
        通用按钮点击方法

        Args:
            name: 按钮名称
            timeout: 超时时间（秒）
            search_depth: 搜索深度
            class_name: 类名（可选）

        Returns:
            是否点击成功
        """
        try:
            kwargs: dict[str, Any] = {"Name": name, "searchDepth": search_depth}
            if class_name:
                kwargs["ClassName"] = class_name
            btn = auto.ButtonControl(**kwargs)
            if btn.Exists(timeout):
                btn.Click()
                logger.debug("点击按钮 [{}] 成功", name)
                return True
            logger.debug("未找到按钮 [{}]", name)
            return False
        except Exception as e:
            logger.debug("点击按钮 [{}] 失败: {}", name, e)
            return False

    def _click_button_by_name_contains(
        self, name_contains: str, timeout: float = 3.0, search_depth: int = 15
    ) -> bool:
        """
        点击名称包含指定字符串的按钮

        Args:
            name_contains: 按钮名称包含的字符串
            timeout: 超时时间
            search_depth: 搜索深度

        Returns:
            是否点击成功
        """
        main_win = self._get_window(self.WINDOW_NAME)
        if not main_win:
            return False

        try:
            main_win_any = cast(Any, main_win)
            for ctrl in main_win_any.GetDescendants():
                try:
                    if getattr(ctrl, "ControlTypeName", "") == "ButtonControl":
                        ctrl_name = getattr(ctrl, "Name", "") or ""
                        if name_contains in ctrl_name:
                            ctrl.Click()
                            logger.debug("点击按钮 [包含: {}] 成功", name_contains)
                            return True
                except Exception:
                    continue
            logger.debug("未找到名称包含 [{}] 的按钮", name_contains)
            return False
        except Exception as e:
            logger.debug("点击按钮 [包含: {}] 失败: {}", name_contains, e)
            return False

    # ====================== 列表项操作 ======================

    def _find_list_item(self, name: str, search_depth: int = 15) -> Optional[Any]:
        """
        查找列表项

        Args:
            name: 列表项名称
            search_depth: 搜索深度

        Returns:
            找到的列表项，未找到返回None
        """
        try:
            return auto.ListItemControl(Name=name, searchDepth=search_depth)
        except Exception:
            return None

    def _find_and_click_list_item(
        self, name: str, timeout: float = 2.0, search_depth: int = 15
    ) -> bool:
        """
        查找并点击列表项

        Args:
            name: 列表项名称
            timeout: 超时时间
            search_depth: 搜索深度

        Returns:
            是否点击成功
        """
        item = self._find_list_item(name, search_depth)
        if item and item.Exists(timeout):
            item.Click()
            logger.debug("点击列表项 [{}] 成功", name)
            return True
        logger.debug("未找到列表项 [{}]", name)
        return False

    # ====================== 对话框处理 ======================

    def _handle_dialog(self, button_names: Sequence[str], timeout: float = 5.0) -> bool:
        """
        处理对话框，点击指定的按钮之一

        Args:
            button_names: 要尝试点击的按钮名称列表
            timeout: 超时时间

        Returns:
            是否点击成功
        """
        for btn_name in button_names:
            if self._click_button(btn_name, timeout=timeout):
                logger.debug("对话框处理：点击 [{}] 成功", btn_name)
                return True
        logger.debug("对话框处理：未找到指定按钮")
        return False

    def _handle_confirm_dialog(
        self,
        window_names: Sequence[str],
        button_names: Sequence[str],
        timeout: float = 8.0,
    ) -> bool:
        """
        处理确认对话框，查找指定窗口并点击按钮

        Args:
            window_names: 要查找的窗口名称列表
            button_names: 要点击的按钮名称列表
            timeout: 超时时间

        Returns:
            是否处理成功
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            for win_name in window_names:
                win = self._wait_for_window(name=win_name, timeout=1.0)
                if win:
                    # 尝试点击指定按钮
                    for btn_name in button_names:
                        btn = win.ButtonControl(Name=btn_name, searchDepth=8)
                        if btn.Exists(0):
                            btn.Click()
                            logger.debug(
                                "确认对话框：窗口[{}] 点击按钮[{}] 成功",
                                win_name,
                                btn_name,
                            )
                            # 等待窗口关闭
                            end_close = time.time() + 2
                            while win.Exists(0) and time.time() < end_close:
                                time.sleep(0.1)
                            return True
                    # 备用：点击第一个按钮
                    fallback_btn = win.ButtonControl(foundIndex=1, searchDepth=8)
                    if fallback_btn.Exists(0):
                        fallback_btn.Click()
                        logger.debug("确认对话框：使用备用按钮")
                        return True
            time.sleep(0.3)
        logger.debug("确认对话框：未找到或超时")
        return False

    # ====================== 控件查找 ======================

    def _find_control(
        self, control_type: type, name: str = "", **kwargs
    ) -> Optional[Any]:
        """
        通用控件查找方法

        Args:
            control_type: 控件类型（如 auto.ButtonControl）
            name: 控件名称（可选）
            **kwargs: 其他搜索参数

        Returns:
            找到的控件，未找到返回None
        """
        try:
            if name:
                kwargs["Name"] = name
            return control_type(**kwargs)
        except Exception:
            return None

    def _find_control_by_automation_id(
        self,
        automation_id: str,
        control_type: type = auto.Control,
        search_depth: int = 20,
    ) -> Optional[Any]:
        """
        通过 AutomationId 查找控件

        Args:
            automation_id: 控件的 AutomationId
            control_type: 控件类型
            search_depth: 搜索深度

        Returns:
            找到的控件
        """
        try:
            return control_type(AutomationId=automation_id, searchDepth=search_depth)
        except Exception:
            return None

    def _find_controls_by_class_name(
        self, class_name: str, control_type: type = auto.Control, search_depth: int = 15
    ) -> List[Any]:
        """
        通过 ClassName 查找所有匹配的控件

        Args:
            class_name: 控件的 ClassName（支持包含匹配）
            control_type: 控件类型
            search_depth: 搜索深度

        Returns:
            匹配的控件列表
        """
        results: List[Any] = []
        main_win = self._get_window(self.WINDOW_NAME)
        if not main_win:
            return results

        try:
            main_win_any = cast(Any, main_win)
            for ctrl in main_win_any.GetDescendants():
                try:
                    ctrl_class = getattr(ctrl, "ClassName", "") or ""
                    if class_name in ctrl_class:
                        if (
                            control_type is auto.Control
                            or getattr(ctrl, "ControlTypeName", "")
                            == control_type.__name__
                        ):
                            results.append(ctrl)
                except Exception:
                    continue
        except Exception as e:
            logger.debug("按ClassName查找控件失败: {}", e)
        return results

    def _find_control_by_name(
        self, parent: Any, name: str, control_type: str
    ) -> Optional[Any]:
        """
        在父控件下查找指定名称和类型的控件

        Args:
            parent: 父控件
            name: 控件名称
            control_type: 控件类型名称

        Returns:
            找到的控件
        """
        try:
            all_controls: List[Any] = []
            self._collect_all_controls(parent, all_controls, max_depth=8)

            matching_controls = []
            for control in all_controls:
                if (
                    control.ControlTypeName == control_type
                    and control.Name
                    and name in control.Name
                ):
                    matching_controls.append(control)

            if matching_controls:
                best_control = matching_controls[0]
                rect = best_control.BoundingRectangle
                logger.debug(
                    "找到'{}'控件: {} 位置({},{}) 大小{}x{}",
                    name,
                    best_control.ControlTypeName,
                    rect.left,
                    rect.top,
                    rect.width(),
                    rect.height(),
                )
                return best_control

            logger.debug("未找到名称为'{}'的{}控件", name, control_type)
            return None
        except Exception as e:
            logger.debug("查找控件失败: {}", e)
            return None

    def _collect_all_controls(
        self,
        parent: Any,
        controls_list: list[Any],
        max_depth: int = 10,
        current_depth: int = 0,
    ) -> None:
        """递归收集所有控件"""
        if current_depth >= max_depth:
            return

        try:
            if hasattr(parent, "GetChildren"):
                children = parent.GetChildren()
                for child in children:
                    controls_list.append(child)
                    self._collect_all_controls(
                        child, controls_list, max_depth, current_depth + 1
                    )
        except Exception:
            pass

    # ====================== 剪贴板操作 ======================

    def _copy_image_to_clipboard(self, image_path: str) -> bool:
        """
        将图片文件以 CF_HDROP 格式写入剪贴板

        Args:
            image_path: 图片路径

        Returns:
            是否复制成功
        """
        if not win32clipboard or not win32con:
            return False

        path_obj = Path(image_path).resolve()
        if not path_obj.exists():
            logger.error("图片不存在: {}", image_path)
            return False

        try:
            files = [str(path_obj)]
            files_str = "\0".join(files) + "\0\0"
            files_bytes = files_str.encode("utf-16le")
            header = struct.pack("IiiII", 20, 0, 0, 0, 1)
            data = header + files_bytes
            h_global = ctypes.windll.kernel32.GlobalAlloc(0x0002, len(data))
            if not h_global:
                return False
            ptr = ctypes.windll.kernel32.GlobalLock(h_global)
            ctypes.memmove(ptr, data, len(data))
            ctypes.windll.kernel32.GlobalUnlock(h_global)
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, h_global)
            win32clipboard.CloseClipboard()
            return True
        except Exception as e:
            logger.error("写入剪贴板底层错误: {}", e)
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return False

    # ====================== 消息发送 ======================

    def _send_keys_with_clipboard(self, text: str) -> None:
        """
        使用剪贴板发送文本（解决特殊字符问题）

        Args:
            text: 要发送的文本
        """
        if pyperclip:
            pyperclip.copy(text)
            time.sleep(0.1)
            auto.SendKeys("{Ctrl}v")
        else:
            auto.SendKeys(text)

    def _send_text(self, text: str) -> None:
        """
        发送文本消息（使用剪贴板解决特殊字符问题）

        Args:
            text: 要发送的文本
        """
        if pyperclip:
            pyperclip.copy(text)
            time.sleep(0.1)
            auto.SendKeys("{Ctrl}v")
        else:
            auto.SendKeys(text)
        self._random_delay()
        auto.SendKeys("{Enter}")

    def _send_image(self, image_path: str) -> bool:
        """
        发送图片消息

        Args:
            image_path: 图片路径

        Returns:
            是否发送成功
        """
        if self._copy_image_to_clipboard(image_path):
            auto.SendKeys("{Ctrl}v")
            self._random_delay()
            auto.SendKeys("{Enter}")
            return True
        return False

    # ====================== 辅助工具 ======================

    def _clean_keyword(self, keyword: Any) -> str:
        """数据清洗，将关键字转为字符串"""
        if isinstance(keyword, (list, tuple)):
            return str(keyword[0]) if len(keyword) > 0 else ""
        return str(keyword)

    def _random_delay(
        self, min_sec: float | None = None, max_sec: float | None = None
    ) -> None:
        """随机延迟，防止操作过快被风控"""
        resolved_min = min_sec
        resolved_max = max_sec
        if self._owner:
            resolved_min = (
                self._owner.rpa_delay_min if resolved_min is None else resolved_min
            )
            resolved_max = (
                self._owner.rpa_delay_max if resolved_max is None else resolved_max
            )
        if resolved_min is None:
            resolved_min = 0.5
        if resolved_max is None:
            resolved_max = 1.5
        delay = random.uniform(resolved_min, resolved_max)
        time.sleep(delay)
