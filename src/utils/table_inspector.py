"""
辅助脚本：动态查看飞书多维表格的字段列表与部分数据样例。
执行后会打印任务表和客户表的字段信息及前几条记录，方便映射字段名，无需改动主业务代码。
"""

from __future__ import annotations

from pprint import pprint

from loguru import logger

from src.config.settings import get_config
from src.services.feishu import FeishuClient


def print_table_info(title: str, table_url: str, sample_size: int = 5) -> None:
    """
    拉取字段列表与样例数据并打印。
    """
    client = FeishuClient()
    fields = client.list_fields(table_url)
    records = client.list_records(table_url, page_size=sample_size)

    logger.info("====== {} ======", title)
    logger.info("表 URL: {}", table_url)
    logger.info("字段列表（name -> type）:")
    for f in fields:
        logger.info("- {} -> {}", f.get("field_name"), f.get("type"))

    logger.info("样例记录（前 {} 条）:", sample_size)
    for idx, rec in enumerate(records, start=1):
        logger.info("记录 {}:", idx)
        pprint(rec.get("fields", {}))


def main() -> None:
    """
    查看任务表与客户表字段/样例。
    """
    cfg = get_config()
    print_table_info("任务表（待办/处理状态表）", cfg["FEISHU_TABLE_URL"])
    print_table_info("客户表（资料表）", cfg["FEISHU_PROFILE_TABLE_URL"])


if __name__ == "__main__":
    main()
