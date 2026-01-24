from __future__ import annotations

from typing import Any, Iterable, cast

import flet as ft


def _format_lines(lines: Iterable[str]) -> list[ft.Control]:
    return [ft.Text(f"- {line}", size=12, color=ft.Colors.GREY_800) for line in lines]


def show_error_page(
    title: str, errors: list[str], warnings: list[str] | None = None
) -> None:
    def _build(page: ft.Page) -> None:
        page.title = title
        page.theme_mode = ft.ThemeMode.LIGHT
        cast(Any, page).window_width = 900
        cast(Any, page).window_height = 600
        page.bgcolor = ft.Colors.GREY_50
        page.padding = 24

        content = ft.Column(expand=True, spacing=16, scroll=ft.ScrollMode.AUTO)

        content.controls.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.ERROR_OUTLINE, size=28, color=ft.Colors.RED_500
                        ),
                        ft.Text(
                            title,
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREY_900,
                        ),
                    ],
                    spacing=12,
                ),
                padding=16,
                border_radius=14,
                bgcolor=ft.Colors.WHITE,
            )
        )

        if errors:
            content.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "错误详情",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.RED_700,
                            ),
                            ft.Column(_format_lines(errors), spacing=6),
                        ],
                        spacing=8,
                    ),
                    padding=16,
                    border_radius=14,
                    bgcolor=ft.Colors.RED_50,
                )
            )

        if warnings:
            content.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "提示信息",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.AMBER_700,
                            ),
                            ft.Column(_format_lines(warnings), spacing=6),
                        ],
                        spacing=8,
                    ),
                    padding=16,
                    border_radius=14,
                    bgcolor=ft.Colors.AMBER_50,
                )
            )

        content.controls.append(
            ft.Container(
                content=ft.Text(
                    "请修复配置后重新启动。",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                padding=12,
            )
        )

        page.add(content)

    ft.app(target=_build)
