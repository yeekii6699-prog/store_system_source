"""
src/wechat_bot.py
基于 uiautomation 的微信 RPA 核心库 (V2 修正版)
核心修复：
1. 按键语法：将所有 '^v' 替换为 '{Ctrl}v'，修复粘贴失败的问题。
2. 内存管理：保留了 ctypes 手动管理剪贴板内存的逻辑，防止报错。
3. 数据清洗：保留了 keyword 强转 string 的逻辑。
"""

from __future__ import annotations

import time
import struct
import ctypes
import re
import random
from pathlib import Path
from typing import Optional, Sequence, Literal, List, Dict, TypedDict

import uiautomation as auto
from loguru import logger

from ..config.settings import get_config


class ContactProfile(TypedDict, total=False):
    """微信资料卡信息，用于被动同步到飞书。"""

    wechat_id: str
    nickname: Optional[str]
    remark: Optional[str]


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


class WeChatRPA:
    WINDOW_NAME = "微信"
    PROFILE_TITLES = ("详细资料", "基本资料", "资料", "个人信息", "添加朋友")

    def __init__(self, exec_path: Optional[str] = None):
        self.exec_path = exec_path
        # 加载扫描间隔配置
        config = get_config()
        self.scan_interval = int(config.get("NEW_FRIEND_SCAN_INTERVAL", "30"))

    def _activate_window(self) -> bool:
        """强制激活微信窗口到前台"""
        win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
        if not win.Exists(0, 0):
            if self.exec_path:
                import subprocess
                subprocess.Popen(self.exec_path)
                time.sleep(3)
                win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
            else:
                logger.error("未找到微信窗口且未配置启动路径")
                return False
        
        win.SetActive()
        win.SetFocus()
        return True

    def _copy_image_to_clipboard(self, image_path: str) -> bool:
        """
        [底层重写] 将图片文件以 CF_HDROP 格式写入剪贴板
        使用 ctypes 手动管理内存，解决 'bytes-like object required' 报错
        """
        if not win32clipboard or not win32con:
            return False
            
        path_obj = Path(image_path).resolve()
        if not path_obj.exists():
            logger.error(f"图片不存在: {image_path}")
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
            logger.error(f"写入剪贴板底层错误: {e}")
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return False

    def _clean_keyword(self, keyword) -> str:
        """数据清洗"""
        if isinstance(keyword, (list, tuple)):
            return str(keyword[0]) if len(keyword) > 0 else ""
        return str(keyword)

    def _detect_relationship_state(
        self,
        containers: Sequence[auto.Control],
        timeout: float = 6.0,
    ) -> Literal["friend", "stranger", "unknown", "not_found"]:
        friend_labels = ("发消息", "发送消息", "Message")
        add_labels = ("添加到通讯录", "加好友", "Add to contacts")
        deadline = time.time() + timeout
        while time.time() < deadline:
            for ctrl in containers:
                if ctrl is None or not ctrl.Exists(0):
                    continue
                for name in friend_labels:
                    if ctrl.ButtonControl(Name=name, searchDepth=15).Exists(0):
                        return "friend"
                for name in add_labels:
                    if ctrl.ButtonControl(Name=name, searchDepth=15).Exists(0):
                        return "stranger"
            time.sleep(0.3)
        has_friend = False
        has_add = False
        for ctrl in containers:
            if ctrl is None or not ctrl.Exists(0):
                continue
            if any(ctrl.ButtonControl(Name=name, searchDepth=15).Exists(0) for name in friend_labels):
                has_friend = True
            if any(ctrl.ButtonControl(Name=name, searchDepth=15).Exists(0) for name in add_labels):
                has_add = True
        if not has_friend and not has_add:
            return "not_found"
        return "unknown"

    def _search_and_open_profile(self, keyword) -> Optional[auto.WindowControl]:
        """搜索关键词并打开资料卡"""
        keyword = self._clean_keyword(keyword)
        if not keyword:
            return None

        if not self._activate_window():
            return None
            
        main = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)

        def _log_focus_warning(action: str, exc: Exception) -> None:  # noqa: BLE001
            handle = getattr(main, "NativeWindowHandle", None)
            rect = getattr(main, "BoundingRectangle", None)
            rect_str = None
            if rect:
                rect_str = f"{rect.left},{rect.top},{rect.right},{rect.bottom}"
            logger.warning(
                "[WeChatFocus] action={} keyword={} handle={} rect={} err={}",
                action,
                keyword,
                handle,
                rect_str,
                exc,
            )

        try:
            main.SwitchToThisWindow()
        except Exception as exc:  # noqa: BLE001
            _log_focus_warning("SwitchToThisWindow", exc)
        finally:
            try:
                main.SetFocus()
            except Exception as focus_exc:  # noqa: BLE001
                _log_focus_warning("SetFocus", focus_exc)

        auto.SendKeys('{Ctrl}f')
        logger.info("⌨️ [Shortcut] 已发送 Ctrl+F 激活搜索框")

        def _send_keys(text: str) -> None:
            auto.SendKeys(text)
            
        if pyperclip:
            time.sleep(0.1)
            _send_keys("{Ctrl}a{Delete}")
            pyperclip.copy(keyword)
            time.sleep(0.1)
            _send_keys("{Ctrl}v")
        else:
            _send_keys("{Ctrl}a{Delete}")
            _send_keys(keyword)

        time.sleep(1.5)

        def _has_not_found_message() -> bool:
            hints = ("无法找到该用户", "请检查你填写的账号是否正确")
            for hint in hints:
                if main.TextControl(SubName=hint, searchDepth=15).Exists(0):
                    return True
            tip_win = auto.WindowControl(Name="提示", searchDepth=1)
            if tip_win.Exists(0) and tip_win.TextControl(SubName="无法找到该用户", searchDepth=6).Exists(0):
                return True
            return False
        
        if _has_not_found_message():
            return None

        # 先点击"网络查找"选项（搜索框下方的第一个ListItemControl）
        clicked = False  # 初始化点击状态
        network_find = main.ListItemControl(SubName="网络查找", searchDepth=15)
        if network_find.Exists(0.5):
            logger.debug("点击网络查找选项")
            network_find.Click()
            clicked = True
        else:
            # 兜底：尝试 SubName 包含"网络查找"的项
            network_find_v2 = main.ListItemControl(RegexName="网络查找.*", searchDepth=15)
            if network_find_v2.Exists(0.5):
                logger.debug("点击网络查找选项(v2)")
                network_find_v2.Click()
                clicked = True

        if not clicked:
            # 如果找不到网络查找选项，再尝试在search_list中查找
            search_list = main.ListControl(AutomationId='search_list')
            if search_list.Exists(0.5):
                target = search_list.ListItemControl(AutomationId=f'search_item_{keyword}')
                if target.Exists(0):
                    logger.debug("点击精确匹配的搜索结果: {}", keyword)
                    target.Click()
                    clicked = True
                else:
                    # 遍历搜索结果
                    all_items = search_list.GetChildren()
                    for item in all_items:
                        try:
                            item_name = item.Name or ""
                            item_aid = getattr(item, "AutomationId", "") or ""
                            if item_name in ("最常使用", "最近聊天", "群聊"):
                                continue
                            if item_aid and not item_aid.startswith("search_item_"):
                                continue
                            logger.debug("点击搜索结果项: name={}, aid={}", item_name, item_aid)
                            item.Click()
                            clicked = True
                            break
                        except Exception as item_err:
                            logger.debug("处理搜索项失败: {}", item_err)
                            continue

        if not clicked:
            _send_keys("{Enter}")
            
        profile_win = None
        end_time = time.time() + 4
        while time.time() < end_time:
            for title in self.PROFILE_TITLES:
                win = auto.WindowControl(Name=title, searchDepth=1)
                if win.Exists(0):
                    profile_win = win
                    break
            if profile_win:
                break
            time.sleep(0.3)

        if profile_win:
            try:
                profile_win.SetFocus()
            except Exception:
                pass
            return profile_win

        fallback_deadline = time.time() + 2
        while time.time() < fallback_deadline:
            if _has_not_found_message():
                return None
            msg_exists = main.ButtonControl(Name="发消息", searchDepth=15).Exists(0)
            add_exists = main.ButtonControl(Name="添加到通讯录", searchDepth=15).Exists(0)
            if msg_exists or add_exists:
                try:
                    main.SetFocus()
                except Exception:
                    pass
                return main
            time.sleep(0.2)

        return None

    def check_relationship(self, keyword) -> Literal["friend", "stranger", "unknown", "not_found"]:
        """检查关系状态"""
        keyword = self._clean_keyword(keyword)
        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return "unknown"
        
        result = "unknown"
        try:
            main_win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
            containers = [profile_win, main_win]
            result = self._detect_relationship_state(containers, timeout=6.0)
            if result != "unknown":
                logger.info("[关系检测] {} -> {}", keyword, result)
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")
        return result

    def apply_friend(self, keyword) -> bool:
        """执行申请操作"""
        keyword = self._clean_keyword(keyword)
        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return False
        
        success = False
        try:
            add_btn = profile_win.ButtonControl(Name="添加到通讯录", searchDepth=10)
            if add_btn.Exists(2):
                add_btn.Click()
                time.sleep(1)
                confirm_windows = ("申请添加朋友", "发送好友申请", "好友验证", "通过朋友验证")
                confirm_buttons = ("确定", "发送", "Send", "确定(&O)", "确定(&S)")
                wait_until = time.time() + 8
                while time.time() < wait_until and not success:
                    for win_name in confirm_windows:
                        win = auto.WindowControl(Name=win_name)
                        if not win.Exists(0.2):
                            continue
                        for btn_name in confirm_buttons:
                            btn = win.ButtonControl(Name=btn_name, searchDepth=8)
                            if btn.Exists(0):
                                btn.Click()
                                success = True
                                break
                        if not success:
                            fallback_btn = win.ButtonControl(foundIndex=1, searchDepth=8)
                            if fallback_btn.Exists(0):
                                fallback_btn.Click()
                                success = True
                        if success:
                            end_close = time.time() + 2
                            while win.Exists(0) and time.time() < end_close:
                                time.sleep(0.1)
                            break
                    if not success:
                        time.sleep(0.3)
                if not success and not add_btn.Exists(0):
                    success = True
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")
        return success

    def send_welcome_package(self, keyword, steps: Sequence[dict]) -> bool:
        """发送欢迎包"""
        keyword = self._clean_keyword(keyword)
        if not pyperclip:
            return False

        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return False
            
        try:
            msg_btn = None
            for _ in range(3):
                msg_btn = profile_win.ButtonControl(Name="发消息", searchDepth=10)
                if msg_btn.Exists(0):
                    break
                time.sleep(0.5)
            
            if msg_btn and msg_btn.Exists(0):
                msg_btn.Click()
                time.sleep(0.8)
            else:
                return False
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")

        self._activate_window()
        
        logger.info(f"开始向 [{keyword}] 发送欢迎包...")
        for i, step in enumerate(steps):
            try:
                msg_type = step.get("type")
                content = step.get("content") or step.get("path") or step.get("url")
                if not content:
                    continue
                content = str(content)
                if msg_type == "text":
                    pyperclip.copy(content)
                    auto.SendKeys('{Ctrl}v')
                    time.sleep(0.3)
                    auto.SendKeys('{Enter}')
                elif msg_type == "link":
                    title = step.get("title", "")
                    text = f"{title}\n{content}" if title else content
                    pyperclip.copy(text)
                    auto.SendKeys('{Ctrl}v')
                    time.sleep(0.3)
                    auto.SendKeys('{Enter}')
                elif msg_type == "image":
                    if self._copy_image_to_clipboard(content):
                        auto.SendKeys('{Ctrl}v')
                        time.sleep(0.8)
                        auto.SendKeys('{Enter}')
                    else:
                        logger.error(f"图片复制失败: {content}")
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"发送步骤 {i+1} 失败: {e}")
        return True

    def _get_all_chat_messages(self, main_win: auto.WindowControl) -> List[str]:
        """获取当前聊天窗口中所有可见的消息文本（整页内容）。"""
        messages: List[str] = []

        # 等待聊天内容加载
        time.sleep(0.3)

        try:
            chat_list = self._find_chat_message_list(main_win)
            if chat_list:
                return self._collect_all_text_from_control(chat_list, max_depth=20)

            chat_content = self._find_chat_content_area(main_win)
            if chat_content:
                return self._collect_all_text_from_control(chat_content, max_depth=20)

            logger.debug("未找到聊天消息列表控件")
            return messages

        except Exception as e:
            logger.debug("获取聊天消息失败: {}", e)
            return messages

    def _find_chat_message_list(self, main_win: auto.WindowControl) -> Optional[auto.Control]:
        """查找聊天消息列表控件（chat_message_list）。"""
        try:
            direct = main_win.ListControl(AutomationId="chat_message_list", searchDepth=15)
            if direct.Exists(0.3):
                return direct
        except Exception:
            pass

        try:
            direct = main_win.ListControl(Name="消息", searchDepth=15)
            if direct.Exists(0.3):
                return direct
        except Exception:
            pass

        all_controls: list[auto.Control] = []
        self._collect_all_controls(main_win, all_controls, max_depth=15)
        candidates: list[auto.Control] = []
        for ctrl in all_controls:
            try:
                if getattr(ctrl, "ControlTypeName", "") != "ListControl":
                    continue
                aid = str(getattr(ctrl, "AutomationId", "") or "")
                name = str(getattr(ctrl, "Name", "") or "")
                cls = str(getattr(ctrl, "ClassName", "") or "")
                if aid == "session_list" or name == "会话":
                    continue
                if aid == "chat_message_list" or "RecyclerListView" in cls or name == "消息":
                    candidates.append(ctrl)
            except Exception:
                continue

        def _has_chat_parent(target: auto.Control) -> bool:
            parent = target
            for _ in range(8):
                try:
                    parent = parent.GetParentControl()
                except Exception:
                    return False
                if not parent:
                    return False
                cls = str(getattr(parent, "ClassName", "") or "")
                if (
                    "ChatDetailView" in cls
                    or "ChatMessagePage" in cls
                    or "MessageView" in cls
                    or "ChatMasterView" in cls
                ):
                    return True
            return False

        for ctrl in candidates:
            if _has_chat_parent(ctrl):
                return ctrl

        if candidates:
            return candidates[0]
        return None

    def _collect_all_text_from_control(self, control: auto.Control, max_depth: int = 20, current_depth: int = 0) -> List[str]:
        """递归收集控件中的所有文本内容。"""
        texts: List[str] = []

        if current_depth >= max_depth:
            return texts

        try:
            # 获取当前控件的文本
            name = getattr(control, "Name", "") or ""
            if name and isinstance(name, str) and name.strip():
                texts.append(name.strip())

            # 递归获取子控件的文本
            if hasattr(control, 'GetChildren'):
                children = control.GetChildren()
                for child in children:
                    child_texts = self._collect_all_text_from_control(child, max_depth, current_depth + 1)
                    texts.extend(child_texts)
        except Exception:
            pass

        return texts

    def _chat_has_keywords(self, main_win: auto.WindowControl, keywords: Sequence[str]) -> bool:
        """检测当前会话的聊天内容（整页）是否包含特定关键词。"""
        logger.debug("🔍 检查聊天页面内容，关键词: {}", keywords)

        # 获取当前页面所有消息
        all_messages = self._get_all_chat_messages(main_win)

        if not all_messages:
            logger.debug("未获取到任何聊天消息")
            return False

        # 合并所有消息文本用于搜索
        combined_text = "\n".join(all_messages)
        logger.debug("获取到 {} 条消息文本，总长度: {}", len(all_messages), len(combined_text))

        # 搜索关键词（精确匹配）
        for kw in keywords:
            if not kw:
                continue
            if kw in combined_text:
                logger.info("✅ 在整页消息中找到关键词 [{}]", kw)
                logger.debug("匹配上下文: ...{}...", combined_text[max(0, combined_text.find(kw)-20):combined_text.find(kw)+len(kw)+20])
                return True

        # 模糊匹配系统消息 - 必须匹配完整的系统消息模式，避免群聊误匹配
        system_patterns = [
            # 必须以这些开头才是系统消息
            "已添加你为朋友",
            "你已添加了",
            "你现在可以给 ta 发送消息",
            "你们现在是好友了",
            "刚刚把你添加到通讯录",
            "现在可以开始聊天了",
            "以上是打招呼的消息",
            "以上是打招呼的内容",
        ]
        for pattern in system_patterns:
            if pattern in combined_text:
                logger.info("✅ 在整页消息中模糊匹配到系统消息 [{}]", pattern)
                return True

        logger.debug("❌ 整页消息中未匹配到任何关键词")
        return False

    def _find_chat_content_area(self, main_win: auto.WindowControl) -> Optional[auto.Control]:
        """查找聊天内容区域（通常在右侧）"""
        try:
            # 方法1: 查找主要的编辑控件（聊天输入框），然后在其上方找内容区域
            edit_control = main_win.EditControl()
            if edit_control.Exists(1):
                logger.debug("找到聊天输入框，在其上方查找内容区域")
                # 获取输入框的位置，然后在其上方搜索
                edit_rect = edit_control.BoundingRectangle

                # 在输入框上方区域查找Document或Pane控件
                for depth in range(5, 15):
                    content_controls = main_win.GetChildren()
                    for control in content_controls:
                        try:
                            rect = control.BoundingRectangle
                            # 检查是否在输入框上方
                            if (rect.bottom < edit_rect.top and
                                rect.width() > 200 and rect.height() > 100):
                                if control.ControlTypeName in ["Document", "Pane", "GroupControl"]:
                                    logger.debug("找到可能的聊天内容区域: {} 位置: ({},{}) 大小: {}x{}",
                                               control.ControlTypeName, rect.left, rect.top, rect.width(), rect.height())
                                    return control
                        except Exception:
                            continue

            # 方法2: 查找右侧大的Pane或Document控件
            window_rect = main_win.BoundingRectangle
            right_x = window_rect.left + window_rect.width() * 2 // 3  # 右侧1/3区域

            # 递归获取所有控件
            all_controls = []
            self._collect_all_controls(main_win, all_controls, max_depth=10)
            for control in all_controls:
                try:
                    if control.ControlTypeName in ["Document", "Pane", "GroupControl"]:
                        rect = control.BoundingRectangle
                        # 检查是否在右侧区域且足够大
                        if (rect.left > right_x and
                            rect.width() > 200 and rect.height() > 200):
                            logger.debug("找到右侧内容区域: {} 位置: ({},{}) 大小: {}x{}",
                                       control.ControlTypeName, rect.left, rect.top, rect.width(), rect.height())
                            return control
                except Exception:
                    continue

        except Exception as e:
            logger.debug("查找聊天内容区域失败: {}", e)

        return None

    def _find_control_by_name(self, parent: auto.Control, name: str, control_type: str) -> Optional[auto.Control]:
        """在父控件下查找指定名称和类型的控件"""
        try:
            # 收集所有控件
            all_controls = []
            self._collect_all_controls(parent, all_controls, max_depth=8)

            # 查找匹配的控件
            matching_controls = []
            for control in all_controls:
                if (control.ControlTypeName == control_type and
                    control.Name and name in control.Name):
                    matching_controls.append(control)

            if not matching_controls:
                logger.info(f"未找到名称为'{name}'的{control_type}控件")
                return None

            # 如果有多个匹配，返回第一个
            best_control = matching_controls[0]
            rect = best_control.BoundingRectangle
            logger.info(f"找到'{name}'控件: {best_control.ControlTypeName} 位置({rect.left}, {rect.top}) 大小{rect.width()}x{rect.height()}")
            return best_control

        except Exception as e:
            logger.info(f"查找控件失败: {e}")
            return None

    def _find_all_list_controls(self, group_control) -> Optional[auto.Control]:
        """在GroupControl下查找所有ListControl，返回左侧的第一个"""
        try:
            all_controls = []
            self._collect_all_controls(group_control, all_controls, max_depth=12)

            # 查找所有ListControl
            list_controls = [c for c in all_controls if c.ControlTypeName == "ListControl"]
            if not list_controls:
                return None

            # 返回位置最靠左的ListControl（应该是会话列表）
            list_controls.sort(key=lambda c: c.BoundingRectangle.left)
            best_list = list_controls[0]

            rect = best_list.BoundingRectangle
            logger.debug("找到左侧ListControl: 位置 ({},{}) 大小 {}x{}",
                       rect.left, rect.top, rect.width(), rect.height())
            return best_list

        except Exception as e:
            logger.debug("查找ListControl失败: {}", e)
            return None

    def _collect_all_controls(self, parent: auto.Control, controls_list: list, max_depth: int = 10, current_depth: int = 0) -> None:
        """递归收集所有控件"""
        if current_depth >= max_depth:
            return

        try:
            if hasattr(parent, 'GetChildren'):
                children = parent.GetChildren()
                for child in children:
                    controls_list.append(child)
                    self._collect_all_controls(child, controls_list, max_depth, current_depth + 1)
        except Exception:
            pass

    def _open_profile_from_chat(
        self,
        main_win: auto.WindowControl,
    ) -> Optional[tuple[auto.Control, Optional[tuple[int, int, int, int]]]]:
        """
        打开资料卡：
        基于聊天消息列表控件，定位消息条目中的头像控件并点击
        """
        chat_list = self._find_chat_message_list(main_win)
        if not chat_list:
            logger.debug("未找到聊天消息列表")
            return None

        try:
            list_rect = chat_list.BoundingRectangle
            items = chat_list.GetChildren()
            if not items:
                logger.debug("聊天消息列表为空")
                return None

            def _find_avatar_in_item(item_ctrl: auto.Control) -> Optional[auto.Control]:
                candidates: list[auto.Control] = []
                all_controls: list[auto.Control] = []
                self._collect_all_controls(item_ctrl, all_controls, max_depth=6)
                for ctrl in all_controls:
                    try:
                        ctrl_type = str(getattr(ctrl, "ControlTypeName", "") or "")
                        if ctrl_type not in (
                            "ImageControl",
                            "ButtonControl",
                            "PaneControl",
                            "CustomControl",
                            "GroupControl",
                        ):
                            continue
                        aid = str(getattr(ctrl, "AutomationId", "") or "")
                        cls = str(getattr(ctrl, "ClassName", "") or "")
                        name = str(getattr(ctrl, "Name", "") or "")
                        key = f"{aid} {cls} {name}".lower()
                        if not any(k in key for k in ("avatar", "head", "portrait", "profile", "头像")):
                            continue
                        rect = ctrl.BoundingRectangle
                        if rect.width() > list_rect.width() * 0.6 or rect.height() > list_rect.height() * 0.6:
                            continue
                        candidates.append(ctrl)
                    except Exception:
                        continue

                if not candidates:
                    return None

                left_boundary = list_rect.left + int(list_rect.width() * 0.45)
                left_scored: list[tuple[int, auto.Control]] = []
                scored: list[tuple[int, auto.Control]] = []
                for ctrl in candidates:
                    try:
                        rect = ctrl.BoundingRectangle
                        scored.append((rect.left, ctrl))
                        if rect.left <= left_boundary:
                            left_scored.append((rect.left, ctrl))
                    except Exception:
                        continue
                if left_scored:
                    left_scored.sort(key=lambda x: x[0])
                    return left_scored[0][1]
                scored.sort(key=lambda x: x[0])
                return scored[0][1]

            def _click_control_center(ctrl: auto.Control) -> bool:
                try:
                    rect = ctrl.BoundingRectangle
                    auto.Click(rect.left + rect.width() // 2, rect.top + rect.height() // 2)
                    return True
                except Exception:
                    return False

            for item in reversed(items):
                avatar_ctrl = _find_avatar_in_item(item)
                if not avatar_ctrl:
                    continue
                if not _click_control_center(avatar_ctrl):
                    continue
                logger.debug("已点击消息头像控件")
                time.sleep(0.5)
                profile_win = self._wait_profile_window(main_win, timeout=1.6)
                if profile_win:
                    return (profile_win, None)

            logger.debug("未能打开资料卡")
            return None

        except Exception as e:
            logger.debug("定位头像失败: {}", e)
            return None

    def _wait_profile_window(self, main_win: auto.WindowControl, timeout: float) -> Optional[auto.WindowControl]:
        """等待资料卡窗口（弹窗或侧栏）"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            # 方法1：检查弹窗式资料卡
            popup = auto.WindowControl(ClassName="mmui::ProfileUniquePop", searchDepth=3)
            if popup.Exists(0.3):
                logger.debug("检测到弹窗式资料卡")
                try:
                    popup.SetFocus()
                except Exception:
                    pass
                return popup

            # 方法2：检查标题为"详细资料"等窗口
            for title in self.PROFILE_TITLES:
                win = auto.WindowControl(Name=title, searchDepth=1)
                if win.Exists(0.3):
                    logger.debug("检测到资料窗口: {}", title)
                    try:
                        win.SetFocus()
                    except Exception:
                        pass
                    return win

            time.sleep(0.2)

        return None

    def _click_avatar_if_possible(self, profile_win: auto.WindowControl) -> None:
        """尝试点击资料卡中的头像，进入更详细的资料页。"""
        try:
            # 直接找带 avatar 关键词的图片/控件
            avatar = profile_win.ImageControl(RegexName="avatar|头像", searchDepth=12)
            if avatar.Exists(0.3):
                try:
                    avatar.Click()
                    logger.debug("点击头像控件成功")
                    time.sleep(0.5)
                    return
                except Exception as exc:
                    logger.debug("点击头像控件失败: {}", exc)

            # 查找 ContactProfileView 容器（你提供的控件）
            candidates = []
            try:
                for ctrl in profile_win.GetDescendants():
                    try:
                        cls = str(getattr(ctrl, "ClassName", "") or "")
                        if "ContactProfileView" in cls or "profile" in cls.lower():
                            candidates.append(ctrl)
                    except Exception:
                        continue
            except Exception:
                candidates = []

            for ctrl in candidates:
                try:
                    rect = ctrl.BoundingRectangle
                    # 限制在资料卡上半部分的小区域
                    if rect.width() > 40 and rect.width() < 400 and rect.height() < 400:
                        ctrl.Click()
                        logger.debug("通过 ContactProfileView 容器点击头像区域")
                        time.sleep(0.5)
                        return
                except Exception as exc:
                    logger.debug("点击 ContactProfileView 失败: {}", exc)
        except Exception:
            pass

    def _fallback_profile_from_header(
        self,
        main_win: auto.WindowControl,
        item_name: str | None,
    ) -> Optional[ContactProfile]:
        """
        兜底：从聊天窗口标题或列表项名称提取一个可用的标识，避免资料卡打不开时完全丢失。
        """
        title = ""
        try:
            header = main_win.TextControl(foundIndex=1, searchDepth=12)
            if header.Exists(0.3):
                title = (header.Name or "").strip()
        except Exception:
            pass

        candidate = (title or item_name or "").strip()
        if not candidate:
            return None

        # 以空格或冒号截断，取第一段作为 id
        tokens = candidate.replace("：", ":").split()
        first = tokens[0] if tokens else candidate
        first = first.split(":", 1)[0]
        if not first:
            return None

        return {"wechat_id": first, "nickname": candidate, "remark": None}

    def _extract_profile_info(
        self,
        profile_win: auto.Control,
        sidebar_rect: Optional[tuple[int, int, int, int]] = None,
    ) -> Optional[ContactProfile]:
        """从资料卡提取微信号/昵称/备注。使用更灵活的提取逻辑。"""
        wechat_id: Optional[str] = None
        nickname: Optional[str] = None
        remark: Optional[str] = None
        profile_class = str(getattr(profile_win, "ClassName", "") or "")

        def _extract_wechat_from_popup() -> Optional[str]:
            """从 ProfileUniquePop 弹窗中提取微信号。"""
            label_id = "right_v_view.user_info_center_view.basic_line_view.basic_line.key_text"
            value_id = "right_v_view.user_info_center_view.basic_line_view.ContactProfileTextView"

            descendants: list[auto.Control] = []
            try:
                descendants = profile_win.GetDescendants()
            except Exception:
                descendants = []

            deadline = time.time() + 2.0
            while time.time() < deadline:
                try:
                    value_ctrl = profile_win.TextControl(AutomationId=value_id, searchDepth=40)
                    if value_ctrl.Exists(0.2):
                        value = (value_ctrl.Name or "").strip()
                        if value and "微信号" not in value:
                            return value
                except Exception as exc:
                    logger.debug("弹窗读取微信号控件失败: {}", exc)
                try:
                    label_ctrl = profile_win.TextControl(AutomationId=label_id, searchDepth=40)
                    if label_ctrl.Exists(0.2):
                        label_name = (label_ctrl.Name or "").strip()
                        if "微信号" in label_name:
                            value = _match_value_from_parent(label_ctrl)
                            if value:
                                return value
                except Exception:
                    pass
                time.sleep(0.2)

            for ctrl in descendants:
                try:
                    aid = str(getattr(ctrl, "AutomationId", "") or "")
                    name = str(getattr(ctrl, "Name", "") or "").strip()
                    if value_id in aid and name and "微信号" not in name:
                        return name
                    if "ContactProfileTextView" in aid and name and "微信号" not in name:
                        return name
                except Exception:
                    continue

            def _match_value_from_parent(label_ctrl: auto.Control) -> Optional[str]:
                parent = None
                try:
                    parent = label_ctrl.GetParentControl()
                except Exception:
                    parent = None
                for _ in range(3):
                    if not parent:
                        break
                    try:
                        for child in parent.GetChildren():
                            try:
                                aid = str(getattr(child, "AutomationId", "") or "")
                                cls = str(getattr(child, "ClassName", "") or "")
                                name = str(getattr(child, "Name", "") or "").strip()
                                if not name or "微信号" in name:
                                    continue
                                if "ContactProfileTextView" in aid or "ContactProfileTextView" in cls:
                                    return name
                            except Exception:
                                continue
                    except Exception:
                        pass
                    try:
                        parent = parent.GetParentControl()
                    except Exception:
                        parent = None
                return None

            def _match_value_by_rect(label_ctrl: auto.Control) -> Optional[str]:
                try:
                    label_rect = label_ctrl.BoundingRectangle
                except Exception:
                    return None
                best = None
                for ctrl in descendants:
                    try:
                        if ctrl.ControlTypeName != "TextControl":
                            continue
                        name = str(getattr(ctrl, "Name", "") or "").strip()
                        if not name or "微信号" in name:
                            continue
                        rect = ctrl.BoundingRectangle
                        if rect.top > label_rect.bottom or rect.bottom < label_rect.top:
                            continue
                        if rect.left <= label_rect.right:
                            continue
                        if best is None or rect.left < best[0]:
                            best = (rect.left, name)
                    except Exception:
                        continue
                return best[1] if best else None

            for ctrl in descendants:
                try:
                    aid = str(getattr(ctrl, "AutomationId", "") or "")
                    name = str(getattr(ctrl, "Name", "") or "").strip()
                    if label_id in aid and "微信号" in name:
                        value = _match_value_from_parent(ctrl) or _match_value_by_rect(ctrl)
                        if value:
                            return value
                except Exception:
                    continue
            return None

        if not wechat_id and profile_class == "mmui::ProfileUniquePop":
            wechat_id = _extract_wechat_from_popup()
            if wechat_id:
                logger.debug("通过弹窗控件提取微信号: {}", wechat_id)

        def _rect_intersects(ctrl: auto.Control) -> bool:
            if sidebar_rect is None:
                return True
            try:
                rect = ctrl.BoundingRectangle
            except Exception:
                return False
            left, top, right, bottom = sidebar_rect
            if rect.right <= left or rect.left >= right:
                return False
            if rect.bottom <= top or rect.top >= bottom:
                return False
            return True

        def _looks_like_wechat_id(value: str) -> bool:
            value = value.strip()
            if not value or len(value) < 6 or len(value) > 20:
                return False
            if value.lower().startswith("wxid_"):
                return True
            if not value[0].isalpha():
                return False
            return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", value))

        def _iter_text_controls() -> list[auto.Control]:
            try:
                controls = profile_win.GetDescendants()
            except Exception:
                return []
            if sidebar_rect is None:
                return controls
            filtered: list[auto.Control] = []
            for ctrl in controls:
                if _rect_intersects(ctrl):
                    filtered.append(ctrl)
            return filtered

        # 提取昵称 - 使用多种方法寻找昵称控件
        try:
            if sidebar_rect is None:
                # 方法1：尝试查找主要的昵称控件
                name_ctrl = profile_win.TextControl(foundIndex=1, searchDepth=6)
                if name_ctrl.Exists(0):
                    nickname = (name_ctrl.Name or "").strip()
                    if nickname and len(nickname) > 1:
                        logger.debug("通过方法1提取到昵称: {}", nickname)
        except Exception:
            pass

        # 如果方法1失败，尝试方法2
        if not nickname or len(nickname) <= 1:
            try:
                # 方法2：查找包含中文特征的名字控件
                text_controls = _iter_text_controls()
                for ctrl in text_controls[:20]:
                    try:
                        text = getattr(ctrl, "Name", "")
                        if not text:
                            continue
                        text_str = str(text)
                        if "微信号" in text_str or "备注" in text_str:
                            continue
                        if any('\u4e00' <= char <= '\u9fff' for char in text_str) and "微信" not in text_str:
                            nickname = text_str.strip()
                            if len(nickname) > 1:
                                logger.debug("通过方法2提取到昵称: {}", nickname)
                                break
                    except Exception:
                        continue
            except Exception:
                pass

        # 提取微信号和备注 - 使用更智能的匹配
        field_mappings = {
            "微信号": "wechat_id",
            "WeChat": "wechat_id",
            "备注": "remark",
            "remark": "remark",
            "昵称": "nickname"
        }

        try:
            # 获取所有文本控件进行遍历
            all_text_controls = _iter_text_controls()
            label_hints = tuple(field_mappings.keys())

            def _find_value_next_to_label(label_rect, start_index: int) -> Optional[str]:
                lookahead_limit = min(start_index + 6, len(all_text_controls))
                for next_idx in range(start_index + 1, lookahead_limit):
                    next_ctrl = all_text_controls[next_idx]
                    try:
                        next_text = str(getattr(next_ctrl, "Name", "") or "").strip()
                        if not next_text or next_text in label_hints:
                            continue
                        next_rect = next_ctrl.BoundingRectangle
                        if label_rect and next_rect:
                            if next_rect.left <= label_rect.right - 5:
                                continue
                            if next_rect.top > label_rect.bottom or next_rect.bottom < label_rect.top:
                                continue
                        return next_text
                    except Exception:
                        continue
                return None

            for idx, ctrl in enumerate(all_text_controls):
                try:
                    raw_text = getattr(ctrl, "Name", "") or ""
                    automation_id = str(getattr(ctrl, "AutomationId", "") or "")
                    class_name = str(getattr(ctrl, "ClassName", "") or "")
                    text = str(raw_text).replace("：", ":").strip()
                    if not text:
                        continue

                    # 直接通过 ContactProfileTextView 提取微信号
                    if (not wechat_id and
                        "ContactProfileTextView" in automation_id + class_name and
                        "微信" not in text and len(text) >= 4):
                        wechat_id = text
                        logger.debug("通过资料卡文本控件提取微信号: {}", text)
                        continue

                    # 尝试匹配字段
                    for field_keyword, target_field in field_mappings.items():
                        if text.lower().startswith(field_keyword.lower()):
                            value = ""
                            parts = text.split(":", 1)
                            if len(parts) == 2 and parts[1].strip():
                                value = parts[1].strip()
                            # 如果当前控件是标签，没有值，尝试读取右侧文本作为值
                            if not value:
                                try:
                                    label_rect = ctrl.BoundingRectangle
                                except Exception:
                                    label_rect = None
                                value = _find_value_next_to_label(label_rect, idx)

                            if value:
                                if target_field == "wechat_id" and not wechat_id:
                                    wechat_id = value
                                    logger.debug("通过标签提取微信号: {}", value)
                                elif target_field == "remark" and not remark:
                                    remark = value
                                    logger.debug("提取到备注: {}", value)
                                elif target_field == "nickname" and (not nickname or len(nickname) <= 1):
                                    nickname = value
                                    logger.debug("提取到昵称: {}", value)
                            break

                    if not wechat_id and _looks_like_wechat_id(text):
                        wechat_id = text
                        logger.debug("通过规则匹配提取微信号: {}", text)
                except Exception:
                    continue
        except Exception:
            pass

        if not wechat_id:
            try:
                edit = profile_win.EditControl(foundIndex=1, searchDepth=10)
                if edit.Exists(0):
                    pattern = getattr(edit, "GetValuePattern", None)
                    if pattern:
                        wechat_id = str(pattern().Value).strip()
            except Exception:
                pass

        if wechat_id:
            return {"wechat_id": wechat_id, "nickname": nickname, "remark": remark}
        logger.debug("未从资料卡提取到微信号，可能需调整控件定位")
        return None

    # ==================== 新的通讯录扫描逻辑 ====================

    def _random_delay(self, min_sec: float = 0.5, max_sec: float = 1.5) -> None:
        """随机延迟，防止操作过快被风控"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    def _click_contacts_tab(self) -> bool:
        """点击侧边栏'通讯录' Tab"""
        try:
            contacts_tab = auto.ButtonControl(
                Name="通讯录",
                ClassName="mmui::XTabBarItem",
                searchDepth=8
            )
            if contacts_tab.Exists(2):
                contacts_tab.Click()
                logger.debug("点击'通讯录' Tab成功")
                self._random_delay()
                return True
            logger.warning("未找到'通讯录' Tab控件")
            return False
        except Exception as e:
            logger.error("点击通讯录Tab失败: {}", e)
            return False

    def _click_new_friends_entry(self) -> bool:
        """点击'新的朋友'入口，支持展开/收起状态"""
        try:
            # 先尝试直接获取待验证列表，检查是否已经展开
            pending_items = self._get_pending_verification_items(check_only=True)
            if pending_items is not None and len(pending_items) > 0:
                logger.debug("'新的朋友'列表已展开，直接使用")
                return True

            # 未展开，需要点击展开
            # 定位"新的朋友"入口
            new_friends = auto.ListItemControl(
                Name="新的朋友",
                ClassName="mmui::ContactsCellGroupView",
                searchDepth=15
            )

            if not new_friends.Exists(1):
                # 遍历所有列表项查找
                main_win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
                if main_win.Exists(1):
                    for ctrl in main_win.GetDescendants():
                        try:
                            if getattr(ctrl, "ControlTypeName", "") == "ListControl":
                                for child in ctrl.GetChildren():
                                    name = getattr(child, "Name", "") or ""
                                    cls = getattr(child, "ClassName", "") or ""
                                    if name == "新的朋友" and cls == "mmui::ContactsCellGroupView":
                                        new_friends = child
                                        break
                        except Exception:
                            continue
                    if not new_friends.Exists(1):
                        logger.warning("未找到'新的朋友'入口")
                        return False

            # 点击展开
            new_friends.Click()
            logger.debug("点击'新的朋友'入口展开列表")
            self._random_delay(0.5, 1.0)
            return True

        except Exception as e:
            logger.error("点击新的朋友入口失败: {}", e)
            return False

    def _get_pending_verification_items(self, check_only: bool = False) -> List[auto.ListItemControl]:
        """
        获取所有'等待验证'列表项

        Args:
            check_only: 如果为True，仅检查是否有待验证项而不返回（用于判断展开状态）
        """
        items: List[auto.ListItemControl] = []
        try:
            # 查找通讯录列表容器
            list_container = auto.ListControl(
                AutomationId="primary_table_.contact_list",
                searchDepth=12
            )

            if not list_container.Exists(1):
                # 尝试备用定位方式
                list_container = auto.ListControl(
                    ClassName="mmui::StickyHeaderRecyclerListView",
                    searchDepth=12
                )

            if not list_container.Exists(1):
                if not check_only:
                    logger.debug("未找到通讯录列表控件")
                return items

            # 遍历所有子项
            children = list_container.GetChildren()

            for child in children:
                try:
                    item_name = getattr(child, "Name", "") or ""
                    # 检查名称是否包含"等待验证"
                    if "等待验证" in item_name:
                        items.append(child)
                except Exception:
                    continue

            if not check_only:
                if items:
                    logger.info("共找到 {} 个待验证项", len(items))
                else:
                    logger.debug("没有待验证的好友")
            else:
                # check_only模式下不打印日志
                pass

        except Exception as e:
            if not check_only:
                logger.error("获取待验证列表失败: {}", e)
        return items

    def _open_verification_detail(self, item: auto.Control) -> bool:
        """点击待验证项，进入详情页"""
        try:
            if item.Exists(1):
                item.Click()
                logger.debug("点击待验证项成功")
                self._random_delay()
                return True
            return False
        except Exception as e:
            logger.error("点击待验证项失败: {}", e)
            return False

    def _click_verify_button(self) -> bool:
        """点击'前往验证'按钮"""
        try:
            # 等待页面加载
            time.sleep(1.0)

            # 扩大搜索范围
            verify_btn = auto.ButtonControl(
                Name="前往验证",
                ClassName="mmui::XOutlineButton",
                searchDepth=20
            )

            # 使用更长的时间检测
            if verify_btn.Exists(5):
                verify_btn.Click()
                logger.debug("点击'前往验证'按钮成功")
                self._random_delay(0.5, 1.0)
                return True

            # 备用：遍历所有ButtonControl查找
            main_win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
            if main_win.Exists(1):
                for ctrl in main_win.GetDescendants():
                    try:
                        if getattr(ctrl, "ControlTypeName", "") == "ButtonControl":
                            name = getattr(ctrl, "Name", "") or ""
                            if name == "前往验证":
                                ctrl.Click()
                                logger.debug("通过遍历找到'前往验证'按钮并点击")
                                self._random_delay(0.5, 1.0)
                                return True
                    except Exception:
                        continue

            logger.warning("未找到'前往验证'按钮")
            return False
        except Exception as e:
            logger.error("点击前往验证按钮失败: {}", e)
            return False

    def _confirm_verification(self) -> bool:
        """点击'确定'按钮确认验证"""
        try:
            # 等待弹窗加载
            time.sleep(0.8)

            # 查找验证窗口中的确定按钮（使用更大的搜索范围）
            confirm_btn = auto.ButtonControl(
                Name="确定",
                ClassName="mmui::XOutlineButton",
                searchDepth=15
            )
            if confirm_btn.Exists(3):
                confirm_btn.Click()
                logger.debug("点击'确定'按钮成功")
                self._random_delay(0.5, 1.0)
                return True

            # 备用：遍历查找
            all_buttons = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
            for ctrl in all_buttons.GetDescendants():
                try:
                    if getattr(ctrl, "ControlTypeName", "") == "ButtonControl":
                        name = getattr(ctrl, "Name", "") or ""
                        if name == "确定":
                            ctrl.Click()
                            logger.debug("通过遍历找到'确定'按钮并点击")
                            self._random_delay(0.5, 1.0)
                            return True
                except Exception:
                    continue

            logger.warning("未找到'确定'按钮")
            return False
        except Exception as e:
            logger.error("点击确定按钮失败: {}", e)
            return False

    def _extract_wechat_id_from_profile(self) -> Optional[str]:
        """从资料卡片中提取微信号（右侧区域）"""
        try:
            # 等待页面完全加载
            time.sleep(1.0)

            main_win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
            if not main_win.Exists(1):
                logger.debug("未找到微信主窗口")
                return None

            # 使用递归方式收集所有子控件
            def collect_controls(control, depth=0, max_depth=50):
                """递归收集所有控件"""
                if depth > max_depth:
                    return []
                result = [control]
                try:
                    for child in control.GetChildren():
                        result.extend(collect_controls(child, depth + 1, max_depth))
                except Exception:
                    pass
                return result

            all_controls = collect_controls(main_win)

            # 找到所有 ContactProfileTextView 控件
            profile_text_views = []
            for ctrl in all_controls:
                try:
                    ctrl_class = getattr(ctrl, "ClassName", "") or ""
                    if "ContactProfileTextView" in ctrl_class:
                        ctrl_automation_id = getattr(ctrl, "AutomationId", "") or ""
                        ctrl_name = getattr(ctrl, "Name", "") or ""
                        profile_text_views.append({
                            "name": ctrl_name,
                            "automation_id": ctrl_automation_id,
                        })
                except Exception:
                    continue

            # 打印所有找到的 ContactProfileTextView 控件信息
            logger.debug("找到 {} 个 ContactProfileTextView 控件:", len(profile_text_views))
            for i, item in enumerate(profile_text_views):
                logger.debug("  [{}] Name='{}', AutomationId='{}'",
                            i, item["name"], item["automation_id"])

            # 方法: 在 basic_line_view 下找到所有 ContactProfileTextView
            # 微信号、昵称、地区都在这里，需要筛选
            for item in profile_text_views:
                ctrl_name = item["name"]
                ctrl_automation_id = item["automation_id"]

                # 只处理 basic_line_view 下的控件
                if "basic_line_view" in ctrl_automation_id and ctrl_automation_id.endswith("ContactProfileTextView"):
                    # 检查是否符合微信号格式（4-20位字母数字下划线）
                    import re
                    if re.match(r"^[A-Za-z0-9_.-]{4,20}$", ctrl_name):
                        logger.debug("提取到微信号: {} (AutomationId={})", ctrl_name, ctrl_automation_id)
                        return ctrl_name

            logger.debug("未找到有效的微信号")
            return None
        except Exception as e:
            logger.error("提取微信号失败: {}", e)
            return None

    def _return_to_chat_list(self) -> bool:
        """返回聊天列表界面"""
        try:
            # 点击微信Tab返回聊天列表
            wechat_tab = auto.ButtonControl(
                Name="微信",
                ClassName="mmui::XTabBarItem",
                searchDepth=8
            )
            if wechat_tab.Exists(2):
                wechat_tab.Click()
                logger.debug("返回聊天列表成功")
                self._random_delay()
                return True
            logger.warning("未找到'微信' Tab")
            return False
        except Exception as e:
            logger.error("返回聊天列表失败: {}", e)
            return False

    def scan_new_friends_via_contacts(self) -> List[ContactProfile]:
        """
        通过通讯录-新的好友扫描待验证的好友，提取微信号并返回。

        流程：
        1. 点击通讯录Tab
        2. 点击新的朋友入口
        3. 遍历等待验证列表
        4. 点击具体项 -> 点击前往验证 -> 点击确定 -> 获取微信号
        5. 写入飞书（状态=未发送）
        6. 返回聊天列表

        Returns:
            List[ContactProfile]: 发现的新好友列表
        """
        results: List[ContactProfile] = []

        if not self._activate_window():
            return results

        # 步骤1: 点击通讯录
        if not self._click_contacts_tab():
            return results

        # 步骤2: 点击新的朋友
        if not self._click_new_friends_entry():
            return results

        # 步骤3: 获取待验证列表
        pending_items = self._get_pending_verification_items(check_only=False)
        if not pending_items:
            logger.debug("没有待验证的好友")
            self._return_to_chat_list()
            return results

        logger.info("开始处理 {} 个待验证好友", len(pending_items))

        # 遍历每个待验证项
        for idx, item in enumerate(pending_items, 1):
            try:
                item_name = getattr(item, "Name", "") or f"待验证项{idx}"
                logger.info("[{}/{}] 处理: {}", idx, len(pending_items), item_name)

                # 步骤4: 点击进入详情
                if not self._open_verification_detail(item):
                    logger.warning("无法进入详情页，跳过: {}", item_name)
                    continue

                # 步骤5: 点击前往验证
                if not self._click_verify_button():
                    logger.warning("点击前往验证失败，跳过: {}", item_name)
                    continue

                # 步骤6: 点击确定确认验证
                if not self._confirm_verification():
                    logger.warning("点击确定失败，跳过: {}", item_name)
                    continue

                # 步骤7: 等待资料卡片加载并提取微信号
                time.sleep(0.8)  # 等待页面加载
                wechat_id = self._extract_wechat_id_from_profile()

                if wechat_id:
                    # 从名称中提取昵称（去掉"等待验证"后缀）
                    nickname = item_name.replace("等待验证", "").strip()
                    if not nickname:
                        nickname = None

                    profile: ContactProfile = {
                        "wechat_id": wechat_id,
                        "nickname": nickname,
                        "remark": None
                    }
                    results.append(profile)
                    logger.info("[{}/{}] 成功提取: 微信号={}, 昵称={}", idx, len(pending_items), wechat_id, nickname)
                else:
                    logger.warning("[{}/{}] 未能提取到微信号: {}", idx, len(pending_items), item_name)

                # 步骤9: 返回聊天列表，继续下一个
                self._return_to_chat_list()

                # 重新进入通讯录页面
                if idx < len(pending_items):
                    self._click_contacts_tab()
                    self._click_new_friends_entry()

            except Exception as e:
                logger.error("[{}/{}] 处理异常: {} - {}", idx, len(pending_items), item_name, e)
                # 尝试返回聊天列表恢复状态
                try:
                    self._return_to_chat_list()
                except Exception:
                    pass
                continue

        # 确保返回聊天列表
        try:
            self._return_to_chat_list()
        except Exception:
            pass

        logger.info("扫描完成，发现 {} 个新好友", len(results))
        return results

    # ==================== 旧的会话列表扫描逻辑（已废弃） ====================

    def scan_passive_new_friends(self, keywords: Sequence[str] | None = None, max_chats: int | None = None) -> List[ContactProfile]:
        """
        从会话列表被动扫描"已添加"系统提示，提取资料并返回列表。
        不访问"新的朋友"页，降低风控风险。

        Args:
            keywords: 关键词列表，为None时使用配置中的默认关键词
            max_chats: 最大扫描聊天数，为None时使用配置中的默认值
        """
        results: List[ContactProfile] = []
        if not self._activate_window():
            return results

        # 使用配置参数
        if keywords is None:
            keywords = self.monitor_keywords
        if max_chats is None:
            max_chats = self.max_chats

        main = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
        if not main.Exists(2):
            logger.error("未找到微信主窗口，跳过被动扫描")
            return results

        logger.debug("微信主窗口已找到，开始查找会话列表...")

        # 使用简化的控件路径查找会话列表
        chat_list = self._find_chat_list(main)
        if not chat_list:
            return results

        # 调试：确认找到的是正确的控件
        try:
            rect = chat_list.BoundingRectangle
            control_type = chat_list.ControlTypeName
            logger.debug("找到会话列表控件: {} 位置: ({},{}) 大小: {}x{}",
                       control_type, rect.left, rect.top, rect.width(), rect.height())
        except Exception as e:
            logger.debug("无法获取控件信息: {}", e)

        try:
            # 尝试获取会话列表子项
            logger.debug("尝试获取会话列表子项...")
            items = chat_list.GetChildren() if hasattr(chat_list, "GetChildren") else []

            if not items:
                logger.warning("⚠️ 会话列表为空或不可枚举")
                logger.warning("   可能原因：")
                logger.warning("   1. 微信会话列表确实为空")
                logger.warning("   2. UI自动化权限不足")
                logger.warning("   3. 微信版本兼容性问题")

                # 尝试诊断会话列表状态
                try:
                    rect = chat_list.BoundingRectangle
                    logger.debug("会话列表控件位置: ({}, {}) 大小: {}x{}",
                               rect.left, rect.top, rect.width(), rect.height())
                except Exception as rect_error:
                    logger.debug("无法获取会话列表控件边界: {}", rect_error)

                return results
            else:
                logger.info("✅ 成功获取会话列表，包含 {} 个会话项", len(items))

        except Exception as e:
            logger.error("❌ 获取会话列表子项失败: {}", e)
            logger.error("   详细错误信息: {}", str(e))
            logger.error("   建议运行微信UI分析工具进行诊断")
            return results

        # 缓存子项列表避免重复获取（从顶部数前6个，从下到上扫描）
        cached_items = list(reversed(items[:max_chats]))
        logger.debug("开始被动扫描 {} 个会话（从下到上），关键词: {}", len(cached_items), keywords)

        for idx, item in enumerate(cached_items, start=1):
            try:
                # 调试：显示即将点击的控件信息
                try:
                    rect = item.BoundingRectangle
                    item_type = item.ControlTypeName
                    item_name = item.Name or "(无名称)"
                    logger.debug("即将点击第{}个控件: {} - {} 位置: ({},{})",
                               idx, item_type, item_name, rect.left, rect.top)
                except Exception as debug_e:
                    logger.debug("无法获取第{}个控件信息: {}", idx, debug_e)

                # 如果列表项名称本身包含关键词，直接认为命中（兼容系统提示出现在列表项标题的情况）
                pre_match = False
                if item_name and keywords:
                    for kw in keywords:
                        if kw and kw in item_name:
                            pre_match = True
                            logger.info("✅ 会话 {} 列表项名称命中关键词 [{}]: {}", idx, kw, item_name)
                            break

                item.Click()
                logger.debug("已点击第{}个控件", idx)
            except Exception as exc:  # noqa: BLE001
                logger.debug("切换会话失败 idx={} err={}", idx, exc)
                continue

            time.sleep(0.8)
            has_keywords = self._chat_has_keywords(main, keywords)
            if not has_keywords:
                if pre_match:
                    logger.debug("List item preview matched, but ignored to avoid sidebar noise.")
                logger.debug("会话 {} 未包含关键词，跳过", idx)
                continue
            else:
                logger.info("✅ 会话 {} 匹配到关键词，准备提取资料", idx)

            profile_result = self._open_profile_from_chat(main)
            if not profile_result:
                logger.debug("未能打开资料卡，尝试兜底使用聊天标题/列表名称 idx={}", idx)
                fallback_profile = self._fallback_profile_from_header(main, item_name)
                if fallback_profile:
                    identifier = f"{fallback_profile.get('wechat_id','')}:{fallback_profile.get('nickname','')}"
                    if identifier not in self._processed_messages:
                        self._processed_messages.add(identifier)
                        results.append(fallback_profile)  # type: ignore[arg-type]
                        logger.info("⚠️ 资料卡未打开，使用兜底标识记录好友: {}", fallback_profile)
                continue

            profile_win, sidebar_rect = profile_result
            try:
                # 尝试点击头像以进入更详细资料页
                try:
                    profile_class = str(getattr(profile_win, "ClassName", "") or "")
                    if sidebar_rect is None and profile_class != "mmui::ProfileUniquePop":
                        self._click_avatar_if_possible(profile_win)
                    else:
                        logger.debug("资料卡已在弹窗/侧栏展开，跳过头像二次点击")
                except Exception as avatar_exc:
                    logger.debug("点击头像进入详细资料失败: {}", avatar_exc)

                profile = self._extract_profile_info(profile_win, sidebar_rect=sidebar_rect)
                if profile:
                    # 创建去重标识符（微信号 + 昵称的组合）
                    wechat_id = profile.get("wechat_id", "")
                    nickname = profile.get("nickname", "")
                    identifier = f"{wechat_id}:{nickname}"

                    # 检查是否已经处理过
                    if identifier not in self._processed_messages:
                        self._processed_messages.add(identifier)
                        results.append(profile)
                        logger.info("发现新的已添加好友: {}", profile)
                    else:
                        logger.debug("跳过重复处理的好友: {}", profile)
            finally:
                try:
                    profile_class = str(getattr(profile_win, "ClassName", "") or "")
                    if sidebar_rect is None and profile_class != "mmui::ProfileUniquePop":
                        profile_win.SendKeys("{Esc}")
                except Exception:
                    pass
            time.sleep(0.5)

        return results

    def _find_chat_list(self, main_window: auto.WindowControl) -> Optional[auto.Control]:
        """
        使用简化的控件路径查找会话列表
        基于inspect工具分析得出的准确路径
        """
        # 尝试的控件路径（按优先级排序）
        # 基于inspect工具分析得出的准确路径
        search_paths = [
            # 路径1: 准确路径 - GroupControl -> ListControl("会话")
            lambda: main_window.ListControl(Name="会话", searchDepth=12),

            # 路径1b: 直接在窗口中查找名称为"会话"的控件
            lambda: self._find_control_by_name(main_window, "会话", "ListControl"),

            # 路径2: GroupControl下的任意ListControl
            lambda: main_window.GroupControl().ListControl(),

            # 路径2b: 直接在主窗口下查找ListControl
            lambda: main_window.ListControl(searchDepth=6),

            # 路径2c: 在GroupControl下查找所有ListControl
            lambda: self._find_all_list_controls(main_window.GroupControl()),

            # 路径3: 传统ListControl（兼容旧版本）
            lambda: main_window.ListControl(searchDepth=8),

            # 路径4: 更深搜索的ListControl
            lambda: main_window.ListControl(searchDepth=15),

            # 路径5: 备用路径 - PaneControl中的ListControl
            lambda: main_window.PaneControl(searchDepth=5).ListControl(searchDepth=3),
        ]

        fallback_control = None
        fallback_info: Dict[str, auto.Control | int | None] = {"rect": None, "children": None}

        def _looks_like_session_list(children: list[auto.Control]) -> bool:
            """根据子项特征判断是否为会话列表（如 AutomationId 以 session_item_ 开头）"""
            for child in children:
                try:
                    aid = getattr(child, "AutomationId", "") or ""
                    if str(aid).startswith("session_item_"):
                        return True
                except Exception:
                    continue
            return False

        def _scan_session_list_from_all() -> auto.Control | None:
            """
            兜底扫描所有 ListControl，优先选择：
            1) 子项包含 session_item_* 前缀
            2) 宽度较小（典型侧边栏 ~200-300）
            """
            all_controls: list[auto.Control] = []
            self._collect_all_controls(main_window, all_controls, max_depth=20)
            list_controls = [c for c in all_controls if getattr(c, "ControlTypeName", "") == "ListControl"]
            scored: list[tuple] = []
            for ctrl in list_controls:
                try:
                    children = ctrl.GetChildren()
                    if not children or len(children) > 200:
                        continue
                    rect = ctrl.BoundingRectangle
                    is_session = _looks_like_session_list(children)
                    score = (0 if is_session else 1, rect.width(), rect.left)
                    scored.append((score, ctrl, rect, len(children), is_session))
                except Exception:
                    continue

            if not scored:
                logger.info("兜底扫描：未找到任何 ListControl 候选")
                return None

            scored.sort(key=lambda x: x[0])
            best = scored[0]
            _, ctrl, rect, child_cnt, is_session = best

            logger.info(
                "兜底扫描候选 Top1: 名称={} 宽={} 左={} 子项={} session_like={}",
                ctrl.Name or "(无名称)",
                rect.width(),
                rect.left,
                child_cnt,
                is_session,
            )

            # 如果命中 session_item_* 或者宽度明显是侧边栏（< 360），使用它
            if is_session or rect.width() < 360:
                logger.info(
                    "⚠️ 兜底扫描选中 ListControl: 名称={} 宽={} 左={} 子项={}",
                    ctrl.Name or "(无名称)",
                    rect.width(),
                    rect.left,
                    child_cnt,
                )
                return ctrl
            return None

        for i, path_func in enumerate(search_paths, 1):
            try:
                control = path_func()
                if not control or not control.Exists(1):
                    continue
                # 验证控件是否有合理的子项（表示这是会话列表）
                try:
                    children = control.GetChildren()
                    if len(children) <= 1 or len(children) >= 100:
                        continue

                    is_session_like = _looks_like_session_list(children)
                    rect = control.BoundingRectangle
                    control_name = control.Name or "(无名称)"
                    if control_name == "消息":
                        continue

                    window_rect = main_window.BoundingRectangle
                    window_left_40pct = window_rect.left + int(window_rect.width() * 0.40)
                    is_left_side = rect.left < window_left_40pct

                    if is_session_like or is_left_side or control_name == "会话":
                        logger.info(
                            "✅ 路径{}命中会话列表: {} ({}个子项) 名称: {}",
                            i,
                            control.ControlTypeName,
                            len(children),
                            control_name,
                        )
                        return control

                    # 记录一个候选，作为兜底（左侧判断失败但结构合理）
                    if fallback_control is None:
                        fallback_control = control
                        fallback_info["rect"] = rect
                        fallback_info["children"] = len(children)
                except Exception:
                    continue
            except Exception:
                continue

        # 如果没命中严格条件，但找到过候选，就返回第一个候选，避免空结果
        if fallback_control is not None:
            try:
                rect = fallback_info["rect"]
                children = fallback_info["children"]
                logger.info("⚠️ 未找到明确“会话”命名的列表，使用候选控件: {} (子项数: {}) 位置: ({},{})",
                           fallback_control.ControlTypeName, children,
                           getattr(rect, 'left', '?'), getattr(rect, 'top', '?'))
            except Exception:
                pass
            return fallback_control

        # 最终兜底：全局扫描 ListControl，按 session_item_* 或宽度优先
        scanned = _scan_session_list_from_all()
        if scanned:
            return scanned

        # 如果所有路径都失败，提供详细的诊断信息
        logger.error("❌ 所有控件路径都未找到会话列表")
        logger.error("💡 建议运行控件路径发现工具:")
        logger.error("   python src/debug/control_path_finder.py")
        logger.error("🔍 该工具会帮助你找到准确的控件路径")
        return None
