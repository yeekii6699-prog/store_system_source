"""Flet-based Modern UI for Store System"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, cast

import flet as ft
from loguru import logger

from src.config.network import network_config
from src.config.settings import (
    BASE_DIR,
    FIELD_LABELS,
    get_config,
    update_config,
    validate_required_config,
)
from src.core.engine import TaskEngine
from src.core.system import check_environment, run_self_check
from src.services.feishu import FeishuClient


class FletApp:
    """Modern Flet-based application interface"""

    PRIMARY_COLOR = ft.Colors.BLUE
    SUCCESS_COLOR = ft.Colors.GREEN_500
    WARNING_COLOR = ft.Colors.AMBER_500
    ERROR_COLOR = ft.Colors.RED_500
    SURFACE_COLOR = ft.Colors.WHITE
    BACKGROUND_COLOR = ft.Colors.GREY_50
    TEXT_PRIMARY = ft.Colors.GREY_900
    TEXT_SECONDARY = ft.Colors.GREY_600

    def __init__(self, engine: TaskEngine) -> None:
        self.engine = engine
        self.log_queue: "queue.Queue[str]" = queue.Queue(maxsize=500)
        self._log_sink_id = logger.add(
            self._queue_sink, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
        )
        self.log_history: list[str] = []

        self.is_running = False
        self.welcome_enabled = self.engine.welcome_enabled

        self.page: ft.Page | None = None
        self.status_dot: ft.Container | None = None
        self.status_text: ft.Text | None = None
        self.apply_count: ft.Text | None = None
        self.welcome_count: ft.Text | None = None
        self.fail_count: ft.Text | None = None
        self.log_list: ft.ListView | None = None
        self.log_empty_state: ft.Container | None = None
        self.quick_error_message: str | None = None
        self.quick_error_container: ft.Container | None = None
        self.quick_error_text: ft.Text | None = None
        self.nav_rail: ft.NavigationRail | None = None
        self.content_area: ft.Column | None = None

        self.monitor_interval_input: ft.TextField | None = None
        self.feishu_poll_input: ft.TextField | None = None
        self.jitter_input: ft.TextField | None = None
        self.welcome_switch: ft.Switch | None = None
        self.feishu_app_id_input: ft.TextField | None = None
        self.feishu_app_secret_input: ft.TextField | None = None
        self.feishu_table_url_input: ft.TextField | None = None
        self.feishu_profile_table_url_input: ft.TextField | None = None
        self.wechat_exec_path_input: ft.TextField | None = None
        self.network_proxy_input: ft.TextField | None = None
        self.use_system_proxy_switch: ft.Switch | None = None
        self.verify_ssl_switch: ft.Switch | None = None
        self.network_timeout_input: ft.TextField | None = None
        self.rpa_delay_min_input: ft.TextField | None = None
        self.rpa_delay_max_input: ft.TextField | None = None
        self.relationship_timeout_input: ft.TextField | None = None
        self.profile_timeout_input: ft.TextField | None = None
        self.button_timeout_input: ft.TextField | None = None
        self.log_retention_input: ft.TextField | None = None
        self.log_level_dropdown: ft.Dropdown | None = None
        self.webhook_url_input: ft.TextField | None = None
        self.alert_cooldown_input: ft.TextField | None = None
        self.welcome_step_delay_input: ft.TextField | None = None
        self.welcome_retry_count_input: ft.TextField | None = None
        self.feishu_rate_limit_input: ft.TextField | None = None
        self.config_status_text: ft.Text | None = None
        self.welcome_steps_data: list[dict[str, str]] = []
        self.welcome_steps_view: ft.Column | None = None

    def _queue_sink(self, message) -> None:
        try:
            self.log_queue.put_nowait(str(message).rstrip("\n"))
        except Exception:
            pass

    def _schedule_call(self, func: Callable[[], None], delay_ms: int) -> None:
        if not self.page:
            return

        async def _delayed_call() -> None:
            await asyncio.sleep(delay_ms / 1000)
            func()

        self.page.run_task(_delayed_call)

    def build(self, page: ft.Page) -> None:
        self.page = page

        page.title = "门店数字化运营系统"
        page.theme_mode = ft.ThemeMode.LIGHT
        setattr(page, "window_width", 1200)
        setattr(page, "window_height", 800)
        setattr(page, "window_min_width", 1000)
        setattr(page, "window_min_height", 700)
        page.padding = 0
        page.bgcolor = self.BACKGROUND_COLOR

        page.theme = ft.Theme(
            color_scheme=ft.ColorScheme(
                primary=self.PRIMARY_COLOR,
                primary_container=ft.Colors.BLUE_50,
                on_primary=ft.Colors.WHITE,
                secondary=ft.Colors.TEAL,
                surface=self.SURFACE_COLOR,
                on_surface=self.TEXT_PRIMARY,
            ),
            use_material3=True,
        )

        main_row = ft.Row(expand=True, spacing=0)

        self.nav_rail = self._build_nav_rail()
        main_row.controls.append(self.nav_rail)

        self.content_area = ft.Column(
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.START,
            spacing=0,
        )
        self.content_area.controls.append(self._build_operation_settings())
        main_row.controls.append(self.content_area)

        page.add(main_row)

        self._update_log_display()
        self._update_stats_display()

    def _build_nav_rail(self) -> ft.NavigationRail:
        return ft.NavigationRail(
            selected_index=2,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=100,
            min_extended_width=200,
            leading=ft.Column(
                [
                    ft.Icon(ft.Icons.STORE, size=40, color=self.PRIMARY_COLOR),
                    ft.Text(
                        "门店系统",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=self.TEXT_PRIMARY,
                    ),
                    ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icon(ft.Icons.DASHBOARD_OUTLINED),
                    selected_icon=ft.Icon(ft.Icons.DASHBOARD),
                    label="概览",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icon(ft.Icons.SETTINGS_OUTLINED),
                    selected_icon=ft.Icon(ft.Icons.SETTINGS),
                    label="设置",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icon(ft.Icons.TUNE_OUTLINED),
                    selected_icon=ft.Icon(ft.Icons.TUNE),
                    label="运营",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icon(ft.Icons.LIST_ALT_OUTLINED),
                    selected_icon=ft.Icon(ft.Icons.LIST_ALT),
                    label="日志",
                ),
            ],
            on_change=lambda e: self._on_nav_change(e),
            bgcolor=ft.Colors.WHITE,
        )

    def _build_dashboard(self) -> ft.Container:
        content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
        )

        welcome_banner = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.AUTO_GRAPH, size=32, color=self.PRIMARY_COLOR),
                    ft.Column(
                        [
                            ft.Text(
                                "欢迎回来，管理员",
                                size=24,
                                weight=ft.FontWeight.BOLD,
                                color=self.TEXT_PRIMARY,
                            ),
                            ft.Text(
                                "系统运行正常，正在监控飞书任务",
                                size=14,
                                color=self.TEXT_SECONDARY,
                            ),
                        ],
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.BLUE_50,
        )
        content.controls.append(welcome_banner)

        status_card = self._build_status_card()
        content.controls.append(status_card)

        metrics_row = ft.Row(
            [
                self._build_metric_card(
                    icon=ft.Icons.PERSON_ADD_ALT_1,
                    title="已申请",
                    value="0",
                    color=ft.Colors.BLUE_500,
                ),
                self._build_metric_card(
                    icon=ft.Icons.VOLUNTEER_ACTIVISM,
                    title="已欢迎",
                    value="0",
                    color=ft.Colors.TEAL_500,
                ),
                self._build_metric_card(
                    icon=ft.Icons.ERROR_OUTLINE,
                    title="失败",
                    value="0",
                    color=ft.Colors.RED_500,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        content.controls.append(metrics_row)

        if self.quick_error_text:
            self.quick_error_text.value = self.quick_error_message or ""
        else:
            self.quick_error_text = ft.Text(
                self.quick_error_message or "",
                size=12,
                color=ft.Colors.RED_700,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            )

        self.quick_error_container = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=18, color=ft.Colors.RED_600),
                    self.quick_error_text,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            border_radius=10,
            bgcolor=ft.Colors.RED_50,
            visible=bool(self.quick_error_message),
            margin=ft.margin.only(top=12),
        )

        actions_card = ft.Container(
            content=ft.Column(
                cast(
                    list[ft.Control],
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.FLASH_ON_OUTLINED,
                                    color=self.TEXT_SECONDARY,
                                ),
                                ft.Text(
                                    "快速操作",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=self.TEXT_PRIMARY,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Divider(height=20),
                        ft.Row(
                            cast(
                                list[ft.Control],
                                [
                                    self._build_action_button(
                                        "启动系统",
                                        ft.Icons.PLAY_ARROW,
                                        self.PRIMARY_COLOR,
                                        self._start_engine,
                                    ),
                                    self._build_action_button(
                                        "暂停监控",
                                        ft.Icons.PAUSE,
                                        self.WARNING_COLOR,
                                        self._pause_engine,
                                    ),
                                    self._build_action_button(
                                        "环境自检",
                                        ft.Icons.FACT_CHECK,
                                        ft.Colors.TEAL_500,
                                        self._run_self_check,
                                    ),
                                    self._build_action_button(
                                        "停止系统",
                                        ft.Icons.STOP_CIRCLE,
                                        self.ERROR_COLOR,
                                        self._stop_engine,
                                    ),
                                ],
                            ),
                            spacing=12,
                        ),
                        self.quick_error_container,
                    ],
                ),
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.WHITE,
        )
        content.controls.append(actions_card)

        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )

    def _build_status_card(self) -> ft.Container:
        self.status_dot = ft.Container(
            width=12,
            height=12,
            border_radius=6,
            bgcolor=ft.Colors.GREY_400,
        )
        self.status_text = ft.Text(
            "系统已停止",
            size=14,
            weight=ft.FontWeight.W_500,
            color=ft.Colors.GREY_600,
        )

        return ft.Container(
            content=ft.Row(
                [
                    self.status_dot,
                    self.status_text,
                    ft.Container(expand=True),
                    ft.Text(
                        "系统状态",
                        size=12,
                        color=ft.Colors.GREY_500,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=16,
            border_radius=16,
            bgcolor=ft.Colors.WHITE,
        )

    def _build_metric_card(
        self, icon, title: str, value: str, color: str
    ) -> ft.Container:
        value_text = ft.Text(
            value,
            size=36,
            weight=ft.FontWeight.BOLD,
            color=color,
        )

        if title == "已申请":
            self.apply_count = value_text
        elif title == "已欢迎":
            self.welcome_count = value_text
        elif title == "失败":
            self.fail_count = value_text

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, size=24, color=ft.Colors.GREY_400),
                            ft.Text(
                                title,
                                size=14,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        spacing=8,
                    ),
                    value_text,
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.WHITE,
            expand=True,
            alignment=ft.Alignment(-1, -1),
        )

    def _build_action_button(
        self, text: str, icon: ft.IconData, color: str, on_click: Callable[[], None]
    ) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            content=ft.Row(
                [
                    ft.Icon(icon, color=ft.Colors.WHITE),
                    ft.Text(
                        text,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=8,
            ),
            bgcolor=color,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
            ),
            on_click=lambda e: on_click(),
        )

    def _build_settings(self) -> ft.Container:
        content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
        )

        header = ft.Row(
            [
                ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=28, color=self.PRIMARY_COLOR),
                ft.Text(
                    "系统设置",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=self.TEXT_PRIMARY,
                ),
            ],
            spacing=12,
        )
        content.controls.append(header)

        cfg = get_config()
        missing_keys = validate_required_config(cfg)
        missing_labels = [FIELD_LABELS.get(key, key) for key in missing_keys]

        if missing_labels:
            content.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.WARNING_AMBER_OUTLINED,
                                color=ft.Colors.AMBER_700,
                            ),
                            ft.Text(
                                f"缺少必填配置: {', '.join(missing_labels)}",
                                size=12,
                                color=ft.Colors.AMBER_800,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=12,
                    border_radius=10,
                    bgcolor=ft.Colors.AMBER_50,
                )
            )

        if self.feishu_app_id_input:
            self.feishu_app_id_input.value = cfg.get("FEISHU_APP_ID", "")
        else:
            self.feishu_app_id_input = ft.TextField(value=cfg.get("FEISHU_APP_ID", ""))

        if self.feishu_app_secret_input:
            self.feishu_app_secret_input.value = cfg.get("FEISHU_APP_SECRET", "")
        else:
            self.feishu_app_secret_input = ft.TextField(
                value=cfg.get("FEISHU_APP_SECRET", ""),
                password=True,
                can_reveal_password=True,
            )

        if self.feishu_table_url_input:
            self.feishu_table_url_input.value = cfg.get("FEISHU_TABLE_URL", "")
        else:
            self.feishu_table_url_input = ft.TextField(
                value=cfg.get("FEISHU_TABLE_URL", "")
            )

        if self.feishu_profile_table_url_input:
            self.feishu_profile_table_url_input.value = cfg.get(
                "FEISHU_PROFILE_TABLE_URL", ""
            )
        else:
            self.feishu_profile_table_url_input = ft.TextField(
                value=cfg.get("FEISHU_PROFILE_TABLE_URL", "")
            )

        if self.wechat_exec_path_input:
            self.wechat_exec_path_input.value = cfg.get("WECHAT_EXEC_PATH", "")
        else:
            self.wechat_exec_path_input = ft.TextField(
                value=cfg.get("WECHAT_EXEC_PATH", "")
            )

        if self.welcome_steps_view is None:
            self.welcome_steps_data = self._load_welcome_steps_from_config(cfg)
            self.welcome_steps_view = ft.Column(spacing=8)
        self._refresh_welcome_steps_view()

        if self.welcome_switch:
            self.welcome_switch.value = (cfg.get("WELCOME_ENABLED") or "0") == "1"
        else:
            self.welcome_switch = ft.Switch(
                value=(cfg.get("WELCOME_ENABLED") or "0") == "1"
            )

        if not self.config_status_text:
            self.config_status_text = ft.Text("", size=12, color=ft.Colors.GREY_600)

        if self.network_proxy_input:
            self.network_proxy_input.value = cfg.get("NETWORK_PROXY", "")
        else:
            self.network_proxy_input = ft.TextField(
                value=cfg.get("NETWORK_PROXY", ""),
                hint_text="http://127.0.0.1:7890",
                width=400,
            )

        use_system_proxy = (cfg.get("NETWORK_USE_SYSTEM_PROXY") or "0") == "1"
        if self.use_system_proxy_switch:
            self.use_system_proxy_switch.value = use_system_proxy
        else:
            self.use_system_proxy_switch = ft.Switch(value=use_system_proxy)

        verify_ssl = (cfg.get("NETWORK_VERIFY_SSL") or "1") == "1"
        if self.verify_ssl_switch:
            self.verify_ssl_switch.value = verify_ssl
        else:
            self.verify_ssl_switch = ft.Switch(value=verify_ssl)

        if self.network_timeout_input:
            self.network_timeout_input.value = cfg.get("NETWORK_TIMEOUT", "15")
        else:
            self.network_timeout_input = ft.TextField(
                value=cfg.get("NETWORK_TIMEOUT", "15"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.rpa_delay_min_input:
            self.rpa_delay_min_input.value = cfg.get("RPA_DELAY_MIN", "0.5")
        else:
            self.rpa_delay_min_input = ft.TextField(
                value=cfg.get("RPA_DELAY_MIN", "0.5"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.rpa_delay_max_input:
            self.rpa_delay_max_input.value = cfg.get("RPA_DELAY_MAX", "1.5")
        else:
            self.rpa_delay_max_input = ft.TextField(
                value=cfg.get("RPA_DELAY_MAX", "1.5"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.relationship_timeout_input:
            self.relationship_timeout_input.value = cfg.get(
                "RELATIONSHIP_DETECT_TIMEOUT", "6.0"
            )
        else:
            self.relationship_timeout_input = ft.TextField(
                value=cfg.get("RELATIONSHIP_DETECT_TIMEOUT", "6.0"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.profile_timeout_input:
            self.profile_timeout_input.value = cfg.get("PROFILE_WAIT_TIMEOUT", "4.0")
        else:
            self.profile_timeout_input = ft.TextField(
                value=cfg.get("PROFILE_WAIT_TIMEOUT", "4.0"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.button_timeout_input:
            self.button_timeout_input.value = cfg.get("BUTTON_FIND_TIMEOUT", "3.0")
        else:
            self.button_timeout_input = ft.TextField(
                value=cfg.get("BUTTON_FIND_TIMEOUT", "3.0"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.log_retention_input:
            self.log_retention_input.value = cfg.get("LOG_RETENTION_DAYS", "7")
        else:
            self.log_retention_input = ft.TextField(
                value=cfg.get("LOG_RETENTION_DAYS", "7"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.log_level_dropdown:
            self.log_level_dropdown.value = cfg.get("LOG_LEVEL", "INFO")
        else:
            self.log_level_dropdown = ft.Dropdown(
                options=[
                    ft.dropdown.Option("DEBUG", "DEBUG"),
                    ft.dropdown.Option("INFO", "INFO"),
                    ft.dropdown.Option("WARNING", "WARNING"),
                    ft.dropdown.Option("ERROR", "ERROR"),
                ],
                value=cfg.get("LOG_LEVEL", "INFO"),
                width=120,
            )

        if self.webhook_url_input:
            self.webhook_url_input.value = cfg.get("FEISHU_WEBHOOK_URL", "")
        else:
            self.webhook_url_input = ft.TextField(
                value=cfg.get("FEISHU_WEBHOOK_URL", ""),
                hint_text="https://open.feishu.cn/open-apis/bot/v2/hook/...",
                width=400,
            )

        if self.alert_cooldown_input:
            self.alert_cooldown_input.value = cfg.get("ALERT_COOLDOWN", "60")
        else:
            self.alert_cooldown_input = ft.TextField(
                value=cfg.get("ALERT_COOLDOWN", "60"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        poll_value = str(int(float(cfg.get("FEISHU_POLL_INTERVAL", "5"))))
        if self.feishu_poll_input:
            self.feishu_poll_input.value = poll_value
        else:
            self.feishu_poll_input = ft.TextField(
                value=poll_value,
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.feishu_rate_limit_input:
            self.feishu_rate_limit_input.value = cfg.get(
                "FEISHU_RATE_LIMIT_COOLDOWN", "0.3"
            )
        else:
            self.feishu_rate_limit_input = ft.TextField(
                value=cfg.get("FEISHU_RATE_LIMIT_COOLDOWN", "0.3"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.welcome_step_delay_input:
            self.welcome_step_delay_input.value = cfg.get("WELCOME_STEP_DELAY", "1.0")
        else:
            self.welcome_step_delay_input = ft.TextField(
                value=cfg.get("WELCOME_STEP_DELAY", "1.0"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        if self.welcome_retry_count_input:
            self.welcome_retry_count_input.value = cfg.get("WELCOME_RETRY_COUNT", "0")
        else:
            self.welcome_retry_count_input = ft.TextField(
                value=cfg.get("WELCOME_RETRY_COUNT", "0"),
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        feishu_card = self._build_setting_card(
            title="飞书接入",
            settings=[
                ft.Column(
                    [
                        ft.Text(
                            "飞书 App ID",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        self.feishu_app_id_input,
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text(
                            "飞书 App Secret",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        self.feishu_app_secret_input,
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text(
                            "预约表链接 (任务表)",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        self.feishu_table_url_input,
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text(
                            "客户表链接 (资料表)",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        self.feishu_profile_table_url_input,
                    ],
                    spacing=8,
                ),
                ft.Text(
                    "飞书 App 与表格链接修改后需重启引擎/程序生效。",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "检查连接",
                            bgcolor=self.PRIMARY_COLOR,
                            color=ft.Colors.WHITE,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=8)
                            ),
                            on_click=lambda e: self._check_feishu_connection(),
                        ),
                        self.config_status_text,
                    ],
                    spacing=12,
                    alignment=ft.MainAxisAlignment.START,
                ),
            ],
        )
        content.controls.append(feishu_card)

        wechat_card = self._build_setting_card(
            title="微信配置",
            settings=[
                ft.Column(
                    [
                        ft.Text(
                            "PC 微信启动路径",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        self.wechat_exec_path_input,
                    ],
                    spacing=8,
                ),
            ],
        )
        content.controls.append(wechat_card)

        # 网络设置卡片
        network_card = self._build_setting_card(
            title="网络设置",
            settings=[
                ft.Column(
                    [
                        ft.Text("手动代理地址", size=14, color=self.TEXT_PRIMARY),
                        self.network_proxy_input
                        if self.network_proxy_input
                        else ft.TextField(
                            value=cfg.get("NETWORK_PROXY", ""),
                            hint_text="http://127.0.0.1:7890",
                            width=400,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Row(
                    [
                        ft.Text("使用系统代理", size=14, color=self.TEXT_PRIMARY),
                        self.use_system_proxy_switch
                        if self.use_system_proxy_switch
                        else ft.Switch(
                            value=(cfg.get("NETWORK_USE_SYSTEM_PROXY") or "0") == "1"
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Row(
                    [
                        ft.Text("验证 SSL 证书", size=14, color=self.TEXT_PRIMARY),
                        self.verify_ssl_switch
                        if self.verify_ssl_switch
                        else ft.Switch(
                            value=(cfg.get("NETWORK_VERIFY_SSL") or "1") == "1"
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Column(
                    [
                        ft.Text("网络超时（秒）", size=14, color=self.TEXT_PRIMARY),
                        self.network_timeout_input
                        if self.network_timeout_input
                        else ft.TextField(
                            value=cfg.get("NETWORK_TIMEOUT", "15"),
                            width=100,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    spacing=8,
                ),
            ],
        )
        content.controls.append(network_card)

        # RPA 行为设置卡片
        rpa_card = self._build_setting_card(
            title="RPA 行为设置",
            settings=[
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "操作最小延迟（秒）",
                                    size=14,
                                    color=self.TEXT_PRIMARY,
                                ),
                                self.rpa_delay_min_input
                                if self.rpa_delay_min_input
                                else ft.TextField(
                                    value=cfg.get("RPA_DELAY_MIN", "0.5"),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    "操作最大延迟（秒）",
                                    size=14,
                                    color=self.TEXT_PRIMARY,
                                ),
                                self.rpa_delay_max_input
                                if self.rpa_delay_max_input
                                else ft.TextField(
                                    value=cfg.get("RPA_DELAY_MAX", "1.5"),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=30,
                ),
            ],
        )
        content.controls.append(rpa_card)

        # 超时设置卡片
        timeout_card = self._build_setting_card(
            title="超时设置",
            settings=[
                ft.Column(
                    [
                        ft.Text("关系检测超时（秒）", size=14, color=self.TEXT_PRIMARY),
                        self.relationship_timeout_input
                        if self.relationship_timeout_input
                        else ft.TextField(
                            value=cfg.get("RELATIONSHIP_DETECT_TIMEOUT", "6.0"),
                            width=100,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text(
                            "资料卡等待超时（秒）", size=14, color=self.TEXT_PRIMARY
                        ),
                        self.profile_timeout_input
                        if self.profile_timeout_input
                        else ft.TextField(
                            value=cfg.get("PROFILE_WAIT_TIMEOUT", "4.0"),
                            width=100,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text("按钮查找超时（秒）", size=14, color=self.TEXT_PRIMARY),
                        self.button_timeout_input
                        if self.button_timeout_input
                        else ft.TextField(
                            value=cfg.get("BUTTON_FIND_TIMEOUT", "3.0"),
                            width=100,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    spacing=8,
                ),
            ],
        )
        content.controls.append(timeout_card)

        # 日志与告警设置卡片
        log_card = self._build_setting_card(
            title="日志与告警",
            settings=[
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "日志保留天数", size=14, color=self.TEXT_PRIMARY
                                ),
                                self.log_retention_input
                                if self.log_retention_input
                                else ft.TextField(
                                    value=cfg.get("LOG_RETENTION_DAYS", "7"),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Column(
                            [
                                ft.Text("日志级别", size=14, color=self.TEXT_PRIMARY),
                                self.log_level_dropdown
                                if self.log_level_dropdown
                                else ft.Dropdown(
                                    options=[
                                        ft.dropdown.Option("DEBUG", "DEBUG"),
                                        ft.dropdown.Option("INFO", "INFO"),
                                        ft.dropdown.Option("WARNING", "WARNING"),
                                        ft.dropdown.Option("ERROR", "ERROR"),
                                    ],
                                    value=cfg.get("LOG_LEVEL", "INFO"),
                                    width=120,
                                ),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=30,
                ),
                ft.Text(
                    "日志级别与保留天数需重启程序后生效。",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                ft.Column(
                    [
                        ft.Text(
                            "飞书告警 Webhook URL", size=14, color=self.TEXT_PRIMARY
                        ),
                        self.webhook_url_input
                        if self.webhook_url_input
                        else ft.TextField(
                            value=cfg.get("FEISHU_WEBHOOK_URL", ""),
                            hint_text="https://open.feishu.cn/open-apis/bot/v2/hook/...",
                            width=400,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text("告警推送冷却（秒）", size=14, color=self.TEXT_PRIMARY),
                        self.alert_cooldown_input
                        if self.alert_cooldown_input
                        else ft.TextField(
                            value=cfg.get("ALERT_COOLDOWN", "60"),
                            width=100,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    spacing=8,
                ),
            ],
        )
        content.controls.append(log_card)

        # 飞书轮询卡片
        poll_card = self._build_setting_card(
            title="飞书轮询",
            settings=[
                ft.Column(
                    [
                        ft.Text("飞书轮询间隔（秒）", size=14, color=self.TEXT_PRIMARY),
                        ft.Row(
                            [
                                self.feishu_poll_input
                                if self.feishu_poll_input
                                else ft.TextField(
                                    value=str(
                                        int(float(cfg.get("FEISHU_POLL_INTERVAL", "5")))
                                    ),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Text(
                                    f"范围: 3-60", size=12, color=ft.Colors.GREY_500
                                ),
                            ],
                            spacing=12,
                        ),
                    ],
                    spacing=8,
                ),
                ft.ElevatedButton(
                    "应用设置",
                    bgcolor=self.PRIMARY_COLOR,
                    color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                    on_click=lambda e: self._apply_feishu_poll(),
                ),
                ft.Row(
                    [
                        ft.Text("飞书频控冷却（秒）", size=14, color=self.TEXT_PRIMARY),
                        self.feishu_rate_limit_input
                        if self.feishu_rate_limit_input
                        else ft.TextField(
                            value=cfg.get("FEISHU_RATE_LIMIT_COOLDOWN", "0.3"),
                            width=100,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    spacing=12,
                ),
            ],
        )
        content.controls.append(poll_card)

        welcome_card = self._build_setting_card(
            title="欢迎包配置",
            settings=[
                ft.Row(
                    [
                        ft.Text(
                            "启用自动欢迎包",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        self.welcome_switch,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "新增步骤",
                            bgcolor=self.PRIMARY_COLOR,
                            color=ft.Colors.WHITE,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=8)
                            ),
                            on_click=lambda e: self._open_welcome_step_dialog(None),
                        ),
                        ft.OutlinedButton(
                            "清空步骤",
                            on_click=lambda e: self._clear_welcome_steps(),
                        ),
                    ],
                    spacing=12,
                ),
                ft.Container(
                    content=self.welcome_steps_view,
                    padding=12,
                    border_radius=10,
                    bgcolor=ft.Colors.GREY_50,
                ),
                ft.Text(
                    "支持文字/图片/链接步骤，可用上下按钮调整顺序。",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
            ],
        )
        content.controls.append(welcome_card)

        # 欢迎包设置卡片
        welcome_detail_card = self._build_setting_card(
            title="欢迎包设置",
            settings=[
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "欢迎步骤间隔（秒）",
                                    size=14,
                                    color=self.TEXT_PRIMARY,
                                ),
                                self.welcome_step_delay_input
                                if self.welcome_step_delay_input
                                else ft.TextField(
                                    value=cfg.get("WELCOME_STEP_DELAY", "1.0"),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    "欢迎失败重试次数", size=14, color=self.TEXT_PRIMARY
                                ),
                                self.welcome_retry_count_input
                                if self.welcome_retry_count_input
                                else ft.TextField(
                                    value=cfg.get("WELCOME_RETRY_COUNT", "0"),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                            spacing=8,
                        ),
                    ],
                    spacing=30,
                ),
            ],
        )
        content.controls.append(welcome_detail_card)

        content.controls.append(
            ft.Row(
                [
                    ft.ElevatedButton(
                        "保存配置",
                        bgcolor=self.PRIMARY_COLOR,
                        color=ft.Colors.WHITE,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=10)
                        ),
                        on_click=lambda e: self._save_config_changes(),
                    ),
                    ft.ElevatedButton(
                        "重启程序",
                        bgcolor=self.WARNING_COLOR,
                        color=ft.Colors.WHITE,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=10)
                        ),
                        on_click=lambda e: self._restart_program(),
                    ),
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
            )
        )

        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )

    def _build_operation_settings(self) -> ft.Container:
        content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
        )

        header = ft.Row(
            [
                ft.Icon(ft.Icons.TUNE_OUTLINED, size=28, color=self.PRIMARY_COLOR),
                ft.Text(
                    "运营设置",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=self.TEXT_PRIMARY,
                ),
            ],
            spacing=12,
        )
        content.controls.append(header)

        cfg = get_config()
        monitor_value = str(int(float(cfg.get("NEW_FRIEND_SCAN_INTERVAL", "30"))))
        if self.monitor_interval_input:
            self.monitor_interval_input.value = monitor_value
        else:
            self.monitor_interval_input = ft.TextField(
                value=monitor_value,
                width=100,
                text_align=ft.TextAlign.CENTER,
            )

        jitter_value = str(int(float(cfg.get("PASSIVE_SCAN_JITTER", "5"))))
        if self.jitter_input:
            self.jitter_input.value = jitter_value
        else:
            self.jitter_input = ft.TextField(
                value=jitter_value,
                width=100,
                text_align=ft.TextAlign.CENTER,
            )
        monitor_card = self._build_setting_card(
            title="监控设置",
            settings=[
                ft.Column(
                    [
                        ft.Text(
                            "新好友扫描间隔（秒）",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        ft.Row(
                            [
                                self.monitor_interval_input
                                if self.monitor_interval_input
                                else ft.TextField(
                                    value=str(
                                        int(
                                            float(
                                                cfg.get(
                                                    "NEW_FRIEND_SCAN_INTERVAL", "30"
                                                )
                                            )
                                        )
                                    ),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Text(
                                    f"范围: 5-300",
                                    size=12,
                                    color=ft.Colors.GREY_500,
                                ),
                            ],
                            spacing=12,
                        ),
                    ],
                    spacing=8,
                ),
                ft.ElevatedButton(
                    "应用设置",
                    bgcolor=self.PRIMARY_COLOR,
                    color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                    on_click=lambda e: self._apply_monitor_interval(),
                ),
            ],
        )
        content.controls.append(monitor_card)

        jitter_card = self._build_setting_card(
            title="抖动设置",
            settings=[
                ft.Column(
                    [
                        ft.Text(
                            "扫描抖动时间（秒）",
                            size=14,
                            weight=ft.FontWeight.W_500,
                            color=self.TEXT_PRIMARY,
                        ),
                        ft.Row(
                            [
                                self.jitter_input
                                if self.jitter_input
                                else ft.TextField(
                                    value=str(
                                        int(float(cfg.get("PASSIVE_SCAN_JITTER", "5")))
                                    ),
                                    width=100,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Text(
                                    f"范围: 0-30",
                                    size=12,
                                    color=ft.Colors.GREY_500,
                                ),
                            ],
                            spacing=12,
                        ),
                    ],
                    spacing=8,
                ),
                ft.ElevatedButton(
                    "应用设置",
                    bgcolor=self.PRIMARY_COLOR,
                    color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                    on_click=lambda e: self._apply_jitter(),
                ),
            ],
        )
        content.controls.append(jitter_card)

        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )

    def _build_setting_card(
        self, title: str, settings: list[ft.Control]
    ) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        title,
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=self.TEXT_PRIMARY,
                    ),
                    ft.Divider(height=16),
                    ft.Column(
                        settings,
                        spacing=16,
                    ),
                ],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.WHITE,
        )

    def _load_welcome_steps_from_config(
        self, cfg: dict[str, str]
    ) -> list[dict[str, str]]:
        steps: list[dict[str, str]] = []
        raw = (cfg.get("WELCOME_STEPS") or "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            steps.append({k: str(v) for k, v in item.items()})
            except json.JSONDecodeError:
                logger.warning("欢迎包步骤解析失败，将回退旧字段")

        if steps:
            return steps

        legacy_text = (cfg.get("WELCOME_TEXT") or "").strip()
        if legacy_text:
            steps.append({"type": "text", "content": legacy_text})
        legacy_images = [
            item.strip()
            for item in (cfg.get("WELCOME_IMAGE_PATHS") or "").split("|")
            if item.strip()
        ]
        for image in legacy_images:
            steps.append({"type": "image", "path": image})
        return steps

    def _welcome_step_summary(self, step: dict[str, str]) -> str:
        action = (step.get("type") or "").lower()
        if action == "text":
            content = step.get("content", "")
            return (content[:40] + "…") if len(content) > 40 else content
        if action == "image":
            path = step.get("path", "")
            return Path(path).name or path
        if action == "link":
            title = step.get("title", "")
            url = step.get("url", "")
            return f"{title} | {url}" if title else url
        return step.get("content", "") or step.get("path", "") or step.get("url", "")

    def _refresh_welcome_steps_view(self) -> None:
        if not self.welcome_steps_view:
            return

        self.welcome_steps_view.controls.clear()
        if not self.welcome_steps_data:
            self.welcome_steps_view.controls.append(
                ft.Text(
                    "暂无步骤，点击“新增步骤”添加。", size=12, color=ft.Colors.GREY_600
                )
            )
        else:
            for idx, step in enumerate(self.welcome_steps_data):
                self.welcome_steps_view.controls.append(
                    self._build_welcome_step_row(idx, step)
                )

        if self.page:
            self.page.update()

    def _build_welcome_step_row(self, index: int, step: dict[str, str]) -> ft.Container:
        type_map = {"text": "文字", "image": "图片", "link": "链接"}
        type_value = (step.get("type") or "").lower()
        type_label = type_map.get(type_value, type_value or "未知")
        type_color = ft.Colors.BLUE_500
        if type_value == "image":
            type_color = ft.Colors.TEAL_500
        elif type_value == "link":
            type_color = ft.Colors.AMBER_500

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(f"{index + 1}.", size=12, color=ft.Colors.GREY_600),
                    ft.Container(
                        content=ft.Text(type_label, size=11, color=ft.Colors.WHITE),
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        border_radius=8,
                        bgcolor=type_color,
                    ),
                    ft.Text(
                        self._welcome_step_summary(step),
                        size=12,
                        color=self.TEXT_PRIMARY,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_UPWARD,
                        tooltip="上移",
                        on_click=lambda e, idx=index: self._move_welcome_step(idx, -1),
                        disabled=index == 0,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_DOWNWARD,
                        tooltip="下移",
                        on_click=lambda e, idx=index: self._move_welcome_step(idx, 1),
                        disabled=index >= len(self.welcome_steps_data) - 1,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.EDIT,
                        tooltip="编辑",
                        on_click=lambda e, idx=index: self._open_welcome_step_dialog(
                            idx
                        ),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="删除",
                        icon_color=ft.Colors.RED_500,
                        on_click=lambda e, idx=index: self._delete_welcome_step(idx),
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=8,
            border_radius=8,
            bgcolor=ft.Colors.WHITE,
        )

    def _open_welcome_step_dialog(self, index: int | None) -> None:
        if not self.page:
            return

        editing = index is not None
        current = self.welcome_steps_data[index] if editing else {"type": "text"}

        type_dropdown = ft.Dropdown(
            value=(current.get("type") or "text").lower(),
            options=[
                ft.dropdown.Option("text", "文字"),
                ft.dropdown.Option("image", "图片"),
                ft.dropdown.Option("link", "链接"),
            ],
            width=140,
        )
        text_field = ft.TextField(
            value=current.get("content", ""),
            multiline=True,
            min_lines=4,
            max_lines=8,
        )
        image_field = ft.TextField(value=current.get("path", ""))
        link_title_field = ft.TextField(value=current.get("title", ""))
        link_url_field = ft.TextField(value=current.get("url", ""))

        text_group = ft.Column(
            [
                ft.Text("文字内容", size=12, color=ft.Colors.GREY_600),
                text_field,
            ],
            spacing=8,
            visible=type_dropdown.value == "text",
        )
        image_group = ft.Column(
            [
                ft.Text("图片路径", size=12, color=ft.Colors.GREY_600),
                image_field,
            ],
            spacing=8,
            visible=type_dropdown.value == "image",
        )
        link_group = ft.Column(
            [
                ft.Text("链接标题（可选）", size=12, color=ft.Colors.GREY_600),
                link_title_field,
                ft.Text("链接 URL", size=12, color=ft.Colors.GREY_600),
                link_url_field,
            ],
            spacing=8,
            visible=type_dropdown.value == "link",
        )

        def _sync_groups(_=None) -> None:
            value = type_dropdown.value
            text_group.visible = value == "text"
            image_group.visible = value == "image"
            link_group.visible = value == "link"
            if self.page:
                self.page.update()

        type_dropdown.on_select = _sync_groups

        def _save_step(_=None) -> None:
            step_type = type_dropdown.value or "text"
            if step_type == "text":
                content = text_field.value.strip()
                if not content:
                    self._show_snackbar("请输入文字内容")
                    return
                step = {"type": "text", "content": content}
            elif step_type == "image":
                path = image_field.value.strip()
                if not path:
                    self._show_snackbar("请输入图片路径")
                    return
                step = {"type": "image", "path": path}
            else:
                url = link_url_field.value.strip()
                if not url:
                    self._show_snackbar("请输入链接 URL")
                    return
                title = link_title_field.value.strip()
                step = {"type": "link", "url": url}
                if title:
                    step["title"] = title

            if editing and index is not None:
                self.welcome_steps_data[index] = step
            else:
                self.welcome_steps_data.append(step)

            self._close_dialog(dialog)
            self._refresh_welcome_steps_view()

        dialog = ft.AlertDialog(
            modal=True,
            title="编辑欢迎步骤" if editing else "新增欢迎步骤",
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("步骤类型", size=12, color=ft.Colors.GREY_600),
                            type_dropdown,
                        ],
                        spacing=12,
                    ),
                    text_group,
                    image_group,
                    link_group,
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog(dialog)),
                ft.ElevatedButton(
                    "保存",
                    bgcolor=self.PRIMARY_COLOR,
                    color=ft.Colors.WHITE,
                    on_click=_save_step,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        dialog.open = True
        self.page.show_dialog(dialog)
        self.page.update()

    def _close_dialog(self, dialog: ft.AlertDialog) -> None:
        dialog.open = False
        if self.page:
            self.page.pop_dialog()
            self.page.update()

    def _clear_welcome_steps(self) -> None:
        self.welcome_steps_data = []
        self._refresh_welcome_steps_view()

    def _delete_welcome_step(self, index: int) -> None:
        if 0 <= index < len(self.welcome_steps_data):
            self.welcome_steps_data.pop(index)
            self._refresh_welcome_steps_view()

    def _move_welcome_step(self, index: int, offset: int) -> None:
        target = index + offset
        if target < 0 or target >= len(self.welcome_steps_data):
            return
        self.welcome_steps_data[index], self.welcome_steps_data[target] = (
            self.welcome_steps_data[target],
            self.welcome_steps_data[index],
        )
        self._refresh_welcome_steps_view()

    def _collect_config_values(self) -> tuple[dict[str, str], list[dict[str, str]]]:
        welcome_enabled = (
            bool(self.welcome_switch.value) if self.welcome_switch else False
        )
        steps = list(self.welcome_steps_data)

        values = {
            "FEISHU_APP_ID": (
                self.feishu_app_id_input.value if self.feishu_app_id_input else ""
            ).strip(),
            "FEISHU_APP_SECRET": (
                self.feishu_app_secret_input.value
                if self.feishu_app_secret_input
                else ""
            ).strip(),
            "FEISHU_TABLE_URL": (
                self.feishu_table_url_input.value if self.feishu_table_url_input else ""
            ).strip(),
            "FEISHU_PROFILE_TABLE_URL": (
                self.feishu_profile_table_url_input.value
                if self.feishu_profile_table_url_input
                else ""
            ).strip(),
            "WECHAT_EXEC_PATH": (
                self.wechat_exec_path_input.value if self.wechat_exec_path_input else ""
            ).strip(),
            "WELCOME_ENABLED": "1" if welcome_enabled else "0",
            "WELCOME_TEXT": "",
            "WELCOME_IMAGE_PATHS": "",
            "WELCOME_STEPS": json.dumps(steps, ensure_ascii=False) if steps else "",
            # 运行时配置（通过"应用设置"按钮实时生效，但也要保存）
            "NEW_FRIEND_SCAN_INTERVAL": (
                str(int(self.engine.passive_scan_interval))
                if self.monitor_interval_input
                else "30"
            ),
            "PASSIVE_SCAN_JITTER": (
                str(int(self.engine.passive_scan_jitter)) if self.jitter_input else "5"
            ),
            "FEISHU_POLL_INTERVAL": (
                str(int(self.engine.feishu_poll_interval))
                if self.feishu_poll_input
                else "5"
            ),
            # 新增配置项
            "NETWORK_PROXY": (
                self.network_proxy_input.value if self.network_proxy_input else ""
            ).strip(),
            "NETWORK_USE_SYSTEM_PROXY": (
                "1"
                if self.use_system_proxy_switch and self.use_system_proxy_switch.value
                else "0"
            ),
            "NETWORK_VERIFY_SSL": (
                "1" if self.verify_ssl_switch and self.verify_ssl_switch.value else "0"
            ),
            "NETWORK_TIMEOUT": (
                self.network_timeout_input.value if self.network_timeout_input else "15"
            ).strip(),
            "FEISHU_RATE_LIMIT_COOLDOWN": (
                self.feishu_rate_limit_input.value
                if self.feishu_rate_limit_input
                else "0.3"
            ).strip(),
            "RPA_DELAY_MIN": (
                self.rpa_delay_min_input.value if self.rpa_delay_min_input else "0.5"
            ).strip(),
            "RPA_DELAY_MAX": (
                self.rpa_delay_max_input.value if self.rpa_delay_max_input else "1.5"
            ).strip(),
            "LOG_RETENTION_DAYS": (
                self.log_retention_input.value if self.log_retention_input else "7"
            ).strip(),
            "LOG_LEVEL": (
                (self.log_level_dropdown.value or "INFO")
                if self.log_level_dropdown
                else "INFO"
            ).strip(),
            "FEISHU_WEBHOOK_URL": (
                self.webhook_url_input.value if self.webhook_url_input else ""
            ).strip(),
            "ALERT_COOLDOWN": (
                self.alert_cooldown_input.value if self.alert_cooldown_input else "60"
            ).strip(),
            "WELCOME_STEP_DELAY": (
                self.welcome_step_delay_input.value
                if self.welcome_step_delay_input
                else "1.0"
            ).strip(),
            "WELCOME_RETRY_COUNT": (
                self.welcome_retry_count_input.value
                if self.welcome_retry_count_input
                else "0"
            ).strip(),
            "RELATIONSHIP_DETECT_TIMEOUT": (
                self.relationship_timeout_input.value
                if self.relationship_timeout_input
                else "6.0"
            ).strip(),
            "PROFILE_WAIT_TIMEOUT": (
                self.profile_timeout_input.value
                if self.profile_timeout_input
                else "4.0"
            ).strip(),
            "BUTTON_FIND_TIMEOUT": (
                self.button_timeout_input.value if self.button_timeout_input else "3.0"
            ).strip(),
        }
        return values, steps

    def _apply_config_to_engine(
        self, cfg: dict[str, str], steps: list[dict[str, str]]
    ) -> None:
        self.engine.cfg = cfg
        self.engine.welcome_enabled = (cfg.get("WELCOME_ENABLED") or "0") == "1"
        self.engine.welcome_steps = steps
        self.welcome_enabled = self.engine.welcome_enabled

        # 应用网络配置
        network_config.reload()

        # 应用 RPA 延迟配置
        self.engine.rpa_delay_min = float(cfg.get("RPA_DELAY_MIN") or 0.5)
        self.engine.rpa_delay_max = float(cfg.get("RPA_DELAY_MAX") or 1.5)

        # 应用超时配置
        self.engine.relationship_timeout = float(
            cfg.get("RELATIONSHIP_DETECT_TIMEOUT") or 6.0
        )
        self.engine.profile_timeout = float(cfg.get("PROFILE_WAIT_TIMEOUT") or 4.0)
        self.engine.button_timeout = float(cfg.get("BUTTON_FIND_TIMEOUT") or 3.0)

        # 应用飞书频控冷却
        self.engine.feishu_rate_limit_cooldown = float(
            cfg.get("FEISHU_RATE_LIMIT_COOLDOWN") or 0.3
        )

        # 应用欢迎包细化配置
        self.engine.welcome_step_delay = float(cfg.get("WELCOME_STEP_DELAY") or 1.0)
        self.engine.welcome_retry_count = int(cfg.get("WELCOME_RETRY_COUNT") or 0)

        # 应用日志配置
        self.engine.log_retention_days = int(cfg.get("LOG_RETENTION_DAYS") or 7)
        self.engine.log_level = cfg.get("LOG_LEVEL") or "INFO"

        # 应用告警配置
        self.engine.alert_cooldown = int(cfg.get("ALERT_COOLDOWN") or 60)

        if self.engine.feishu:
            self.engine.feishu._min_request_interval = (
                self.engine.feishu_rate_limit_cooldown
            )

        if self.engine.wechat:
            self.engine.wechat.rpa_delay_min = self.engine.rpa_delay_min
            self.engine.wechat.rpa_delay_max = self.engine.rpa_delay_max
            self.engine.wechat.relationship_timeout = self.engine.relationship_timeout
            self.engine.wechat.profile_timeout = self.engine.profile_timeout
            self.engine.wechat.button_timeout = self.engine.button_timeout
            self.engine.wechat.welcome_step_delay = self.engine.welcome_step_delay
            self.engine.wechat.welcome_retry_count = self.engine.welcome_retry_count

    def _save_config_changes(self) -> None:
        try:
            values, steps = self._collect_config_values()
        except ValueError as exc:
            self._show_snackbar(str(exc))
            return

        missing = validate_required_config(values)
        if missing:
            missing_labels = [FIELD_LABELS.get(key, key) for key in missing]
            self._show_snackbar(f"缺少必填配置: {', '.join(missing_labels)}")
            return

        if values.get("WELCOME_ENABLED") == "1" and not steps:
            self._show_snackbar("启用欢迎包后至少配置一条步骤")
            return

        cfg = update_config(values, persist=True)
        network_config.reload()
        self._apply_config_to_engine(cfg, steps)
        self._show_snackbar("配置已保存")

    def _check_feishu_connection(self) -> None:
        if not self.page:
            return

        values = {
            "FEISHU_APP_ID": (
                self.feishu_app_id_input.value if self.feishu_app_id_input else ""
            ).strip(),
            "FEISHU_APP_SECRET": (
                self.feishu_app_secret_input.value
                if self.feishu_app_secret_input
                else ""
            ).strip(),
            "FEISHU_TABLE_URL": (
                self.feishu_table_url_input.value if self.feishu_table_url_input else ""
            ).strip(),
            "FEISHU_PROFILE_TABLE_URL": (
                self.feishu_profile_table_url_input.value
                if self.feishu_profile_table_url_input
                else ""
            ).strip(),
        }
        missing = validate_required_config(values)
        if missing:
            missing_labels = [FIELD_LABELS.get(key, key) for key in missing]
            self._show_snackbar(f"缺少必填配置: {', '.join(missing_labels)}")
            return

        if self.config_status_text:
            self.config_status_text.value = "正在检查..."
            self.config_status_text.color = ft.Colors.GREY_600
        self.page.update()

        async def _task() -> None:
            try:
                await asyncio.to_thread(self._check_feishu_connection_sync, values)
                result = "检查成功"
                color = self.SUCCESS_COLOR
            except Exception as exc:
                result = f"检查失败: {exc}"
                color = self.ERROR_COLOR
                self._add_log(f"检查失败: {exc}", "ERROR")

            if self.config_status_text:
                self.config_status_text.value = result
                self.config_status_text.color = color
            if self.page:
                self.page.update()

        self.page.run_task(_task)

    def _check_feishu_connection_sync(self, values: dict[str, str]) -> None:
        client = FeishuClient(
            app_id=values["FEISHU_APP_ID"],
            app_secret=values["FEISHU_APP_SECRET"],
            task_table_url=values["FEISHU_TABLE_URL"],
            profile_table_url=values["FEISHU_PROFILE_TABLE_URL"],
        )
        client.get_token()
        client.list_records(values["FEISHU_TABLE_URL"], page_size=1)
        client.list_records(values["FEISHU_PROFILE_TABLE_URL"], page_size=1)

    def _build_logs(self) -> ft.Container:
        content = ft.Column(
            expand=True,
            spacing=20,
        )

        header = ft.Row(
            [
                ft.Icon(ft.Icons.LIST_ALT_OUTLINED, size=28, color=self.PRIMARY_COLOR),
                ft.Text(
                    "系统日志",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=self.TEXT_PRIMARY,
                ),
                ft.Container(expand=True),
                ft.TextButton(
                    "导出日志",
                    on_click=lambda e: self._export_logs(),
                ),
                ft.IconButton(
                    icon=ft.Icon(ft.Icons.DELETE_SWEEP_OUTLINED),
                    icon_color=ft.Colors.GREY_500,
                    tooltip="清空日志",
                    on_click=lambda e: self._clear_logs(),
                ),
            ],
            spacing=12,
        )
        content.controls.append(header)

        self.log_list = ft.ListView(
            expand=True,
            spacing=4,
            auto_scroll=True,
        )

        self.log_empty_state = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.INBOX_OUTLINED, size=48, color=ft.Colors.GREY_300),
                    ft.Text(
                        "暂无日志",
                        size=14,
                        color=ft.Colors.GREY_500,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment(0, 0),
            expand=True,
            visible=True,
        )

        if self.log_history:
            self.log_list.controls.extend(
                self._parse_log_line(line) for line in self.log_history
            )
            self.log_empty_state.visible = False

        scroll_container = ft.Container(
            content=ft.Stack(
                [
                    self.log_list,
                    self.log_empty_state,
                ],
                expand=True,
                fit=ft.StackFit.EXPAND,
            ),
            expand=True,
            border_radius=12,
            bgcolor=ft.Colors.GREY_50,
            padding=12,
        )
        content.controls.append(scroll_container)

        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )

    def _on_nav_change(self, event: ft.Event[ft.NavigationRail]) -> None:
        if not self.content_area or not self.page:
            return

        nav = cast(ft.NavigationRail, event.control)
        index = nav.selected_index or 0
        self.content_area.controls.clear()

        if index == 0:
            self.content_area.controls.append(self._build_dashboard())
        elif index == 1:
            self.content_area.controls.append(self._build_settings())
        elif index == 2:
            self.content_area.controls.append(self._build_operation_settings())
        elif index == 3:
            self.content_area.controls.append(self._build_logs())

        self.page.update()

    def _update_status(self, running: bool, message: str = "") -> None:
        if self.status_dot and self.status_text:
            if running:
                self.status_dot.bgcolor = self.SUCCESS_COLOR
                self.status_text.value = message or "系统运行中"
                self.status_text.color = self.TEXT_PRIMARY
            else:
                self.status_dot.bgcolor = ft.Colors.GREY_400
                self.status_text.value = message or "系统已停止"
                self.status_text.color = ft.Colors.GREY_600
            if self.page:
                self.page.update()

    def _update_stats_display(self) -> None:
        if self.apply_count:
            self.apply_count.value = str(self.engine.apply_count)
        if self.welcome_count:
            self.welcome_count.value = str(self.engine.welcome_count)
        if self.fail_count:
            self.fail_count.value = str(self.engine.fail_count)

        if self.page:
            self.page.update()

        self._schedule_call(self._update_stats_display, 500)

    def _update_log_display(self) -> None:
        new_lines = self._drain_log_queue()
        if new_lines:
            self._append_log_history(new_lines)

        error_message: str | None = None
        for line in new_lines:
            log_level, content = self._split_log_line(line)
            if log_level in ("ERROR", "CRITICAL"):
                error_message = content

        if error_message:
            self._set_quick_error(error_message)

        if not self.log_list:
            self._schedule_call(self._update_log_display, 200)
            return

        for line in new_lines:
            log_control = self._parse_log_line(line)
            if not self.log_list.controls or len(self.log_list.controls) < 500:
                self.log_list.controls.append(log_control)
            else:
                self.log_list.controls.pop(0)
                self.log_list.controls.append(log_control)

        if self.log_empty_state:
            self.log_empty_state.visible = len(self.log_list.controls) == 0

        if new_lines and self.page:
            self.page.update()

        self._schedule_call(self._update_log_display, 200)

    def _drain_log_queue(self) -> list[str]:
        lines: list[str] = []
        try:
            while True:
                lines.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        return lines

    def _append_log_history(self, lines: list[str]) -> None:
        if not lines:
            return
        self.log_history.extend(lines)
        if len(self.log_history) > 500:
            self.log_history = self.log_history[-500:]

    def _split_log_line(self, line: str) -> tuple[str, str]:
        log_level = "INFO"
        content = line
        if "|" in line:
            parts = line.split("|")
            if len(parts) >= 2:
                log_level = parts[-2].strip().upper()
                content = parts[-1].strip()
        return log_level, content

    def _parse_log_line(self, line: str) -> ft.Container:
        log_level, content = self._split_log_line(line)

        bg_color = ft.Colors.BLUE_50
        text_color = ft.Colors.BLUE_900

        if log_level == "WARNING":
            bg_color = ft.Colors.AMBER_50
            text_color = ft.Colors.AMBER_900
        elif log_level in ("ERROR", "CRITICAL"):
            bg_color = ft.Colors.RED_50
            text_color = ft.Colors.RED_900
        elif log_level == "DEBUG":
            bg_color = ft.Colors.GREY_100
            text_color = ft.Colors.GREY_700

        icon = ft.Icons.INFO_OUTLINE
        if log_level == "WARNING":
            icon = ft.Icons.WARNING_AMBER_OUTLINED
        elif log_level in ("ERROR", "CRITICAL"):
            icon = ft.Icons.ERROR_OUTLINE
        elif log_level == "DEBUG":
            icon = ft.Icons.BUG_REPORT

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=16, color=text_color),
                    ft.Text(
                        content,
                        size=12,
                        color=text_color,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=8,
            border_radius=8,
            bgcolor=bg_color,
        )

    def _clear_logs(self) -> None:
        self.log_history = []
        self._drain_log_queue()
        if self.log_list:
            self.log_list.controls.clear()
            if self.log_empty_state:
                self.log_empty_state.visible = True
            if self.page:
                self.page.update()

    def _export_logs(self) -> None:
        new_lines = self._drain_log_queue()
        if new_lines:
            self._append_log_history(new_lines)

        if not self.log_history:
            self._show_snackbar("暂无日志可导出")
            return

        logs_dir = BASE_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = logs_dir / f"ui_logs_{timestamp}.txt"
        try:
            export_path.write_text("\n".join(self.log_history) + "\n", encoding="utf-8")
        except Exception as exc:
            self._show_snackbar(f"导出失败: {exc}")
            self._add_log(f"导出失败: {exc}", "ERROR")
            return

        self._show_snackbar(f"日志已导出: {export_path}")

    def _start_engine(self) -> None:
        if not self.is_running:
            try:
                cfg = get_config()
                missing = validate_required_config(cfg)
                if missing:
                    missing_labels = [FIELD_LABELS.get(key, key) for key in missing]
                    self._show_snackbar(f"缺少必填配置: {', '.join(missing_labels)}")
                    self._add_log(f"缺少必填配置: {', '.join(missing_labels)}", "ERROR")
                    return
                self.engine.start()
                self.is_running = True
                self._update_status(True, "系统运行中")
                self._clear_quick_error()
                self._add_log("系统已启动", "INFO")
            except Exception as e:
                self._add_log(f"启动失败: {e}", "ERROR")

    def _pause_engine(self) -> None:
        if not self.is_running:
            return

        if self.engine.is_paused():
            if self.engine.resume():
                self._add_log("监控已继续", "INFO")
        else:
            if self.engine.pause():
                self._add_log("监控已暂停", "WARNING")

    def _stop_engine(self) -> None:
        if self.is_running:
            self.engine.stop()
            self.is_running = False
            self._update_status(False, "系统已停止")
            self._add_log("系统已停止", "INFO")

    def _restart_program(self) -> None:
        try:
            if self.is_running:
                self.engine.stop()
                self.is_running = False
            self._show_snackbar("正在重启程序…")
            self._add_log("正在重启程序", "WARNING")
            executable = sys.executable
            argv = [executable, *sys.argv[1:]]
            os.execv(executable, argv)
        except Exception as exc:
            self._add_log(f"重启失败: {exc}", "ERROR")
            self._show_snackbar(f"重启失败: {exc}")

    def _run_self_check(self) -> None:
        if not self.page:
            return

        self._show_snackbar("正在自检，请稍候…")

        async def _task() -> None:
            errors: list[str] = []
            warnings: list[str] = []
            title = "自检完成"
            try:
                cfg = get_config()
                env_ok, errors, warnings = check_environment(cfg)
                if not env_ok:
                    title = "自检发现问题"
                else:
                    await asyncio.to_thread(run_self_check)
            except Exception as exc:
                title = "自检失败"
                errors = [str(exc)]
                self._add_log(f"自检失败: {exc}", "ERROR")

            self._show_self_check_dialog(title, errors, warnings)

        self.page.run_task(_task)

    def _set_quick_error(self, message: str | None) -> None:
        cleaned = message.strip() if message else ""
        self.quick_error_message = cleaned or None
        if self.quick_error_text:
            self.quick_error_text.value = self.quick_error_message or ""
        if self.quick_error_container:
            self.quick_error_container.visible = bool(self.quick_error_message)
        if self.page:
            self.page.update()

    def _clear_quick_error(self) -> None:
        self._set_quick_error(None)

    def _add_log(self, message: str, level: str = "INFO") -> None:
        if level in ("ERROR", "CRITICAL"):
            self._set_quick_error(message)
        self._append_log_history([f"{level} | {message}"])
        if self.log_list:
            log_control = self._parse_log_line(f"{level} | {message}")
            self.log_list.controls.append(log_control)
            if self.log_empty_state:
                self.log_empty_state.visible = False
            if self.page:
                self.page.update()

    def _apply_monitor_interval(self) -> None:
        try:
            if self.monitor_interval_input:
                value = float(self.monitor_interval_input.value)
                if 5 <= value <= 300:
                    self.engine.set_monitor_interval(value)
                    value_str = str(int(value))
                    cfg = update_config(
                        {"NEW_FRIEND_SCAN_INTERVAL": value_str}, persist=True
                    )
                    self.engine.cfg = cfg
                    self.monitor_interval_input.value = value_str
                    self._show_snackbar("监控频率已更新")
                    self._add_log(f"监控频率已更新: {value}秒", "INFO")
                else:
                    self._show_snackbar("请输入 5-300 之间的数值")
        except ValueError:
            self._show_snackbar("请输入有效的数字")

    def _apply_feishu_poll(self) -> None:
        try:
            if self.feishu_poll_input:
                value = float(self.feishu_poll_input.value)
                if 3 <= value <= 60:
                    self.engine.set_feishu_poll_interval(value)
                    value_str = str(int(value))
                    cfg = update_config(
                        {"FEISHU_POLL_INTERVAL": value_str}, persist=True
                    )
                    self.engine.cfg = cfg
                    self.feishu_poll_input.value = value_str
                    self._show_snackbar("飞书轮询频率已更新")
                    self._add_log(f"飞书轮询频率已更新: {value}秒", "INFO")
                else:
                    self._show_snackbar("请输入 3-60 之间的数值")
        except ValueError:
            self._show_snackbar("请输入有效的数字")

    def _apply_jitter(self) -> None:
        try:
            if self.jitter_input:
                value = float(self.jitter_input.value)
                if 0 <= value <= 30:
                    self.engine.set_jitter(value)
                    value_str = str(int(value))
                    cfg = update_config(
                        {"PASSIVE_SCAN_JITTER": value_str}, persist=True
                    )
                    self.engine.cfg = cfg
                    self.jitter_input.value = value_str
                    self._show_snackbar("扫描抖动已更新")
                    self._add_log(f"扫描抖动已更新: {value}秒", "INFO")
                else:
                    self._show_snackbar("请输入 0-30 之间的数值")
        except ValueError:
            self._show_snackbar("请输入有效的数字")

    def _toggle_welcome(self, event: ft.ControlEvent) -> None:
        control = cast(ft.Switch, event.control)
        enabled = bool(control.value)
        self.engine.toggle_welcome(enabled)
        self.welcome_enabled = enabled
        cfg = update_config({"WELCOME_ENABLED": "1" if enabled else "0"}, persist=True)
        self.engine.cfg = cfg
        self._show_snackbar(f"欢迎包功能已{'启用' if enabled else '禁用'}")
        self._add_log(f"欢迎包功能已{'启用' if enabled else '禁用'}", "INFO")

    def _show_snackbar(self, message: str) -> None:
        if self.page:
            snack_bar = ft.SnackBar(
                ft.Text(message),
                bgcolor=self.TEXT_PRIMARY,
            )
            setattr(self.page, "snack_bar", snack_bar)
            snack_bar.open = True
            self.page.update()

    def _show_self_check_dialog(
        self, title: str, errors: list[str], warnings: list[str]
    ) -> None:
        if not self.page:
            return

        content = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO)

        if not errors and not warnings:
            content.controls.append(
                ft.Text("自检完成，未发现问题。", size=12, color=ft.Colors.GREY_700)
            )

        if errors:
            content.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "错误",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.RED_700,
                            ),
                            ft.Column(
                                [ft.Text(f"- {item}", size=12) for item in errors],
                                spacing=6,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=12,
                    border_radius=10,
                    bgcolor=ft.Colors.RED_50,
                )
            )

        if warnings:
            content.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "提示",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.AMBER_700,
                            ),
                            ft.Column(
                                [ft.Text(f"- {item}", size=12) for item in warnings],
                                spacing=6,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=12,
                    border_radius=10,
                    bgcolor=ft.Colors.AMBER_50,
                )
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=title,
            content=content,
            actions=[
                ft.TextButton("关闭", on_click=lambda e: self._close_dialog(dialog))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        dialog.open = True
        self.page.show_dialog(dialog)
        self.page.update()

    def run(self) -> None:
        ft.app(target=self.build)
        self._cleanup()

    def _cleanup(self) -> None:
        self.engine.stop()
        try:
            logger.remove(self._log_sink_id)
        except Exception:
            pass
