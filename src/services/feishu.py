"""
飞书相关接口封装，统一管理 token 获取、表格数据查询与更新。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from loguru import logger

from src.config.settings import get_config


class FeishuClient:
    """
    封装飞书多维表格 API 的常用操作。
    FEISHU_TABLE_URL 与 FEISHU_PROFILE_TABLE_URL 需填记录接口地址:
    https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
    """

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        task_table_url: str | None = None,
        profile_table_url: str | None = None,
    ) -> None:
        # 先初始化 token 相关字段，避免后续 normalize 过程中调用 get_token 时未定义
        self._tenant_access_token: str | None = None
        self._token_expire_at: float = 0.0

        cfg = get_config()
        self.app_id = app_id or cfg["FEISHU_APP_ID"]
        self.app_secret = app_secret or cfg["FEISHU_APP_SECRET"]
        self._wiki_token_cache: Dict[str, str] = {}
        task_url = task_table_url or cfg["FEISHU_TABLE_URL"]
        profile_url = profile_table_url or cfg["FEISHU_PROFILE_TABLE_URL"]
        self.task_table_url = self._normalize_table_url(task_url)
        self.profile_table_url = self._normalize_table_url(profile_url)
        self.profile_field_phone = cfg.get("FEISHU_FIELD_PHONE", "") or "手机号"
        self.profile_field_name = cfg.get("FEISHU_FIELD_NAME", "") or "姓名"
        self.profile_field_remark = cfg.get("FEISHU_FIELD_REMARK", "") or "微信备注"

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
    def _normalize_table_url(self, table_url: str) -> str:
        """
        支持正常 Bitable API URL 也支持 Wiki 链接。
        - 如果链接来自 Wiki (/wiki/<token>?table=tblxxx)，先换算为 Base obj_token
        - 最终输出格式: https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
        """
        parsed = urlparse(table_url)
        parts = [p for p in parsed.path.split("/") if p]

        # Wiki 链接：需要先通过 API 换索引 token
        if "wiki" in parts:
            wiki_index = parts.index("wiki")
            if wiki_index + 1 >= len(parts):
                raise ValueError("Wiki 链接缺少 token")
            wiki_token = parts[wiki_index + 1]
            table_id = self._extract_table_id(parsed)
            base_token = self._resolve_wiki_token(wiki_token)
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records"
            logger.debug("Wiki 链接已换算为表格: wiki_token={} -> base_token={}", wiki_token, base_token)
            return url.rstrip("/")

        # 正常 API 路径：直接解析 app_token 和 table_id 再重构
        if "apps" in parts and "tables" in parts:
            app_token, table_id = self._parse_table_info_from_api_path(parts)
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
            return url.rstrip("/")

        raise ValueError("不支持的表格链接格式，请使用 Bitable 或 Wiki 链接")

    def _extract_table_id(self, parsed_url) -> str:
        query = {k.lower(): v for k, v in parse_qs(parsed_url.query).items()}
        for key in ("table", "table_id", "tableid"):
            if key in query and query[key]:
                return query[key][0]
        raise ValueError("没有从 URL 参数中找到 table_id，请检查链接的 table= 参数")

    def _parse_table_info_from_api_path(self, parts: List[str]) -> Tuple[str, str]:
        if "apps" not in parts or "tables" not in parts:
            raise ValueError("表格 URL 格式异常，缺少 apps/tables 段")
        app_token = parts[parts.index("apps") + 1]
        table_id = parts[parts.index("tables") + 1]
        if not app_token or not table_id:
            raise ValueError("无法从表格 URL 解析 app_token 或 table_id")
        return app_token, table_id

    def _parse_table_info(self, table_url: str) -> Tuple[str, str]:
        """
        从表格链接提取 app_token 和 table_id，无论是 API 链接还是 Wiki 链接。
        """
        normalized = self._normalize_table_url(table_url)
        parts = [p for p in urlparse(normalized).path.split("/") if p]
        return self._parse_table_info_from_api_path(parts)

    def _resolve_wiki_token(self, wiki_token: str) -> str:
        """
        通过 Wiki token 获取其对应的 Bitable obj_token（Base token）。
        结果会缓存，防止重复请求。
        """
        if wiki_token in self._wiki_token_cache:
            return self._wiki_token_cache[wiki_token]

        url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
        params = {"obj_type": "wiki", "token": wiki_token}
        data = self._request("GET", url, params=params)
        obj_token = data.get("data", {}).get("node", {}).get("obj_token")
        if not obj_token:
            raise RuntimeError(f"无法将 Wiki token 换算为 Base token：{data}")

        self._wiki_token_cache[wiki_token] = obj_token
        return obj_token

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
        normalized = self._normalize_table_url(table_url)
        data = self._request("GET", normalized, params=params)
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
        return self.fetch_tasks_by_status(["待添加"])

    def fetch_tasks_by_status(self, statuses: List[str]) -> List[Dict[str, Any]]:
        values = [status for status in statuses if status]
        if not values:
            return []
        payload = {
            "filter": {
                "conditions": [
                    {
                        "field_name": "微信绑定状态",
                        "operator": "is",
                        "value": values,
                    }
                ],
                "conjunction": "and",
            }
        }
        logger.debug("按状态拉取任务，payload={}", payload)
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

    def update_status(self, record_id: str, status: str) -> None:
        """
        通用状态更新入口，便于双队列流程设置“已申请”“已绑定”等值。
        """
        url = f"{self.profile_table_url}/{record_id}"
        payload = {"fields": {"微信绑定状态": status}}
        logger.debug("更新记录 {} 状态 -> {}", record_id, status)
        self._request("PUT", url, json=payload)

    # ========================= 被动写入资料 =========================
    def _find_profile_by_phone(self, phone: str) -> str | None:
        """按手机号搜索客户表，返回 record_id（若存在）。"""
        payload = {
            "filter": {
                "conditions": [
                    {
                        "field_name": self.profile_field_phone,
                        "operator": "is",
                        "value": [phone],
                    }
                ],
                "conjunction": "and",
            }
        }
        data = self._request("POST", self.profile_table_url + "/search", json=payload)
        items: List[Dict[str, Any]] = data.get("data", {}).get("items", [])
        if not items:
            return None
        record = items[0]
        return record.get("record_id") or record.get("recordId")

    def upsert_contact_profile(self, phone: str, name: str | None = None, remark: str | None = None) -> str:
        """
        将微信号写入“手机号”字段，若已存在则更新姓名/备注，否则创建记录。
        返回记录 ID（存在或新建）。
        """
        phone = (phone or "").strip()
        if not phone:
            raise ValueError("phone is required for upsert_contact_profile")

        fields: Dict[str, Any] = {self.profile_field_phone: phone}
        if name:
            fields[self.profile_field_name] = name
        if remark:
            fields[self.profile_field_remark] = remark

        record_id = self._find_profile_by_phone(phone)
        if record_id:
            url = f"{self.profile_table_url}/{record_id}"
            logger.debug("被动写入：更新已有记录 {} -> {}", record_id, fields)
            self._request("PUT", url, json={"fields": fields})
            return record_id

        logger.debug("被动写入：新增记录 -> {}", fields)
        data = self._request("POST", self.profile_table_url, json={"fields": fields})
        return (
            data.get("data", {})
            .get("record", {})
            .get("record_id")
            or data.get("data", {})
            .get("record", {})
            .get("recordId", "")
        )
