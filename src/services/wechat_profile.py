"""
微信RPA资料卡操作模块
负责资料卡的打开、信息提取等操作
"""

from __future__ import annotations

import re
import time
from typing import Optional, List, Any, TYPE_CHECKING

import uiautomation as auto
from loguru import logger

if TYPE_CHECKING:
    from .wechat import WeChatRPA


class WeChatProfileOperations:
    """微信资料卡操作类"""

    PROFILE_TITLES = ("详细资料", "基本资料", "资料", "个人信息", "添加朋友")

    def __init__(self, owner: "WeChatRPA"):
        """
        初始化资料卡操作类

        Args:
            owner: 拥有此实例的WeChatRPA对象
        """
        self._owner = owner

    # ====================== 窗口等待 ======================

    def _wait_profile_window(self, timeout: float) -> Optional[auto.WindowControl]:
        """等待资料卡窗口"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            # 检查弹窗式资料卡
            popup = self._owner._get_window(class_name="mmui::ProfileUniquePop", search_depth=3)
            if popup.Exists(0.3):
                logger.debug("检测到弹窗式资料卡")
                try:
                    popup.SetFocus()
                except Exception:
                    pass
                return popup

            # 检查标题为"详细资料"等窗口
            for title in self.PROFILE_TITLES:
                win = self._owner._get_window(title)
                if win.Exists(0.3):
                    logger.debug("检测到资料窗口: {}", title)
                    try:
                        win.SetFocus()
                    except Exception:
                        pass
                    return win

            time.sleep(0.2)

        return None

    # ====================== 头像操作 ======================

    def _click_avatar_if_possible(self, profile_win: auto.WindowControl) -> None:
        """尝试点击资料卡中的头像"""
        try:
            avatar = profile_win.ImageControl(RegexName="avatar|头像", searchDepth=12)
            if avatar.Exists(0.3):
                try:
                    avatar.Click()
                    logger.debug("点击头像控件成功")
                    time.sleep(0.5)
                    return
                except Exception as exc:
                    logger.debug("点击头像控件失败: {}", exc)

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
                    if rect.width() > 40 and rect.width() < 400 and rect.height() < 400:
                        ctrl.Click()
                        logger.debug("通过 ContactProfileView 容器点击头像区域")
                        time.sleep(0.5)
                        return
                except Exception as exc:
                    logger.debug("点击 ContactProfileView 失败: {}", exc)
        except Exception:
            pass

    # ====================== 兜底提取 ======================

    def _fallback_profile_from_header(
        self,
        main_win: auto.WindowControl,
        item_name: Optional[str],
    ) -> Optional[dict]:
        """兜底：从聊天窗口标题或列表项名称提取标识"""
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

        tokens = candidate.replace("：", ":").split()
        first = tokens[0] if tokens else candidate
        first = first.split(":", 1)[0]
        if not first:
            return None

        return {"wechat_id": first, "nickname": candidate, "remark": None}

    # ====================== 信息提取 ======================

    def _extract_nickname_from_profile(self, profile_win: auto.WindowControl) -> Optional[str]:
        """
        从资料卡中提取昵称（仅昵称，不包含微信号）。

        Args:
            profile_win: 资料卡窗口

        Returns:
            昵称字符串，提取失败返回None
        """
        try:
            # 方法1: 通过 AutomationId 精确查找昵称控件
            # 昵称控件的 AutomationId 格式: right_v_view.nickname_button_view.display_name_text
            nickname_ctrl = profile_win.TextControl(
                AutomationId="right_v_view.nickname_button_view.display_name_text",
                searchDepth=20
            )
            if nickname_ctrl.Exists(0):
                nickname = (nickname_ctrl.Name or "").strip()
                if nickname and len(nickname) > 1:
                    logger.debug("提取到昵称: {}", nickname)
                    return nickname

            # 方法2: 通过 ClassName 查找 mmui::XTextView
            all_controls = list(profile_win.GetDescendants())[:100]
            for ctrl in all_controls:
                try:
                    cls = getattr(ctrl, "ClassName", "") or ""
                    if "XTextView" in cls or "ContactProfileTextView" in cls:
                        aid = getattr(ctrl, "AutomationId", "") or ""
                        # 昵称控件通常包含 display_name 或 nickname
                        if "display_name" in aid.lower() or "nickname" in aid.lower():
                            text = getattr(ctrl, "Name", "") or ""
                            if text and len(text) > 1 and len(text) < 30:
                                # 排除微信号格式
                                if not text.replace("_", "").replace("-", "").isalnum():
                                    logger.debug("提取到昵称: {}", text)
                                    return text
                except Exception:
                    continue

            # 方法3: 遍历查找包含中文的文本（昵称通常是中文）
            for ctrl in all_controls:
                try:
                    text = getattr(ctrl, "Name", "")
                    if not text:
                        continue
                    text_str = str(text).strip()
                    # 排除微信号、备注等字段
                    if "微信号" in text_str or "备注" in text_str or "微信" in text_str:
                        continue
                    # 排除纯数字和纯英文
                    if text_str.isdigit() or text_str.encode('utf-8').isalpha():
                        continue
                    # 判断是否包含中文（昵称通常是中文）
                    if any('\u4e00' <= char <= '\u9fff' for char in text_str):
                        if len(text_str) > 1 and len(text_str) < 30:
                            logger.debug("提取到昵称: {}", text_str)
                            return text_str
                except Exception:
                    continue
        except Exception as e:
            logger.debug("提取昵称失败: {}", e)

        return None

    def _extract_profile_info(
        self,
        profile_win: auto.Control,
        sidebar_rect: Optional[tuple[int, int, int, int]] = None,
    ) -> Optional[dict]:
        """从资料卡提取微信号/昵称/备注"""
        wechat_id: Optional[str] = None
        nickname: Optional[str] = None
        remark: Optional[str] = None

        def _looks_like_wechat_id(value: str) -> bool:
            value = value.strip()
            if not value or len(value) < 6 or len(value) > 20:
                return False
            if value.lower().startswith("wxid_"):
                return True
            if not value[0].isalpha():
                return False
            return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", value))

        # 提取昵称
        try:
            name_ctrl = profile_win.TextControl(foundIndex=1, searchDepth=6)
            if name_ctrl.Exists(0):
                nickname = (name_ctrl.Name or "").strip()
                if nickname and len(nickname) > 1:
                    logger.debug("提取到昵称: {}", nickname)

            if not nickname or len(nickname) <= 1:
                text_controls = list(profile_win.GetDescendants())[:20]
                for ctrl in text_controls:
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
                                logger.debug("提取到昵称: {}", nickname)
                                break
                    except Exception:
                        continue
        except Exception:
            pass

        # 字段映射
        field_mappings = {
            "微信号": "wechat_id",
            "WeChat": "wechat_id",
            "备注": "remark",
            "remark": "remark",
            "昵称": "nickname"
        }

        try:
            all_text_controls = list(profile_win.GetDescendants())

            for ctrl in all_text_controls:
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
                        logger.debug("提取微信号: {}", text)
                        continue

                    # 尝试匹配字段
                    for field_keyword, target_field in field_mappings.items():
                        if text.lower().startswith(field_keyword.lower()):
                            parts = text.split(":", 1)
                            value = parts[1].strip() if len(parts) > 1 and parts[1].strip() else ""
                            if value:
                                if target_field == "wechat_id" and not wechat_id:
                                    wechat_id = value
                                elif target_field == "remark" and not remark:
                                    remark = value
                                elif target_field == "nickname" and (not nickname or len(nickname) <= 1):
                                    nickname = value
                            break

                    if not wechat_id and _looks_like_wechat_id(text):
                        wechat_id = text
                except Exception:
                    continue
        except Exception:
            pass

        if wechat_id:
            return {"wechat_id": wechat_id, "nickname": nickname, "remark": remark}
        logger.debug("未从资料卡提取到微信号")
        return None

    # ====================== 从聊天打开资料卡 ======================

    def _open_profile_from_chat(
        self,
        main_win: auto.WindowControl,
    ) -> Optional[tuple[auto.Control, None]]:
        """打开资料卡：基于聊天消息列表定位头像并点击"""
        chat_list = self._owner._find_chat_message_list(main_win)
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
                candidates: List[auto.Control] = []
                all_controls: List[auto.Control] = []
                self._owner._collect_all_controls(item_ctrl, all_controls, max_depth=6)

                for ctrl in all_controls:
                    try:
                        ctrl_type = str(getattr(ctrl, "ControlTypeName", "") or "")
                        if ctrl_type in ("ImageControl", "ButtonControl", "PaneControl",
                                         "CustomControl", "GroupControl"):
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
                left_scored: List[tuple[int, auto.Control]] = []
                scored: List[tuple[int, auto.Control]] = []

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
                profile_win = self._wait_profile_window(timeout=1.6)
                if profile_win:
                    return (profile_win, None)

            return None
        except Exception as e:
            logger.debug("定位头像失败: {}", e)
            return None
