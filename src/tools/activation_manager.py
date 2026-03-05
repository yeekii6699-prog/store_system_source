#!/usr/bin/env python3
"""激活码管理工具。"""

import argparse
import sys
from datetime import datetime

from loguru import logger

from src.services.activation import (
    create_activation_feishu_client,
    generate_activation_code as core_generate_activation_code,
)


def setup_logger() -> None:
    """配置日志"""
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(stdout_reconfigure):
        stdout_reconfigure(encoding="utf-8", errors="replace")

    logger.remove()
    logger.add(sys.stdout, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
    logger.add(
        f"activation_manager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
        rotation="1 day",
        retention="7 days",
    )


def generate_activation_code(length: int = 16) -> str:
    """生成随机激活码，格式：XXXX-XXXX-XXXX-XXXX。"""
    return core_generate_activation_code(length)


def batch_create_codes(
    count: int,
    validity_days: int,
    table_url: str | None = None,
    customer_name: str | None = None,
    remark: str | None = None,
) -> list[str]:
    """批量生成激活码"""
    client = create_activation_feishu_client()
    activation_table_url = (table_url or client.activation_table_url or "").strip()
    if not activation_table_url:
        raise ValueError(
            "未配置激活码表 URL，请设置 ACTIVATION_TABLE_URL 或 --table-url"
        )

    codes = []
    for i in range(count):
        code = generate_activation_code()
        codes.append(code)

        try:
            fields = {"激活码": code, "时长（天）": validity_days, "状态": "未使用"}

            if customer_name:
                fields["客户名称"] = customer_name

            if remark:
                fields["备注"] = remark

            data = client._request(
                "POST", activation_table_url, json={"fields": fields}
            )
            record = data.get("data", {}).get("record", {})
            record_id = client._extract_record_id(record)
            logger.info(f"[{i + 1}/{count}] 创建激活码: {code} -> {record_id}")

        except Exception as e:
            logger.error(f"[{i + 1}/{count}] 创建激活码失败: {code} -> {e}")

    return codes


def main() -> None:
    """主函数"""
    parser = argparse.ArgumentParser(
        description="激活码管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.tools.activation_manager --count 10 --validity-days 365
  python -m src.tools.activation_manager generate --count 5 --validity-days 30 --customer-name "测试客户"
        """,
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="generate",
        choices=["generate"],
        help="可用命令（默认 generate）",
    )
    parser.add_argument("--count", "-c", type=int, default=10, help="生成数量")
    parser.add_argument(
        "--validity-days", "-d", type=int, default=365, help="有效期天数"
    )
    parser.add_argument(
        "--table-url",
        "-t",
        type=str,
        default=None,
        help="激活码表 URL（可选，默认读取配置）",
    )
    parser.add_argument(
        "--customer-name", "-n", type=str, default=None, help="客户名称"
    )
    parser.add_argument("--remark", "-r", type=str, default=None, help="备注")

    args = parser.parse_args()

    setup_logger()

    if args.command == "generate":
        logger.info(
            f"开始生成激活码，数量: {args.count}, 有效期: {args.validity_days}天"
        )
        codes = batch_create_codes(
            count=args.count,
            validity_days=args.validity_days,
            table_url=args.table_url,
            customer_name=args.customer_name,
            remark=args.remark,
        )
        logger.info(f"成功生成 {len(codes)} 个激活码")
        print("\n生成的激活码:")
        for code in codes:
            print(f"  {code}")


if __name__ == "__main__":
    main()
