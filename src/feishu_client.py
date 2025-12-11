"""
飞书相关接口封装，统一管理 token 获取、表格数据查询与更新。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import requests
from loguru import logger

from config import (
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_PROFILE_TABLE_URL,
    FEISHU_TABLE_URL,
)


class FeishuClient:
    """
    封装飞书多维表格 API 的常用操作。
    FEISHU_TABLE_URL 与 FEISHU_PROFILE_TABLE_URL 需填记录接口地址:
    https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
    """

    def __init__(
        self,
        app_id: str = FEISHU_APP_ID,
        app_secret: str = FEISHU_APP_SECRET,
        task_table_url: str = FEISHU_TABLE_URL,
        profile_table_url: str = FEISHU_PROFILE_TABLE_URL,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.task_table_url = task_table_url.rstrip("/")
        self.profile_table_url = profile_table_url.rstrip("/")
        self._tenant_access_token: str | None = None
        self._token_expire_at: float = 0.0

    # ========================= 基础请求 =========================
    def get_token(self) -> str:
        """
        获取租户 token，自动刷新并缓存，避免频繁请求。
        """
        now = time.time()
        if self._tenant_access_token and now < self._token_expire_at - 60:
            return self._tenant_access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

        token = data["tenant_access_token"]
        expire = int(data.get("expire", 0))
        self._tenant_access_token = token
        self._token_expire_at = now + expire
        logger.debug("刷新飞书 tenant_access_token 成功，过期时间 {}", self._token_expire_at)
        return token

    def _headers(self) -> Dict[str, str]:
        token = self.get_token()
        return {"Authorization": f"Bearer {token}"}

    def _request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        """
        简化请求发送与错误检查，出现 HTTPError 时打印响应体便于排障。
        """
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        try:
            resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)
            resp.raise_for_status()
        except requests.HTTPError as http_err:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            logger.error("飞书 HTTP 错误: {} | 响应: {}", http_err, str(body)[:500])
            raise

        data = resp.json()
        if data.get("code") not in (0, None):
            raise RuntimeError(
                f"飞书接口返回异常 code={data.get('code')} msg={data.get('msg')} data={data}"
            )
        return data

    # ========================= 辅助工具 =========================
    def _parse_table_info(self, table_url: str) -> Tuple[str, str]:
        """
        从记录接口 URL 中提取 app_token 与 table_id。
        期望格式: .../apps/{app_token}/tables/{table_id}/records
        """
        from urllib.parse import urlparse

        parts = [p for p in urlparse(table_url).path.split("/") if p]
        if "apps" not in parts or "tables" not in parts:
            raise ValueError("表格 URL 格式异常，缺少 apps/tables 段")
        app_token = parts[parts.index("apps") + 1]
        table_id = parts[parts.index("tables") + 1]
        if not app_token or not table_id:
            raise ValueError("无法从表格 URL 解析 app_token 或 table_id")
        return app_token, table_id

    def list_fields(self, table_url: str) -> List[Dict[str, Any]]:
        """
        获取表格字段列表，便于调试。
        """
        app_token, table_id = self._parse_table_info(table_url)
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        data = self._request("GET", url)
        return data.get("data", {}).get("items", [])

    def list_records(self, table_url: str, page_size: int = 5) -> List[Dict[str, Any]]:
        params = {"page_size": page_size}
        data = self._request("GET", table_url, params=params)
        return data.get("data", {}).get("items", [])

    # ========================= 业务方法 =========================
    def search_customer(self, phone: str) -> Tuple[bool, str, str]:
        """
        在客户表按手机号查询，返回 (是否存在, 状态, 姓名)。
        """
        if not isinstance(phone, str):
            phone = str(phone)

        payload = {
            "filter": {
                "conditions": [
                    {
                        "field_name": "手机号",
                        "operator": "is",
                        "value": [phone],
                    }
                ],
                "conjunction": "and",
            }
        }
        url = self.profile_table_url
        logger.debug("查询客户手机号: {}", phone)
        data = self._request("POST", url + "/search", json=payload)
        items: List[Dict[str, Any]] = data.get("data", {}).get("items", [])
        if not items:
            return False, "", ""

        record = items[0].get("fields", {})
        status = record.get("微信绑定状态", "")
        name = record.get("姓名", "")
        return True, status, name

    def fetch_new_tasks(self) -> List[Dict[str, Any]]:
        """
        获取客户表中“微信绑定状态”为“待添加”的记录，作为待处理任务。
        """
        payload = {
            "filter": {
                "conditions": [
                    {
                        "field_name": "微信绑定状态",
                        "operator": "is",
                        "value": ["待添加"],
                    }
                ],
                "conjunction": "and",
            }
        }
        logger.debug("拉取待处理任务，payload={}", payload)
        data = self._request("POST", self.profile_table_url + "/search", json=payload)
        return data.get("data", {}).get("items", [])

    def mark_processed(self, record_id: str) -> None:
        """
        将客户表记录标记为“已添加”，避免重复处理。
        """
        url = f"{self.profile_table_url}/{record_id}"
        payload = {"fields": {"微信绑定状态": "已添加"}}
        logger.debug("标记任务已处理(已添加): {}", record_id)
        self._request("PUT", url, json=payload)

    def mark_failed(self, record_id: str) -> None:
        """
        将客户表记录标记为“添加失败”，方便后续人工处理。
        """
        url = f"{self.profile_table_url}/{record_id}"
        payload = {"fields": {"微信绑定状态": "添加失败"}}
        logger.debug("标记任务添加失败: {}", record_id)
        self._request("PUT", url, json=payload)
