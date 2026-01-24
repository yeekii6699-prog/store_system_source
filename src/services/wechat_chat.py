"""
微信RPA聊天消息操作模块
负责聊天消息的获取、查找等操作
"""

from __future__ import annotations

import time
from typing import Optional, Sequence, List, Any

import uiautomation as auto
from loguru import logger


class WeChatChatOperations:
    """微信聊天消息操作类"""

    def __init__(self, owner: Any):
        """
        初始化聊天操作类

        Args:
            owner: 拥有此实例的WeChatRPA对象
        """
        self._owner = owner

    # ====================== 消息获取 ======================

    def _get_all_chat_messages(self, main_win: auto.WindowControl) -> List[str]:
        """获取当前聊天窗口中所有可见的消息文本"""
        messages: List[str] = []
        time.sleep(0.3)

        try:
            chat_list = self._owner._find_chat_message_list(main_win)
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

    def _find_chat_message_list(
        self, main_win: auto.WindowControl
    ) -> Optional[auto.Control]:
        """查找聊天消息列表控件"""
        # 方法1: 直接通过AutomationId查找
        direct = main_win.ListControl(AutomationId="chat_message_list", searchDepth=15)
        if direct.Exists(0.3):
            return direct

        # 方法2: 通过Name查找
        direct = main_win.ListControl(Name="消息", searchDepth=15)
        if direct.Exists(0.3):
            return direct

        # 方法3: 递归搜索
        all_controls: List[auto.Control] = []
        self._owner._collect_all_controls(main_win, all_controls, max_depth=15)

        candidates: List[auto.Control] = []
        for ctrl in all_controls:
            try:
                if getattr(ctrl, "ControlTypeName", "") != "ListControl":
                    continue
                aid = str(getattr(ctrl, "AutomationId", "") or "")
                name = str(getattr(ctrl, "Name", "") or "")
                cls = str(getattr(ctrl, "ClassName", "") or "")
                if aid == "session_list" or name == "会话":
                    continue
                if (
                    aid == "chat_message_list"
                    or "RecyclerListView" in cls
                    or name == "消息"
                ):
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
                if any(
                    x in cls
                    for x in (
                        "ChatDetailView",
                        "ChatMessagePage",
                        "MessageView",
                        "ChatMasterView",
                    )
                ):
                    return True
            return False

        for ctrl in candidates:
            if _has_chat_parent(ctrl):
                return ctrl

        return candidates[0] if candidates else None

    def _find_chat_content_area(
        self, main_win: auto.WindowControl
    ) -> Optional[auto.Control]:
        """查找聊天内容区域（通常在右侧）"""
        try:
            # 方法1: 查找输入框上方区域
            edit_control = main_win.EditControl()
            if edit_control.Exists(1):
                logger.debug("找到聊天输入框，在其上方查找内容区域")
                edit_rect = edit_control.BoundingRectangle

                for control in main_win.GetChildren():
                    try:
                        rect = control.BoundingRectangle
                        if (
                            rect.bottom < edit_rect.top
                            and rect.width() > 200
                            and rect.height() > 100
                        ):
                            if control.ControlTypeName in [
                                "Document",
                                "Pane",
                                "GroupControl",
                            ]:
                                logger.debug(
                                    "找到聊天内容区域: {} 位置({},{}) 大小{}x{}",
                                    control.ControlTypeName,
                                    rect.left,
                                    rect.top,
                                    rect.width(),
                                    rect.height(),
                                )
                                return control
                    except Exception:
                        continue

            # 方法2: 查找右侧区域
            window_rect = main_win.BoundingRectangle
            right_x = window_rect.left + window_rect.width() * 2 // 3

            all_controls: List[auto.Control] = []
            self._owner._collect_all_controls(main_win, all_controls, max_depth=10)
            for control in all_controls:
                try:
                    if control.ControlTypeName in ["Document", "Pane", "GroupControl"]:
                        rect = control.BoundingRectangle
                        if (
                            rect.left > right_x
                            and rect.width() > 200
                            and rect.height() > 200
                        ):
                            return control
                except Exception:
                    continue
        except Exception as e:
            logger.debug("查找聊天内容区域失败: {}", e)

        return None

    def _collect_all_text_from_control(
        self, control: auto.Control, max_depth: int = 20, current_depth: int = 0
    ) -> List[str]:
        """递归收集控件中的所有文本内容"""
        texts: List[str] = []

        if current_depth >= max_depth:
            return texts

        try:
            name = getattr(control, "Name", "") or ""
            if name and isinstance(name, str) and name.strip():
                texts.append(name.strip())

            if hasattr(control, "GetChildren"):
                for child in control.GetChildren():
                    child_texts = self._collect_all_text_from_control(
                        child, max_depth, current_depth + 1
                    )
                    texts.extend(child_texts)
        except Exception:
            pass

        return texts

    def _chat_has_keywords(
        self, main_win: auto.WindowControl, keywords: Sequence[str]
    ) -> bool:
        """检测当前会话的聊天内容是否包含特定关键词"""
        logger.debug("检查聊天页面内容，关键词: {}", keywords)

        all_messages = self._get_all_chat_messages(main_win)
        if not all_messages:
            logger.debug("未获取到任何聊天消息")
            return False

        combined_text = "\n".join(all_messages)

        # 精确匹配
        for kw in keywords:
            if not kw:
                continue
            if kw in combined_text:
                logger.info("在整页消息中找到关键词 [{}]", kw)
                return True

        # 模糊匹配系统消息
        system_patterns = [
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
                logger.info("在整页消息中模糊匹配到系统消息 [{}]", pattern)
                return True

        return False

    # ====================== 会话列表查找 ======================

    def _find_chat_list(
        self, main_window: auto.WindowControl
    ) -> Optional[auto.Control]:
        """查找会话列表控件"""
        search_paths = [
            lambda: main_window.ListControl(Name="会话", searchDepth=12),
            lambda: self._owner._find_control_by_name(
                main_window, "会话", "ListControl"
            ),
            lambda: main_window.GroupControl().ListControl(),
            lambda: main_window.ListControl(searchDepth=6),
            lambda: main_window.ListControl(searchDepth=8),
            lambda: main_window.ListControl(searchDepth=15),
            lambda: main_window.PaneControl(searchDepth=5).ListControl(searchDepth=3),
        ]

        fallback_control = None

        def _looks_like_session_list(children: List[auto.Control]) -> bool:
            for child in children:
                try:
                    aid = getattr(child, "AutomationId", "") or ""
                    if str(aid).startswith("session_item_"):
                        return True
                except Exception:
                    continue
            return False

        for i, path_func in enumerate(search_paths, 1):
            try:
                control = path_func()
                if not control or not control.Exists(1):
                    continue
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
                        "路径{}命中会话列表: {} ({}个子项)",
                        i,
                        control.ControlTypeName,
                        len(children),
                    )
                    return control

                if fallback_control is None:
                    fallback_control = control
            except Exception:
                continue

        if fallback_control:
            return fallback_control

        # 最终兜底：扫描所有ListControl
        all_controls: List[auto.Control] = []
        self._owner._collect_all_controls(main_window, all_controls, max_depth=20)
        list_controls = [
            c
            for c in all_controls
            if getattr(c, "ControlTypeName", "") == "ListControl"
        ]

        for ctrl in list_controls:
            try:
                children = ctrl.GetChildren()
                if not children or len(children) > 200:
                    continue
                rect = ctrl.BoundingRectangle
                if _looks_like_session_list(children) or rect.width() < 360:
                    return ctrl
            except Exception:
                continue

        logger.error("未找到会话列表")
        return None
