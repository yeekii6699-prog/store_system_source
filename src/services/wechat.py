"""
微信RPA核心库
基于 uiautomation 的微信自动化操作

模块结构：
- wechat.py: 主类，公开API和业务流程
- wechat_ui.py: 通用UI操作（窗口、按钮、对话框等）
- wechat_profile.py: 资料卡操作
- wechat_chat.py: 聊天消息操作
- wechat_contacts.py: 通讯录操作
"""

from __future__ import annotations

import time
from typing import Optional, Sequence, Literal, List, TypedDict, Any, TYPE_CHECKING

import uiautomation as auto
from loguru import logger

from ..config.settings import get_config

# 导入UI操作基类
from .wechat_ui import WeChatUIOperations, pyperclip

# 导入操作模块
from .wechat_profile import WeChatProfileOperations
from .wechat_chat import WeChatChatOperations
from .wechat_contacts import WeChatContactsOperations

if TYPE_CHECKING:
    from .wechat_ui import WeChatUIOperations
    from .wechat_profile import WeChatProfileOperations
    from .wechat_chat import WeChatChatOperations
    from .wechat_contacts import WeChatContactsOperations


class ContactProfile(TypedDict, total=False):
    """微信资料卡信息，用于被动同步到飞书。"""

    wechat_id: str
    nickname: Optional[str]
    remark: Optional[str]


