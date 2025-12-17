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
from pathlib import Path
from typing import Optional, Sequence, Literal, List, Dict, TypedDict

import uiautomation as auto
from loguru import logger

from ..config.settings import get_config

# 添加文件日志，方便调试
logger.add("debug_log.txt",
           level="DEBUG",
           format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
           rotation="10 MB",
           encoding="utf-8")


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
        # 用于消息去重的集合
        self._processed_messages = set()
        # 加载配置参数
        self._load_monitoring_config()

    def _load_monitoring_config(self) -> None:
        """加载监控相关配置参数"""
        config = get_config()
        self.max_chats = int(config.get("MONITOR_MAX_CHATS", "6"))
        self.scan_interval = int(config.get("MONITOR_SCAN_INTERVAL", "30"))
        # 解析关键词列表，支持逗号分隔；始终包含系统常见提示，防止配置缺失
        default_keywords = [
            "已添加你为朋友",
            "你现在可以给 ta 发送消息",
            "打招呼消息",
            "你们现在是好友了",
            "刚刚把你添加到通讯录",
            "现在可以开始聊天了",
            "以上是打招呼的消息",
            "以上是打招呼的内容",
        ]
        keywords_str = config.get("MONITOR_KEYWORDS", "")
        user_keywords = [kw.strip() for kw in keywords_str.split(",") if kw.strip()]
        merged = list(dict.fromkeys(default_keywords + user_keywords))  # 去重保持顺序
        self.monitor_keywords = merged

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

        search_list = main.ListControl(AutomationId='search_list')
        clicked = False
        if search_list.Exists(0.5):
            target = search_list.ListItemControl(SubName="网络查找")
            if target.Exists(0):
                target.Click()
                clicked = True
            else:
                first = search_list.ListItemControl(foundIndex=1)
                if first.Exists(0):
                    first.Click()
                    clicked = True
        
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

    def _chat_has_keywords(self, main_win: auto.WindowControl, keywords: Sequence[str]) -> bool:
        """检测当前会话的聊天内容是否包含特定关键词。"""
        logger.debug("🔍 在聊天内容中检查关键词: {}", keywords)

        # 等待聊天界面加载
        time.sleep(0.5)

        # 查找聊天内容区域
        try:
            # 聊天内容通常在右侧区域
            chat_content = self._find_chat_content_area(main_win)
            if not chat_content:
                logger.debug("未找到聊天内容区域，尝试窗口全局匹配")
                # 兜底：直接在窗口内搜索 TextControl
                for kw in keywords:
                    if not kw:
                        continue
                    text_ctrl = main_win.TextControl(SubName=kw, searchDepth=18)
                    if text_ctrl.Exists(0.3):
                        logger.info("✅ 全局匹配到关键词 {}", kw)
                        return True
                return False

            logger.debug("找到聊天内容区域，开始搜索关键词...")

            # 在聊天内容区域搜索关键词
            for kw in keywords:
                if not kw:
                    continue

                logger.debug("🔍 在聊天内容中搜索关键词: {}", kw)

                # 精确匹配
                text_control = chat_content.TextControl(SubName=kw, searchDepth=10)
                if text_control.Exists(0.3):
                    try:
                        full_text = text_control.Name
                        logger.info("✅ 在聊天内容中找到关键词: {}", kw)
                        logger.debug("完整文本: {}", full_text)
                        return True
                    except Exception:
                        logger.info("✅ 在聊天内容中找到关键词: {}", kw)
                        return True

            # 模糊匹配，搜索系统消息相关内容
            system_keywords = ["已添加", "打招呼", "朋友", "添加你", "现在可以", "以上是打招呼的消息", "以上是打招呼的内容"]
            logger.debug("🔍 尝试模糊匹配系统消息关键词: {}", system_keywords)

            for kw in system_keywords:
                text_control = chat_content.TextControl(SubName=kw, searchDepth=12)
                if text_control.Exists(0.2):
                    try:
                        full_text = text_control.Name
                        logger.debug("模糊匹配到文本: {}", full_text)
                        # 检查是否包含完整的系统消息模式
                        if any(word in full_text for word in ["朋友", "添加", "打招呼", "消息"]):
                            logger.info("✅ 在聊天内容中模糊匹配到系统消息: {}", full_text)
                            return True
                    except Exception as e:
                        logger.debug("获取模糊匹配文本失败: {}", e)

        except Exception as e:
            logger.debug("聊天内容关键词搜索失败: {}", e)

        logger.debug("❌ 聊天内容中未匹配到任何关键词")
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

    def _open_profile_from_chat(self, main_win: auto.WindowControl) -> Optional[auto.WindowControl]:
        """
        打开资料卡（侧栏固定路径版）：
        1) 点击右上角“聊天信息/更多”按钮
        2) 等侧栏展开后，按固定坐标点击侧栏的首个头像
        """
        win_rect = main_win.BoundingRectangle

        # 1) 点击右上角聊天信息/更多
        clicked_info = False
        btn = main_win.ButtonControl(Name="聊天信息", searchDepth=15)
        if btn.Exists(0.6):
            try:
                btn.Click()
                clicked_info = True
                logger.debug("通过按钮 [聊天信息] 打开侧栏")
            except Exception as exc:
                logger.debug("点击按钮 [聊天信息] 失败: {}", exc)
        if not clicked_info:
            # 坐标兜底：窗口右上角
            fallback_x = win_rect.right - 30
            fallback_y = win_rect.top + 45
            try:
                auto.Click(fallback_x, fallback_y)
                clicked_info = True
                logger.debug("坐标兜底点击右上角: ({}, {})", fallback_x, fallback_y)
            except Exception as exc:
                logger.debug("右上角兜底点击失败: {}", exc)
                return None

        # 2) 等侧栏展开
        time.sleep(0.8)

        # 3) 固定坐标点击侧栏首个头像
        # 根据实际测量点 (1715, 244) 计算的相对偏移：距离窗口右侧约 205px，距离顶部约 190px
        target_x = win_rect.right - 205
        target_y = win_rect.top + 140
        try:
            auto.Click(target_x, target_y)
            logger.debug("侧栏头像固定坐标点击: ({}, {})", target_x, target_y)
        except Exception as exc:
            logger.debug("点击侧栏头像失败: {}", exc)
            return None

        # 4) 等资料卡窗口弹出
        end_time = time.time() + 3
        while time.time() < end_time:
            for title in self.PROFILE_TITLES:
                win = auto.WindowControl(Name=title, searchDepth=1)
                if win.Exists(0):
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

    def _extract_profile_info(self, profile_win: auto.WindowControl) -> Optional[ContactProfile]:
        """从资料卡提取微信号/昵称/备注。使用更灵活的提取逻辑。"""
        wechat_id: Optional[str] = None
        nickname: Optional[str] = None
        remark: Optional[str] = None

        # 提取昵称 - 使用多种方法寻找昵称控件
        try:
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
                text_controls = profile_win.GetChildren()
                for i, ctrl in enumerate(text_controls[:5]):  # 只检查前5个子控件
                    try:
                        text = getattr(ctrl, "Name", "")
                        if text and any('\u4e00' <= char <= '\u9fff' for char in str(text)) and "微信" not in str(text):
                            nickname = str(text).strip()
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
            all_text_controls = profile_win.GetDescendants()
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
                            # 如果当前控件是标签，没有值，尝试读取下一个文本控件作为值
                            if not value and idx + 1 < len(all_text_controls):
                                next_ctrl = all_text_controls[idx + 1]
                                next_text = str(getattr(next_ctrl, "Name", "") or "").strip()
                                if next_text:
                                    value = next_text

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

        # 缓存子项列表避免重复获取
        cached_items = items[:max_chats]
        logger.debug("开始被动扫描 {} 个会话，关键词: {}", len(cached_items), keywords)

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
            has_keywords = pre_match or self._chat_has_keywords(main, keywords)
            if not has_keywords:
                logger.debug("会话 {} 未包含关键词，跳过", idx)
                continue
            else:
                logger.info("✅ 会话 {} 匹配到关键词，准备提取资料", idx)

            profile_win = self._open_profile_from_chat(main)
            if not profile_win:
                logger.debug("未能打开资料卡，尝试兜底使用聊天标题/列表名称 idx={}", idx)
                fallback_profile = self._fallback_profile_from_header(main, item_name)
                if fallback_profile:
                    identifier = f"{fallback_profile.get('wechat_id','')}:{fallback_profile.get('nickname','')}"
                    if identifier not in self._processed_messages:
                        self._processed_messages.add(identifier)
                        results.append(fallback_profile)  # type: ignore[arg-type]
                        logger.info("⚠️ 资料卡未打开，使用兜底标识记录好友: {}", fallback_profile)
                continue

            try:
                # 尝试点击头像以进入更详细资料页
                try:
                    self._click_avatar_if_possible(profile_win)
                except Exception as avatar_exc:
                    logger.debug("点击头像进入详细资料失败: {}", avatar_exc)

                profile = self._extract_profile_info(profile_win)
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
                if control and control.Exists(1):
                    # 验证控件是否有合理的子项（表示这是会话列表）
                    try:
                        children = control.GetChildren()
                        if len(children) > 1 and len(children) < 100:  # 合理的会话数量
                            is_session_like = _looks_like_session_list(children)

                            # 显示控件信息用于调试
                            rect = control.BoundingRectangle
                            control_name = control.Name or "(无名称)"

                            logger.info("🔍 路径{}找到控件: {} ({}个子项) 名称: {}",
                                      i, control.ControlTypeName, len(children), control_name)

                            # 检查是否是正确的会话列表（名称应该是"会话"或在左侧）
                            is_left_side = False
                            window_rect = main_window.BoundingRectangle
                            # 放宽区域：用窗口左侧 40% 作为“左侧区域”判断，避免误杀（宽度 920 的窗口左侧 1/3≈30%）
                            window_left_40pct = window_rect.left + int(window_rect.width() * 0.40)

                            logger.info("窗口边界: 左={}, 宽={}, 左侧40%分界线={}",
                                       window_rect.left, window_rect.width(), window_left_40pct)
                            logger.info("控件边界: 左={}, 宽={}", rect.left, rect.width())

                            if rect.left < window_left_40pct:
                                is_left_side = True
                                logger.info("✅ 控件在左侧区域 ({} < {})", rect.left, window_left_40pct)
                            else:
                                logger.info("ℹ️ 控件在右侧区域 ({} >= {})", rect.left, window_left_40pct)

                            # 如果控件名称是"消息"，肯定不是会话列表
                            if control_name == "消息":
                                logger.info("❌ 控件名称是'消息'，这是聊天窗口，不是会话列表")
                                continue  # 跳过这个路径，尝试下一个

                            # 如果子项 AutomationId 命中 session_item_*，直接判定为会话列表
                            if is_session_like:
                                logger.info("✅ 路径{}匹配到 session_item_* 子项，判定为会话列表", i)
                                return control

                            # 如果在左侧或名称是"会话"，则是正确的会话列表
                            if is_left_side or control_name == "会话":
                                logger.info("✅ 路径{}成功找到正确的会话列表: {} ({}个子项)",
                                          i, control.ControlTypeName, len(children))

                                logger.info("🔍 会话列表详细信息:")
                                logger.info("   类型: {}", control.ControlTypeName)
                                logger.info("   名称: {}", control_name)
                                logger.info("   位置: ({},{}) 大小: {}x{}",
                                           rect.left, rect.top, rect.width(), rect.height())
                                logger.info("   子项数: {}", len(children))

                                # 显示前3个子项的信息
                                for j, child in enumerate(children[:3], 1):
                                    child_rect = child.BoundingRectangle
                                    child_name = child.Name or "(无名称)"
                                    logger.info("   子项{}: {} - {} 位置({},{})",
                                               j, child.ControlTypeName, child_name[:20],
                                               child_rect.left, child_rect.top)

                                return control
                            # 记录一个候选，作为兜底（左侧判断失败但结构合理）
                            if fallback_control is None:
                                fallback_control = control
                                fallback_info["rect"] = rect
                                fallback_info["children"] = len(children)
                            else:
                                logger.info("❌ 路径{}不是会话列表，继续尝试", i)
                        else:
                            logger.info("❌ 路径{}控件子项数量不合理: {}", i, len(children))
                    except Exception as e:
                        logger.info("❌ 路径{}控件验证失败: {}", i, e)
                else:
                    logger.info("❌ 路径{}未找到控件", i)
            except Exception as e:
                logger.info("❌ 路径{}搜索失败: {}", i, e)

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
