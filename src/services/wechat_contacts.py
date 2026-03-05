"""
微信RPA通讯录操作模块
负责通讯录tab、新的朋友、好友验证等操作
"""

from __future__ import annotations

import re
import time
from typing import Optional, List, Any, Literal, TypedDict, Callable

import uiautomation as auto
from loguru import logger


class NewFriendItem(TypedDict):
    """新的朋友列表项数据结构"""

    name: str  # 昵称
    status: Literal["已添加", "等待验证"]  # 状态（微信UI显示）
    raw_text: str  # 原始文本
    control: Any  # 控件对象


class WeChatContactsOperations:
    """微信通讯录操作类"""

    def __init__(self, owner: Any):
        """
        初始化通讯录操作类

        Args:
            owner: 拥有此实例的WeChatRPA对象
        """
        self._owner = owner
        self._processed_nickname: Optional[str] = None  # 暂存刚发送welcome的昵称

    def _ensure_foreground_for_action(self, action: str) -> bool:
        """执行RPA动作前确保微信窗口在前台。"""
        if self._owner._activate_window():
            return True
        logger.warning("RPA动作前激活微信失败，跳过本次操作: {}", action)
        return False

    def _ensure_contacts_tab(self) -> bool:
        """确保当前位于通讯录视图，避免无意义重复点击。"""
        contacts_tab = self._owner._find_control(
            auto.ButtonControl,
            Name="通讯录",
            ClassName="mmui::XTabBarItem",
            searchDepth=8,
        )
        if not contacts_tab or not contacts_tab.Exists(0.3):
            return self._click_contacts_tab()

        selected: Optional[bool] = None
        try:
            get_pattern = getattr(contacts_tab, "GetSelectionItemPattern", None)
            pattern = get_pattern() if get_pattern else None
            if pattern is not None:
                selected = bool(getattr(pattern, "IsSelected", False))
        except Exception:
            selected = None

        if selected is None:
            try:
                raw_selected = getattr(contacts_tab, "IsSelected", None)
                if isinstance(raw_selected, bool):
                    selected = raw_selected
            except Exception:
                selected = None

        if selected is True:
            logger.debug("当前已处于'通讯录'页，跳过点击")
            return True

        if selected is False:
            logger.debug("当前不在'通讯录'页，执行切换")
            return self._click_contacts_tab()

        # 无法读取Tab选中状态时，使用通讯录专用列表作为兜底判断
        list_container = self._owner._find_control(
            auto.ListControl,
            AutomationId="primary_table_.contact_list",
            searchDepth=12,
        )
        if list_container and list_container.Exists(0.3):
            logger.debug("检测到通讯录列表容器，判定已在'通讯录'页")
            return True

        logger.debug("无法确认是否在'通讯录'页，执行切换")
        return self._click_contacts_tab()

    def _find_new_friends_entry(self) -> Optional[Any]:
        """查找“新的朋友”分组入口，未找到通常表示当前无新好友（微信会隐藏该分组）。"""
        entry = self._owner._find_control(
            auto.ListItemControl,
            Name="新的朋友",
            ClassName="mmui::ContactsCellGroupView",
            searchDepth=15,
        )
        if entry and entry.Exists(0.3):
            return entry

        entry = self._owner._find_control(
            auto.ListItemControl,
            Name="新的朋友",
            searchDepth=15,
        )
        if entry and entry.Exists(0.3):
            return entry

        return None

    def _is_new_friends_expanded(self, entry: Any) -> Optional[bool]:
        """读取“新的朋友”分组展开状态；返回 None 表示控件不支持该模式。"""
        try:
            get_pattern = getattr(entry, "GetExpandCollapsePattern", None)
            if not get_pattern:
                return None

            pattern = get_pattern()
            if not pattern:
                return None

            state = getattr(pattern, "ExpandCollapseState", None)
            if state is None:
                return None

            if isinstance(state, (int, float)):
                # UIA常见值: 0=Collapsed, 1=Expanded, 2=PartiallyExpanded
                return int(state) in (1, 2)

            state_name = str(getattr(state, "name", state)).lower()
            if "expanded" in state_name:
                return True
            if "collapsed" in state_name:
                return False
        except Exception:
            return None
        return None

    # ====================== Tab切换 ======================

    def _click_contacts_tab(self) -> bool:
        """点击侧边栏'通讯录' Tab"""
        success = self._owner._click_button(
            "通讯录", timeout=2, search_depth=8, class_name="mmui::XTabBarItem"
        )
        if not success:
            logger.error("未找到'通讯录' Tab，触发截屏告警")
            self._owner._report_wechat_not_found("未找到'通讯录' Tab")
        return success

    def _return_to_chat_list(self) -> bool:
        """返回聊天列表界面"""
        return self._owner._click_button(
            "微信", timeout=2, search_depth=8, class_name="mmui::XTabBarItem"
        )

    # ====================== 新的朋友入口 ======================

    def _click_new_friends_entry(self) -> bool:
        """
        点击'新的朋友'入口。

        注意：只有收到好友请求时才会出现"新的朋友"入口，
        没有好友请求时找不到是正常情况，直接返回False即可。

        Returns:
            是否成功点击（False表示没有新的朋友，这是正常情况）
        """
        # 先检查是否已展开且有可处理项
        all_items = self._get_new_friends_items(check_only=True)
        if all_items:
            logger.debug("'新的朋友'列表已展开")
            return True

        entry = self._find_new_friends_entry()
        if not entry:
            # 没有入口是正常情况：微信在无新好友时会隐藏该分组
            logger.debug("未找到'新的朋友'入口（无新好友时会隐藏）")
            return False

        expanded = self._is_new_friends_expanded(entry)
        if expanded is True:
            logger.debug("'新的朋友'分组已展开（当前无待处理项）")
            return True

        if expanded is None:
            # 无法读取展开状态时，优先不点击，避免把已展开列表误收起。
            logger.debug("无法判断'新的朋友'展开状态，跳过点击以避免误收起")
            return True

        # 明确是收起状态时才点击展开
        try:
            if not self._ensure_foreground_for_action("click_new_friends_entry"):
                return False
            entry.Click()
            logger.debug("点击列表项 [新的朋友] 成功")
            self._owner._random_delay(0.5, 1.0)
            return True
        except Exception as exc:
            logger.debug("点击列表项 [新的朋友] 失败: {}", exc)

        # 备用：遍历查找
        main_win = self._owner._get_window(self._owner.WINDOW_NAME)
        if main_win:
            try:
                # 使用 GetDescendants 的安全方式
                descendants = getattr(main_win, "GetDescendants", None)
                if descendants:
                    for ctrl in descendants():
                        try:
                            if getattr(ctrl, "ControlTypeName", "") == "ListControl":
                                for child in ctrl.GetChildren():
                                    try:
                                        name = getattr(child, "Name", "") or ""
                                        cls = getattr(child, "ClassName", "") or ""
                                        if (
                                            name == "新的朋友"
                                            and cls == "mmui::ContactsCellGroupView"
                                        ):
                                            if not self._ensure_foreground_for_action(
                                                "click_new_friends_entry_fallback"
                                            ):
                                                return False
                                            child.Click()
                                            self._owner._random_delay(0.5, 1.0)
                                            return True
                                    except Exception:
                                        continue
                        except Exception:
                            continue
            except Exception:
                pass

        # 没有点击成功，保持容错返回False
        logger.debug("未能打开'新的朋友'分组")
        return False

    def _get_new_friends_items(self, check_only: bool = False) -> List[NewFriendItem]:
        """
        获取'新的朋友'列表中的所有项，区分'已通过'和'等待验证'。

        Args:
            check_only: 如果为True，只检查是否存在，不返回列表

        Returns:
            NewFriendItem列表，每个元素包含昵称、状态和控件
        """
        items: List[NewFriendItem] = []

        # 查找通讯录列表容器
        list_container = self._owner._find_control(
            auto.ListControl, AutomationId="primary_table_.contact_list", searchDepth=12
        )
        if not list_container or not list_container.Exists(1):
            list_container = self._owner._find_control(
                auto.ListControl,
                ClassName="mmui::StickyHeaderRecyclerListView",
                searchDepth=12,
            )

        if not list_container or not list_container.Exists(1):
            return items

        try:
            children = list_container.GetChildren()
            for child in children:
                try:
                    item_name = getattr(child, "Name", "") or ""
                    # 解析状态：格式如 "昵称 等待验证" 或 "昵称 已添加"
                    if "等待验证" in item_name:
                        nickname = item_name.replace("等待验证", "").strip()
                        status: Literal["已添加", "等待验证"] = "等待验证"
                        items.append(
                            NewFriendItem(
                                name=nickname,
                                status=status,
                                raw_text=item_name,
                                control=child,
                            )
                        )
                    elif "已添加" in item_name:
                        nickname = item_name.replace("已添加", "").strip()
                        status: Literal["已添加", "等待验证"] = "已添加"
                        items.append(
                            NewFriendItem(
                                name=nickname,
                                status=status,
                                raw_text=item_name,
                                control=child,
                            )
                        )
                except Exception:
                    continue

            if not check_only:
                if items:
                    verified_count = sum(1 for i in items if i["status"] == "已添加")
                    pending_count = sum(1 for i in items if i["status"] == "等待验证")
                    logger.info(
                        "新的朋友列表: 已添加={}, 等待验证={}",
                        verified_count,
                        pending_count,
                    )
                else:
                    logger.debug("新的朋友列表为空")
        except Exception as e:
            if not check_only:
                logger.error("获取新的朋友列表失败: {}", e)

        return items

    def _get_verified_friends(self) -> List[NewFriendItem]:
        """
        筛选'已添加'的好友列表（我主动添加后对方通过的情况）。

        Returns:
            已添加状态的列表项
        """
        all_items = self._get_new_friends_items()
        return [item for item in all_items if item["status"] == "已添加"]

    def _get_pending_verification(self) -> List[NewFriendItem]:
        """
        筛选'等待验证'的列表项（对方添加我，需要我前往验证）。

        Returns:
            等待验证状态的列表项
        """
        all_items = self._get_new_friends_items()
        return [item for item in all_items if item["status"] == "等待验证"]

    def _find_item_by_nickname(self, nickname: str) -> Optional[NewFriendItem]:
        """
        通过昵称在"新的朋友"列表中找到对应的项。

        列表项 Name 格式: "昵称 已添加" 或 "昵称 等待验证"

        Args:
            nickname: 要匹配的昵称

        Returns:
            匹配的 NewFriendItem，未找到返回 None
        """
        items = self._get_new_friends_items()
        for item in items:
            # 检查 item["name"] 是否包含目标昵称
            if nickname in item["name"] or item["name"] in nickname:
                logger.debug("通过昵称找到列表项: {} -> {}", nickname, item["name"])
                return item
        logger.debug("未找到昵称对应的列表项: {}", nickname)
        return None

    # ====================== 验证流程 ======================

    def _open_new_friend_detail(self, item: NewFriendItem) -> bool:
        """点击列表项，进入详情页"""
        control = item.get("control")
        if control and control.Exists(1):
            if not self._ensure_foreground_for_action("open_new_friend_detail"):
                return False
            control.Click()
            logger.debug("点击列表项成功: {}", item["name"])
            self._owner._random_delay()
            return True
        return False

    def _resolve_profile_nickname(self, fallback: str) -> str:
        """从资料卡补全昵称，失败则回退到列表昵称。"""
        try:
            profile_win = self._owner._profile._wait_profile_window(timeout=3.0)
        except Exception:
            profile_win = None

        if not profile_win:
            return fallback

        try:
            nickname = self._owner._profile._extract_nickname_from_profile(profile_win)
        except Exception:
            nickname = None

        if nickname and nickname.strip():
            return nickname.strip()

        try:
            profile_info = self._owner._profile._extract_profile_info(profile_win)
        except Exception:
            profile_info = None

        if profile_info:
            profile_nickname = (profile_info.get("nickname") or "").strip()
            if profile_nickname:
                return profile_nickname

        return fallback

    def _click_confirm_button(self) -> bool:
        """
        点击'前往验证'或'确定'按钮完成验证流程。

        对方加我时，需要点击"前往验证"按钮确认。
        """
        # 先尝试点击"前往验证"
        if self._owner._click_button(
            "前往验证", timeout=3, search_depth=15, class_name="mmui::XOutlineButton"
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        # 尝试点击"确定"
        if self._owner._click_button(
            "确定", timeout=3, search_depth=15, class_name="mmui::XOutlineButton"
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        # 备用：模糊匹配
        confirm_patterns = ["前往验证", "确定", "同意"]
        for pattern in confirm_patterns:
            if self._owner._click_button_by_name_contains(
                pattern, timeout=2, search_depth=15
            ):
                self._owner._random_delay(0.5, 1.0)
                time.sleep(0.8)
                return True

        logger.warning("未找到确认按钮")
        return False

    def _click_verify_button(self) -> bool:
        """
        点击'前往验证'按钮。

        Returns:
            是否成功点击
        """
        if self._owner._click_button(
            "前往验证", timeout=3, search_depth=15, class_name="mmui::XOutlineButton"
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        # 备用：模糊匹配
        if self._owner._click_button_by_name_contains(
            "前往验证", timeout=2, search_depth=15
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        logger.warning("未找到'前往验证'按钮")
        return False

    def _handle_verify_confirm_dialog(self) -> bool:
        """
        处理'前往验证'后的确认弹窗。

        点击"前往验证"按钮后会弹出一个确认对话框，需要点击"确定"完成验证。

        Returns:
            是否成功处理弹窗
        """
        # 等待弹窗出现并直接点击“确定”，不再切前台，避免打断验证链路
        time.sleep(0.5)

        # 方式1: 直接查找并点击主窗口里的“确定”按钮
        confirm_btn = self._owner._find_control(
            auto.ButtonControl,
            Name="确定",
            ClassName="mmui::XOutlineButton",
            searchDepth=15,
        )
        if confirm_btn and confirm_btn.Exists(0.8):
            try:
                confirm_btn.Click()
                logger.debug("直接点击'确定'按钮成功")
                self._owner._random_delay(0.5, 1.0)
                time.sleep(1.0)
                return True
            except Exception as exc:
                logger.debug("直接点击'确定'按钮失败: {}", exc)

        # 方式2: 放宽 ClassName 再尝试一次（仍然直接点击）
        confirm_btn = self._owner._find_control(
            auto.ButtonControl,
            Name="确定",
            searchDepth=20,
        )
        if confirm_btn and confirm_btn.Exists(0.8):
            try:
                confirm_btn.Click()
                logger.debug("放宽匹配后点击'确定'按钮成功")
                self._owner._random_delay(0.5, 1.0)
                time.sleep(1.0)
                return True
            except Exception as exc:
                logger.debug("放宽匹配点击'确定'失败: {}", exc)

        # 方式3: 查找弹窗 WindowControl
        popup_win = self._owner._find_control(
            auto.WindowControl, ClassName="mmui::Popup", searchDepth=10
        )
        if popup_win and popup_win.Exists(1):
            confirm_btn = popup_win.ButtonControl(Name="确定", searchDepth=10)
            if confirm_btn.Exists(0.5):
                confirm_btn.Click()
                logger.debug("在弹窗中点击'确定'按钮成功")
                self._owner._random_delay(0.5, 1.0)
                time.sleep(1.0)
                return True

        # 方式4: 查找 MessageBox 风格的窗口
        msgbox_win = self._owner._find_control(
            auto.WindowControl, RegexName=".*确认.*|.*验证.*", searchDepth=10
        )
        if msgbox_win and msgbox_win.Exists(0.5):
            confirm_btn = msgbox_win.ButtonControl(Name="确定", searchDepth=5)
            if confirm_btn.Exists(0.3):
                confirm_btn.Click()
                logger.debug("在消息框中点击'确定'按钮成功")
                self._owner._random_delay(0.5, 1.0)
                time.sleep(1.0)
                return True

        # 方式5: 通用方式查找所有"确定"按钮
        main_win = self._owner._get_window(self._owner.WINDOW_NAME)
        if main_win:
            try:
                descendants = getattr(main_win, "GetDescendants", None)
                if descendants:
                    for ctrl in descendants():
                        try:
                            if getattr(ctrl, "ControlTypeName", "") == "ButtonControl":
                                name = getattr(ctrl, "Name", "") or ""
                                cls = getattr(ctrl, "ClassName", "") or ""
                                if name == "确定" and "Outline" in cls:
                                    ctrl.Click()
                                    logger.debug("通过遍历找到并点击'确定'按钮")
                                    self._owner._random_delay(0.5, 1.0)
                                    time.sleep(1.0)
                                    return True
                        except Exception:
                            continue
            except Exception:
                pass

        logger.warning("未找到确认弹窗中的'确定'按钮，可能弹窗已关闭或结构变化")
        return True  # 弹窗可能已经自动关闭，返回True继续流程

    def _extract_wechat_id_from_profile(
        self,
        mode: str = "all",
        exclude_values: Optional[set[str]] = None,
    ) -> Optional[str]:
        """从资料卡片中提取微信号"""
        if not self._ensure_foreground_for_action("extract_wechat_id_from_profile"):
            return None

        time.sleep(0.8)  # 减少等待时间

        main_win = self._owner._get_window(self._owner.WINDOW_NAME)
        if not main_win.Exists(1):
            logger.debug("未找到微信主窗口")
            return None

        def collect_controls(
            control: Any, depth: int = 0, max_depth: int = 50
        ) -> List[Any]:
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

        def normalize_wechat_id_text(raw: str) -> str:
            value = (raw or "").strip()
            if not value:
                return ""

            for sep in (":", "："):
                if sep in value:
                    left, right = value.split(sep, 1)
                    left_text = left.strip().lower()
                    if "微信" in left or "wechat" in left_text:
                        value = right.strip()
                        break

            return value

        def normalize_compare_text(value: str) -> str:
            return (value or "").strip().lower()

        def is_valid_wechat_id(value: str) -> bool:
            # 微信号常规规则：字母开头，允许字母/数字/下划线/短横线，长度 5-20
            return bool(re.match(r"^[A-Za-z][A-Za-z0-9_.-]{4,19}$", value))

        exclude_texts = {
            normalize_compare_text(val)
            for val in (exclude_values or set())
            if normalize_compare_text(val)
        }

        # 查找 ContactProfileTextView 控件
        profile_text_views = []
        for ctrl in all_controls:
            try:
                ctrl_class = getattr(ctrl, "ClassName", "") or ""
                if "ContactProfileTextView" in ctrl_class:
                    ctrl_automation_id = getattr(ctrl, "AutomationId", "") or ""
                    ctrl_name = getattr(ctrl, "Name", "") or ""
                    is_offscreen = bool(getattr(ctrl, "IsOffscreen", False))
                    top = -1
                    try:
                        rect = getattr(ctrl, "BoundingRectangle", None)
                        top = int(getattr(rect, "top", -1))
                    except Exception:
                        top = -1
                    profile_text_views.append(
                        {
                            "name": normalize_wechat_id_text(ctrl_name),
                            "raw_name": ctrl_name,
                            "automation_id": ctrl_automation_id,
                            "is_offscreen": is_offscreen,
                            "top": top,
                        }
                    )
            except Exception:
                continue

        def pick_by_automation_id(predicate: Any, reason: str) -> Optional[str]:
            matches: List[dict[str, Any]] = []
            for item in profile_text_views:
                ctrl_name = str(item.get("name") or "").strip()
                ctrl_automation_id = str(item.get("automation_id") or "").strip()
                if bool(item.get("is_offscreen", False)):
                    continue
                if not predicate(ctrl_automation_id):
                    continue
                if not is_valid_wechat_id(ctrl_name):
                    continue
                if exclude_texts and normalize_compare_text(ctrl_name) in exclude_texts:
                    continue
                matches.append(item)

            if not matches:
                return None

            with_digits = [
                item
                for item in matches
                if any(ch.isdigit() for ch in str(item.get("name") or ""))
            ]
            ranked = with_digits if with_digits else matches

            ranked.sort(
                key=lambda it: (
                    int(it.get("top", -1)),
                    len(str(it.get("name") or "")),
                ),
                reverse=True,
            )

            best = ranked[0]
            ctrl_name = str(best.get("name") or "").strip()
            ctrl_automation_id = str(best.get("automation_id") or "").strip()
            logger.debug(
                "提取到微信号: {} (AutomationId={}, top={}, 命中={}, 候选数={})",
                ctrl_name,
                ctrl_automation_id,
                best.get("top", -1),
                reason,
                len(matches),
            )
            return ctrl_name

        exact_automation_id = (
            "right_v_view.user_info_center_view.basic_line_view.ContactProfileTextView"
        )

        # 1) 精确命中：用户提供的正确控件路径
        candidate = pick_by_automation_id(
            lambda aid: aid == exact_automation_id,
            "exact_basic_line_view",
        )
        if candidate:
            return candidate

        # 2) 次优：同路径前缀（不同窗口层级可能追加前缀）
        candidate = pick_by_automation_id(
            lambda aid: aid.endswith(exact_automation_id),
            "suffix_basic_line_view",
        )
        if candidate:
            return candidate

        if mode == "exact":
            logger.debug("微信号精确路径尚未就绪，继续等待资料面板刷新")
            return None

        # 3) 回退：user_info_center_view 下的 basic_line_view
        candidate = pick_by_automation_id(
            lambda aid: "user_info_center_view.basic_line_view" in aid
            and aid.endswith("ContactProfileTextView"),
            "user_info_center_basic_line_view",
        )
        if candidate:
            return candidate

        # 4) 最后回退：历史规则（basic_line_view）
        candidate = pick_by_automation_id(
            lambda aid: "basic_line_view" in aid
            and aid.endswith("ContactProfileTextView"),
            "legacy_basic_line_view",
        )
        if candidate:
            return candidate

        logger.debug("未找到有效的微信号")
        return None

    def _get_wechat_id_with_wait(
        self,
        timeout: float = 15.0,
        abort_check: Callable[[], bool] | None = None,
        exclude_values: Optional[set[str]] = None,
    ) -> Optional[str]:
        """
        等待并获取微信号，带超时控制。

        Args:
            timeout: 超时时间（秒）

        Returns:
            微信号字符串，超时返回None
        """
        overall_deadline = time.time() + max(timeout, 0.0)

        # 阶段1：先严格等待“前往验证确认后”才会出现的精确控件
        exact_wait_deadline = min(overall_deadline, time.time() + min(timeout, 6.0))
        while time.time() < exact_wait_deadline:
            if abort_check and abort_check():
                return None

            wechat_id = self._extract_wechat_id_from_profile(
                mode="exact",
                exclude_values=exclude_values,
            )
            if wechat_id:
                logger.debug("成功提取微信号(精确路径): {}", wechat_id)
                return wechat_id

            time.sleep(0.4)

        logger.debug("精确路径提取超时，开始回退提取微信号")

        # 阶段2：兜底回退（兼容控件层级差异）
        while time.time() < overall_deadline:
            if abort_check and abort_check():
                return None
            wechat_id = self._extract_wechat_id_from_profile(
                mode="all",
                exclude_values=exclude_values,
            )
            if wechat_id:
                logger.debug("成功提取微信号: {}", wechat_id)
                return wechat_id
            time.sleep(0.5)

        logger.warning("等待 {} 秒未能提取到微信号", timeout)
        return None

    def _get_identity_before_send(
        self,
        fallback_nickname: str,
        timeout: float = 15.0,
        abort_check: Callable[[], bool] | None = None,
    ) -> Optional[tuple[str, str]]:
        """点击发消息前，确保拿到有效昵称和微信号。"""

        def _wait_send_button_ready(wait_timeout: float) -> bool:
            end_time = time.time() + max(wait_timeout, 0.0)
            while time.time() < end_time:
                if abort_check and abort_check():
                    return False

                send_btn = self._owner._find_control(
                    auto.ButtonControl,
                    AutomationId="fixed_height_v_view.content_v_view.ContactProfileBottomUi.foot_button_view.chat_img_button",
                    searchDepth=20,
                )
                if send_btn and send_btn.Exists(0.2):
                    return True
                time.sleep(0.2)
            return False

        start_time = time.time()
        nickname = self._resolve_profile_nickname(fallback_nickname).strip()
        if not nickname:
            nickname = (fallback_nickname or "").strip()

        exclude_values: set[str] = set()
        if fallback_nickname:
            exclude_values.add(fallback_nickname)
        if nickname:
            exclude_values.add(nickname)

        wechat_id = self._get_wechat_id_with_wait(
            timeout=timeout,
            abort_check=abort_check,
            exclude_values=exclude_values,
        )
        if abort_check and abort_check():
            return None

        nickname_after_wait = self._resolve_profile_nickname(
            nickname or fallback_nickname
        ).strip()
        if nickname_after_wait:
            nickname = nickname_after_wait

        elapsed = time.time() - start_time
        remain = max(0.0, timeout - elapsed)
        if not _wait_send_button_ready(remain):
            logger.warning("发消息前未等到'发消息'按钮就绪")
            return None

        if not nickname or not wechat_id:
            logger.warning(
                "发消息前身份信息不完整: nickname={}, wechat_id={}",
                nickname or "<empty>",
                wechat_id or "<empty>",
            )
            return None

        logger.debug("发消息前校验通过: nickname={}, wechat_id={}", nickname, wechat_id)

        return nickname, wechat_id

    # ====================== 处理入口 ======================

    def _click_send_message_button(self) -> bool:
        """
        在右侧资料面板中点击'发消息'按钮。

        按钮控件信息：
        - Name: "发消息"
        - AutomationId: "fixed_height_v_view.content_v_view.ContactProfileBottomUi.foot_button_view.chat_img_button"
        - ClassName: "mmui::ContactProfileBottomButton"
        """
        # 方法1: 通过 AutomationId 精确查找
        send_btn = self._owner._find_control(
            auto.ButtonControl,
            AutomationId="fixed_height_v_view.content_v_view.ContactProfileBottomUi.foot_button_view.chat_img_button",
            searchDepth=20,
        )
        if send_btn and send_btn.Exists(1):
            if not self._ensure_foreground_for_action("click_send_message_button"):
                return False
            send_btn.Click()
            logger.debug("点击'发消息'按钮成功")
            self._owner._random_delay()
            return True

        # 方法2: 通过 Name 和 ClassName 查找
        send_btn = self._owner._find_control(
            auto.ButtonControl,
            Name="发消息",
            ClassName="mmui::ContactProfileBottomButton",
            searchDepth=20,
        )
        if send_btn and send_btn.Exists(1):
            if not self._ensure_foreground_for_action(
                "click_send_message_button_fallback"
            ):
                return False
            send_btn.Click()
            logger.debug("点击'发消息'按钮成功")
            self._owner._random_delay()
            return True

        # 方法3: 备用 - 通过按钮名称模糊查找
        if self._owner._click_button(
            "发消息",
            timeout=3,
            search_depth=15,
            class_name="mmui::ContactProfileBottomButton",
        ):
            return True

        logger.warning("未找到'发消息'按钮")
        return False

    def _right_click_and_delete(self, item: NewFriendItem) -> bool:
        """
        右键点击列表项，在弹出菜单中点击"删除"。

        控件信息：
        - 好友列表项: ListItemControl, ClassName: mmui::XTableCell
        - 右键菜单: WindowControl, Name: "Weixin", ClassName: mmui::XMenu
        - 删除菜单项: MenuItemControl, Name: "删除", ClassName: mmui::XMenuView

        Args:
            item: 要删除的好友列表项

        Returns:
            是否删除成功
        """
        control = item.get("control")
        if not control or not control.Exists(1):
            logger.warning("列表项控件不存在，无法删除")
            return False

        # 1. 右键点击列表项
        try:
            if not self._ensure_foreground_for_action("right_click_new_friend_item"):
                return False
            control.RightClick()
            logger.debug("右键点击列表项: {}", item["name"])
            self._owner._random_delay(0.3, 0.5)
        except Exception as e:
            logger.warning("右键点击失败: {}", e)
            return False

        # 2. 查找右键菜单中的"删除"项
        delete_menu = self._owner._find_control(
            auto.MenuItemControl,
            Name="删除",
            ClassName="mmui::XMenuView",
            searchDepth=10,
        )

        # 如果找不到，尝试通过 WindowControl 查找
        if not delete_menu or not delete_menu.Exists(0.5):
            menu_win = self._owner._find_control(
                auto.WindowControl,
                Name="Weixin",
                ClassName="mmui::XMenu",
                searchDepth=5,
            )
            if menu_win and menu_win.Exists(0.5):
                delete_menu = menu_win.MenuItemControl(Name="删除", searchDepth=10)

        if delete_menu and delete_menu.Exists(0.5):
            try:
                if not self._ensure_foreground_for_action("click_delete_menu"):
                    return False
                delete_menu.Click()
                logger.info("点击'删除'菜单项成功: {}", item["name"])
                self._owner._random_delay(0.5, 1.0)
                return True
            except Exception as e:
                logger.warning("点击删除菜单项失败: {}", e)
                return False

        logger.warning("未找到'删除'菜单项")
        # 按ESC关闭菜单
        try:
            auto.SendKeys("{Esc}")
        except Exception:
            pass
        return False

    def _delete_by_stored_nickname(self, feishu) -> bool:
        """
        通过暂存的昵称删除"新的朋友"列表中的记录。

        流程：
        1. 检查是否有暂存的昵称
        2. 通过昵称更新飞书状态为"已绑定"
        3. 返回"新的朋友"列表
        4. 通过昵称找到列表项
        5. 右键删除
        6. 清空暂存的昵称

        Args:
            feishu: 飞书客户端实例，用于更新状态

        Returns:
            是否删除成功
        """
        if not self._processed_nickname:
            logger.warning("没有暂存的昵称，无法删除")
            return False

        nickname = self._processed_nickname
        logger.info("通过昵称删除: {}", nickname)

        # ========== 更新飞书状态为"已绑定" ==========
        try:
            items = feishu.search_by_nickname(nickname)
            if items:
                # 优先匹配"已申请"状态的记录
                matched_item = None
                for item in items:
                    record_id = feishu._extract_record_id(item)
                    status = item.get("fields", {}).get("微信绑定状态", "")
                    if status == "已申请":
                        matched_item = (record_id, item)
                        break

                # 如果没找到"已申请"状态的，匹配任意状态的
                if not matched_item and items:
                    record_id = feishu._extract_record_id(items[0])
                    matched_item = (record_id, items[0])

                if matched_item:
                    record_id, _ = matched_item
                    feishu.update_status(record_id, "已绑定")
                    logger.info(
                        "飞书状态已更新为'已绑定': {} (record_id={})",
                        nickname,
                        record_id,
                    )
            else:
                logger.warning("未在飞书中找到昵称对应的记录: {}", nickname)
        except Exception as e:
            logger.warning("更新飞书状态失败: {} - {}", nickname, e)
        # ===========================================

        # 返回"新的朋友"列表（保持在通讯录视图）
        self._owner._activate_window()
        self._ensure_contacts_tab()
        self._click_new_friends_entry()
        self._owner._random_delay(0.5, 1.0)

        # 通过昵称找到列表项
        item = self._find_item_by_nickname(nickname)
        if not item:
            logger.warning("未找到昵称对应的列表项: {}", nickname)
            self._processed_nickname = None
            return False

        # 右键删除
        success = self._right_click_and_delete(item)
        self._processed_nickname = None
        return success

    def _process_verified_friend(
        self,
        item: NewFriendItem,
        feishu,
        welcome_enabled: bool,
        welcome_steps: List[dict[str, str | None]],
        abort_check: Callable[[], bool] | None = None,
    ) -> bool:
        """
        处理'已添加'的好友（我主动添加后对方通过）。

        流程：
        1. 点击列表项打开右侧资料面板
        2. 获取微信号
        3. 写入飞书（微信号列=微信号，昵称列=昵称，状态=已绑定）
        4. 点击"发消息"进入聊天
        5. 发送welcome，暂存昵称
        6. 返回"新的朋友"列表
        7. 通过昵称找到记录并删除
        8. 返回聊天列表

        Args:
            item: 好友列表项
            feishu: 飞书客户端实例
            welcome_enabled: 是否启用欢迎包
            welcome_steps: 欢迎包步骤

        Returns:
            是否处理成功
        """
        # 清洗昵称：取"我"前面的部分，"我"及之后的都删除
        raw_nickname = item["name"]
        if "我" in raw_nickname:
            idx = raw_nickname.find("我")
            nickname = raw_nickname[:idx].strip()
        else:
            nickname = raw_nickname
        logger.info("[已添加] 处理好友: {} (原始: {})", nickname, raw_nickname)

        if abort_check and abort_check():
            return False

        # 1. 点击列表项打开右侧资料面板
        if not self._open_new_friend_detail(item):
            logger.warning("[已添加] 无法进入详情页: {}", nickname)
            return False

        identity = self._get_identity_before_send(
            fallback_nickname=nickname,
            timeout=15.0,
            abort_check=abort_check,
        )
        if not identity:
            logger.warning(
                "[已添加] 未获取到有效昵称或微信号，跳过发消息: {}", nickname
            )
            return False

        nickname, wechat_id = identity

        # ========== 2-3. 获取微信号并写入飞书（点击发消息之前） ==========
        try:
            # 写入飞书：微信号字段=微信号，状态=已绑定
            feishu.upsert_contact_profile(
                wechat_id=wechat_id, nickname=nickname, status="已绑定"
            )
            logger.info(
                "[已添加] 飞书写入成功: 微信号={}, 昵称={}, 状态=已绑定",
                wechat_id,
                nickname,
            )
        except Exception as e:
            logger.warning("[已添加] 飞书写入失败: {} - {}", nickname, e)
        # =================================================================

        # 4. 点击"发消息"按钮进入聊天
        if abort_check and abort_check():
            return False
        if not self._click_send_message_button():
            logger.warning("[已添加] 点击'发消息'按钮失败: {}", nickname)
            return False

        # 5. 发送welcome（已在聊天窗口中，already_in_chat=True）
        if welcome_enabled and welcome_steps:
            self._owner.send_welcome_package(
                [nickname], welcome_steps, already_in_chat=True
            )
            self._processed_nickname = nickname  # 暂存昵称用于删除

        # 6. 通过昵称删除（会返回"新的朋友"列表再删除）
        if abort_check and abort_check():
            return False
        self._delete_by_stored_nickname(feishu)

        return True

    def _process_pending_verification(
        self,
        item: NewFriendItem,
        feishu,
        welcome_enabled: bool,
        welcome_steps: List[dict[str, str | None]],
        abort_check: Callable[[], bool] | None = None,
    ) -> bool:
        """
        处理'等待验证'的项（对方加我，需要我前往验证）。

        流程：
        1. 点击列表项打开详情页
        2. 点击"前往验证"按钮
        3. 处理确认弹窗（点击"确定"）
        4. 获取微信号
        5. 写入飞书（微信号列=微信号，昵称列=昵称，状态=已绑定）
        6. 点击"发消息"进入聊天
        7. 发送welcome，暂存昵称
        8. 返回"新的朋友"列表
        9. 通过昵称找到记录并删除
        10. 返回聊天列表

        Args:
            item: 待验证列表项
            feishu: 飞书客户端实例
            welcome_enabled: 是否启用欢迎包
            welcome_steps: 欢迎包步骤

        Returns:
            是否处理成功
        """
        # 清洗昵称：取"我"前面的部分，"我"及之后的都删除
        raw_nickname = item["name"]
        if "我" in raw_nickname:
            idx = raw_nickname.find("我")
            nickname = raw_nickname[:idx].strip()
        else:
            nickname = raw_nickname
        logger.info("[待验证] 处理好友: {} (原始: {})", nickname, raw_nickname)

        if abort_check and abort_check():
            return False

        # 1. 点击列表项打开详情页
        if not self._open_new_friend_detail(item):
            logger.warning("[待验证] 无法进入详情页: {}", nickname)
            return False

        # 2. 点击"前往验证"按钮
        if not self._click_verify_button():
            logger.warning("[待验证] 点击前往验证失败: {}", nickname)
            return False

        # 3. 处理确认弹窗（点击"确定"）
        if not self._handle_verify_confirm_dialog():
            logger.warning("[待验证] 处理确认弹窗失败: {}", nickname)
            # 继续尝试，可能弹窗已自动关闭

        identity = self._get_identity_before_send(
            fallback_nickname=nickname,
            timeout=15.0,
            abort_check=abort_check,
        )
        if not identity:
            logger.warning(
                "[待验证] 未获取到有效昵称或微信号，跳过发消息: {}", nickname
            )
            return False

        nickname, wechat_id = identity

        # ========== 4-5. 获取微信号并写入飞书（点击发消息之前） ==========
        try:
            # 写入飞书：微信号字段=微信号，状态=已绑定
            feishu.upsert_contact_profile(
                wechat_id=wechat_id, nickname=nickname, status="已绑定"
            )
            logger.info(
                "[待验证] 飞书写入成功: 微信号={}, 昵称={}, 状态=已绑定",
                wechat_id,
                nickname,
            )
        except Exception as e:
            logger.warning("[待验证] 飞书写入失败: {} - {}", nickname, e)
        # =================================================================

        # 6. 点击"发消息"按钮进入聊天
        if abort_check and abort_check():
            return False
        if not self._click_send_message_button():
            logger.warning("[待验证] 点击'发消息'按钮失败: {}", nickname)
            return False

        # 7. 发送welcome（已在聊天窗口中，already_in_chat=True）
        if welcome_enabled and welcome_steps:
            self._owner.send_welcome_package(
                [nickname], welcome_steps, already_in_chat=True
            )
            self._processed_nickname = nickname  # 暂存昵称用于删除

        # 8. 通过昵称删除（会返回"新的朋友"列表再删除）
        if abort_check and abort_check():
            return False
        self._delete_by_stored_nickname(feishu)

        return True

    # ====================== 扫描入口 ======================

    def scan_new_friends_via_contacts(
        self,
        feishu,
        welcome_enabled: bool,
        welcome_steps: List[Any],
        abort_check: Callable[[], bool] | None = None,
    ) -> int:
        """
        通过通讯录-新的朋友扫描并处理新好友。

        处理流程：
        1. 先处理'已添加'的好友（我主动添加后对方通过）
           - 发送welcome
           - 删除好友记录
        2. 再处理'等待验证'的项（对方加我）
           - 前往验证
           - 发送welcome
           - 删除好友记录

        Args:
            feishu: 飞书客户端实例，用于状态更新
            welcome_enabled: 是否启用欢迎包
            welcome_steps: 欢迎包步骤

        Returns:
            处理成功的好友数量
        """
        if abort_check and abort_check():
            return 0

        if not self._owner._activate_window():
            return 0

        # 先检查是否已处于“通讯录”页，不在则点击切换
        if abort_check and abort_check():
            return 0
        if not self._ensure_contacts_tab():
            return 0

        # 点击新的朋友
        if abort_check and abort_check():
            return 0
        if not self._click_new_friends_entry():
            return 0

        # 获取所有项
        all_items = self._get_new_friends_items()
        if not all_items:
            logger.debug("新的朋友列表为空")
            return 0

        # 分离两类好友
        verified_friends = self._get_verified_friends()
        pending_items = self._get_pending_verification()

        logger.info(
            "开始处理新好友: 已添加={}, 待验证={}",
            len(verified_friends),
            len(pending_items),
        )

        processed_count = 0

        # ====================== 第一阶段：处理'已添加'的好友 ======================
        for idx, item in enumerate(verified_friends, 1):
            if abort_check and abort_check():
                return processed_count
            try:
                logger.info(
                    "[阶段1/2] [{}/{}] 处理已添加好友", idx, len(verified_friends)
                )
                if self._process_verified_friend(
                    item,
                    feishu,
                    welcome_enabled,
                    welcome_steps,
                    abort_check=abort_check,
                ):
                    processed_count += 1
            except Exception as e:
                logger.error("[已添加] 处理异常: {} - {}", item["name"], e)
            finally:
                # 继续下一个前，确保仍在通讯录/新的朋友视图
                if idx < len(verified_friends):
                    self._owner._activate_window()
                    self._ensure_contacts_tab()
                    self._click_new_friends_entry()

            if abort_check and abort_check():
                return processed_count

        # ====================== 第二阶段：处理'等待验证'的好友 ======================
        for idx, item in enumerate(pending_items, 1):
            if abort_check and abort_check():
                return processed_count
            try:
                logger.info("[阶段2/2] [{}/{}] 处理待验证好友", idx, len(pending_items))
                if self._process_pending_verification(
                    item,
                    feishu,
                    welcome_enabled,
                    welcome_steps,
                    abort_check=abort_check,
                ):
                    processed_count += 1
            except Exception as e:
                logger.error("[待验证] 处理异常: {} - {}", item["name"], e)
            finally:
                # 继续下一个前，确保仍在通讯录/新的朋友视图
                if idx < len(pending_items):
                    self._owner._activate_window()
                    self._ensure_contacts_tab()
                    self._click_new_friends_entry()

            if abort_check and abort_check():
                return processed_count

        logger.info("扫描完成，共处理 {} 个新好友", processed_count)
        return processed_count