class WeChatRPA:
    """
    微信RPA核心类

    组合模式：主类负责业务流程，具体操作委托给各操作模块
    """

    WINDOW_NAME = "微信"
    PROFILE_TITLES = ("详细资料", "基本资料", "资料", "个人信息", "添加朋友")

    def __init__(self, exec_path: Optional[str] = None) -> None:
        """
        初始化微信RPA

        Args:
            exec_path: 微信可执行文件路径（可选）
        """
        self.exec_path = exec_path

        # 加载配置
        config = get_config()
        self.scan_interval = int(config.get("NEW_FRIEND_SCAN_INTERVAL", "30"))
        self.monitor_keywords = config.get("MONITOR_KEYWORDS", "").split(",") if config.get("MONITOR_KEYWORDS") else []
        self.max_chats = int(config.get("MAX_CHATS", "6"))

        # 初始化UI操作基类（提供通用UI方法）
        self._ui = WeChatUIOperations(self)

        # 初始化各操作模块
        self._profile = WeChatProfileOperations(self)
        self._chat = WeChatChatOperations(self)
        self._contacts = WeChatContactsOperations(self)

        # 用于被动扫描的去重
        self._processed_messages: set = set()

    # ====================== 委托UI操作方法 ======================

    def _get_window(self, name: str = "", class_name: str = "", search_depth: int = 1) -> Optional[Any]:
        return self._ui._get_window(name, class_name, search_depth)

    def _activate_window(self) -> bool:
        return self._ui._activate_window()

    def _wait_for_window(self, name: str = "", class_name: str = "", timeout: float = 5.0, search_depth: int = 3) -> Optional[Any]:
        return self._ui._wait_for_window(name, class_name, timeout, search_depth)

    def _click_button(self, name: str, timeout: float = 3.0, search_depth: int = 15, class_name: str = "") -> bool:
        return self._ui._click_button(name, timeout, search_depth, class_name)

    def _click_button_by_name_contains(self, name_contains: str, timeout: float = 3.0, search_depth: int = 15) -> bool:
        return self._ui._click_button_by_name_contains(name_contains, timeout, search_depth)

    def _find_and_click_list_item(self, name: str, timeout: float = 2.0, search_depth: int = 15) -> bool:
        return self._ui._find_and_click_list_item(name, timeout, search_depth)

    def _handle_dialog(self, button_names: List[str], timeout: float = 5.0) -> bool:
        return self._ui._handle_dialog(button_names, timeout)

    def _handle_confirm_dialog(self, window_names: List[str], button_names: List[str], timeout: float = 8.0) -> bool:
        return self._ui._handle_confirm_dialog(window_names, button_names, timeout)

    def _find_control(self, control_type: type, name: str = "", **kwargs) -> Optional[Any]:
        return self._ui._find_control(control_type, name, **kwargs)

    def _find_control_by_name(self, parent: Any, name: str, control_type: str) -> Optional[Any]:
        return self._ui._find_control_by_name(parent, name, control_type)

    def _collect_all_controls(self, parent: Any, controls_list: list, max_depth: int = 10, current_depth: int = 0) -> None:
        return self._ui._collect_all_controls(parent, controls_list, max_depth, current_depth)

    def _copy_image_to_clipboard(self, image_path: str) -> bool:
        return self._ui._copy_image_to_clipboard(image_path)

    def _send_keys_with_clipboard(self, text: str) -> None:
        return self._ui._send_keys_with_clipboard(text)

    def _send_text(self, text: str) -> None:
        return self._ui._send_text(text)

    def _send_image(self, image_path: str) -> bool:
        return self._ui._send_image(image_path)

    def _clean_keyword(self, keyword: Any) -> str:
        return self._ui._clean_keyword(keyword)

    def _random_delay(self, min_sec: float = 0.5, max_sec: float = 1.5) -> None:
        return self._ui._random_delay(min_sec, max_sec)

    def _extract_nickname_from_profile(self, profile_win: auto.WindowControl) -> Optional[str]:
        """从资料卡中提取昵称"""
        return self._profile._extract_nickname_from_profile(profile_win)

    def _detect_relationship_state(
        self,
        containers: Sequence[auto.Control],
        timeout: float = 6.0,
    ) -> Literal["friend", "stranger", "unknown", "not_found"]:
        """检测好友关系状态"""
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

    # ====================== 公开API ======================

    def check_relationship(self, keyword: Any) -> Literal["friend", "stranger", "unknown", "not_found"]:
        """检查关系状态"""
        keyword = self._clean_keyword(keyword)
        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return "unknown"

        result = "unknown"
        try:
            main_win = self._get_window(self.WINDOW_NAME)
            containers = [profile_win, main_win]
            result = self._detect_relationship_state(containers, timeout=6.0)
            if result != "unknown":
                logger.info("[关系检测] {} -> {}", keyword, result)
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")
        return result

    def apply_friend(self, keyword: Any) -> bool:
        """执行申请操作"""
        keyword = self._clean_keyword(keyword)
        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return False

        success = False
        try:
            if self._click_button("添加到通讯录", timeout=2, search_depth=10, class_name="mmui::XOutlineButton"):
                time.sleep(1)
                confirm_windows = ("申请添加朋友", "发送好友申请", "好友验证", "通过朋友验证")
                confirm_buttons = ("确定", "发送", "Send", "确定(&O)", "确定(&S)")
                success = self._handle_confirm_dialog(confirm_windows, confirm_buttons, timeout=8.0)
                if not success:
                    add_btn = profile_win.ButtonControl(Name="添加到通讯录", searchDepth=10)
                    if not add_btn.Exists(0):
                        success = True
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")
        return success

    def send_welcome_package(self, keyword: Any, steps: Sequence[dict], already_in_chat: bool = False) -> bool:
        """
        发送欢迎包

        Args:
            keyword: 搜索关键词
            steps: 欢迎包步骤
            already_in_chat: 是否已经在聊天窗口中（True=跳过搜索直接发送）
        """
        keyword = self._clean_keyword(keyword)
        if not pyperclip:
            return False

        if not already_in_chat:
            # 需要先搜索打开资料卡并点击"发消息"
            profile_win = self._search_and_open_profile(keyword)
            if not profile_win:
                return False

            try:
                if not self._click_button("发消息", timeout=2, search_depth=10):
                    logger.debug("未找到'发消息'按钮")
                    return False
                time.sleep(0.8)
            finally:
                if profile_win.Exists(0):
                    profile_win.SendKeys("{Esc}")

        self._activate_window()

        logger.info("开始向 [{}] 发送欢迎包...", keyword)
        for i, step in enumerate(steps):
            try:
                msg_type = step.get("type")
                content = step.get("content") or step.get("path") or step.get("url")
                if not content:
                    continue
                content = str(content)

                if msg_type == "text":
                    self._send_text(content)
                elif msg_type == "link":
                    title = step.get("title", "")
                    text = f"{title}\n{content}" if title else content
                    self._send_text(text)
                elif msg_type == "image":
                    if not self._send_image(content):
                        logger.error("图片复制失败: {}", content)
                time.sleep(1.0)
            except Exception as e:
                logger.error("发送步骤 {} 失败: {}", i + 1, e)
        return True

    def scan_new_friends_via_contacts(self, feishu, welcome_enabled: bool, welcome_steps: List[dict]) -> int:
        """通过通讯录-新的好友扫描并处理新好友"""
        return self._contacts.scan_new_friends_via_contacts(feishu, welcome_enabled, welcome_steps)

    def scan_passive_new_friends(
        self,
        keywords: Optional[Sequence[str]] = None,
        max_chats: Optional[int] = None
    ) -> List[ContactProfile]:
        """从会话列表被动扫描已添加好友（已废弃，建议使用scan_new_friends_via_contacts）"""
        results: List[ContactProfile] = []
        if not self._activate_window():
            return results

        if keywords is None:
            keywords = self.monitor_keywords
        if max_chats is None:
            max_chats = self.max_chats

        main = self._get_window(self.WINDOW_NAME)
        if not main.Exists(2):
            logger.error("未找到微信主窗口，跳过被动扫描")
            return results

        chat_list = self._chat._find_chat_list(main)
        if not chat_list:
            return results

        try:
            items = list(chat_list.GetChildren()) if hasattr(chat_list, 'GetChildren') else []
            if not items:
                logger.warning("会话列表为空")
                return results
        except Exception as e:
            logger.error("获取会话列表失败: {}", e)
            return results

        cached_items = list(reversed(items[:max_chats]))
        logger.debug("开始被动扫描 {} 个会话，关键词: {}", len(cached_items), keywords)

        for idx, item in enumerate(cached_items, start=1):
            try:
                item_name = item.Name or "(无名称)"
                item.Click()
                time.sleep(0.8)
            except Exception as exc:
                logger.debug("切换会话失败 idx={} err={}", idx, exc)
                continue

            if not self._chat._chat_has_keywords(main, keywords):
                logger.debug("会话 {} 未包含关键词，跳过", idx)
                continue

            profile_result = self._profile._open_profile_from_chat(main)
            if not profile_result:
                fallback_profile = self._profile._fallback_profile_from_header(main, item_name)
                if fallback_profile:
                    identifier = f"{fallback_profile.get('wechat_id','')}:{fallback_profile.get('nickname','')}"
                    if identifier not in self._processed_messages:
                        self._processed_messages.add(identifier)
                        results.append(fallback_profile)
                        logger.info("使用兜底标识记录好友: {}", fallback_profile)
                continue

            profile_win, sidebar_rect = profile_result
            try:
                if sidebar_rect is None:
                    self._profile._click_avatar_if_possible(profile_win)

                profile = self._profile._extract_profile_info(profile_win, sidebar_rect=sidebar_rect)
                if profile:
                    wechat_id = profile.get("wechat_id", "")
                    nickname = profile.get("nickname", "")
                    identifier = f"{wechat_id}:{nickname}"

                    if identifier not in self._processed_messages:
                        self._processed_messages.add(identifier)
                        results.append(profile)
                        logger.info("发现新的已添加好友: {}", profile)
            finally:
                try:
                    if sidebar_rect is None:
                        profile_win.SendKeys("{Esc}")
                except Exception:
                    pass
            time.sleep(0.5)

        return results

    # ====================== 内部方法 ======================

    def _search_and_open_profile(self, keyword: Any) -> Optional[auto.WindowControl]:
        """搜索关键词并打开资料卡"""
        keyword = self._clean_keyword(keyword)
        if not keyword:
            return None

        if not self._activate_window():
            return None

        main = self._get_window(self.WINDOW_NAME)

        def _log_focus_warning(action: str, exc: Exception) -> None:
            handle = getattr(main, "NativeWindowHandle", None)
            rect = getattr(main, "BoundingRectangle", None)
            rect_str = None
            if rect:
                rect_str = f"{rect.left},{rect.top},{rect.right},{rect.bottom}"
            logger.warning("[WeChatFocus] action={} keyword={} handle={} rect={} err={}",
                          action, keyword, handle, rect_str, exc)

        try:
            main.SwitchToThisWindow()
        except Exception as exc:
            _log_focus_warning("SwitchToThisWindow", exc)
        finally:
            try:
                main.SetFocus()
            except Exception as focus_exc:
                _log_focus_warning("SetFocus", focus_exc)

        auto.SendKeys('{Ctrl}f')
        logger.info("已发送 Ctrl+F 激活搜索框")

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
            tip_win = self._get_window("提示")
            if tip_win.Exists(0) and tip_win.TextControl(SubName="无法找到该用户", searchDepth=6).Exists(0):
                return True
            return False

        if _has_not_found_message():
            return None

        # 点击"网络查找"选项
        clicked = False
        network_find = main.ListItemControl(SubName="网络查找", searchDepth=15)
        if network_find.Exists(0.5):
            logger.debug("点击网络查找选项")
            network_find.Click()
            clicked = True
        else:
            network_find_v2 = main.ListItemControl(RegexName="网络查找.*", searchDepth=15)
            if network_find_v2.Exists(0.5):
                logger.debug("点击网络查找选项(v2)")
                network_find_v2.Click()
                clicked = True

        if not clicked:
            search_list = main.ListControl(AutomationId='search_list')
            if search_list.Exists(0.5):
                target = search_list.ListItemControl(AutomationId=f'search_item_{keyword}')
                if target.Exists(0):
                    logger.debug("点击精确匹配的搜索结果: {}", keyword)
                    target.Click()
                    clicked = True
                else:
                    for item in search_list.GetChildren():
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

        # 等待资料卡窗口
        profile_win = None
        end_time = time.time() + 4
        while time.time() < end_time:
            for title in self.PROFILE_TITLES:
                win = self._get_window(title)
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

        # 兜底：检查是否有发消息或添加按钮
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

    # ====================== 委托给操作模块 ======================

    def _find_chat_message_list(self, main_win: auto.WindowControl) -> Optional[auto.Control]:
        return self._chat._find_chat_message_list(main_win)

    def _find_chat_content_area(self, main_win: auto.WindowControl) -> Optional[auto.Control]:
        return self._chat._find_chat_content_area(main_win)

    def _collect_all_text_from_control(
        self,
        control: auto.Control,
        max_depth: int = 20,
        current_depth: int = 0
    ) -> List[str]:
        return self._chat._collect_all_text_from_control(control, max_depth, current_depth)

    def _chat_has_keywords(self, main_win: auto.WindowControl, keywords: Sequence[str]) -> bool:
        return self._chat._chat_has_keywords(main_win, keywords)
