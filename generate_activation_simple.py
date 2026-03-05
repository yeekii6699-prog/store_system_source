#!/usr/bin/env python3
"""
使用现有字段名的激活码管理工具
"""

from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from src.config.settings import get_config
from src.services.feishu import FeishuClient


def generate_activation_code(length: int = 16) -> str:
    """生成随机激活码，格式：XXXX-XXXX-XXXX-XXXX"""
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(length))
    return "-".join(code[i : i + 4] for i in range(0, length, 4))


def main():
    parser = argparse.ArgumentParser(description="使用现有字段生成激活码")
    parser.add_argument("--count", type=int, default=5, help="生成数量")
    parser.add_argument("--validity-days", type=int, default=30, help="有效期（天）")
    parser.add_argument("--customer-name", type=str, help="客户名称")
    parser.add_argument("--remark", type=str, help="备注")

    args = parser.parse_args()

    logger.info(f"开始生成激活码，数量: {args.count}, 有效期: {args.validity_days}天")

    try:
        cfg = get_config()
        activation_table_url = cfg.get("ACTIVATION_TABLE_URL")

        if not activation_table_url:
            logger.error("未配置 ACTIVATION_TABLE_URL")
            return 1

        client = FeishuClient()

        # 原始URL用于显示
        original_url = None
        if hasattr(client, "activation_table_url") and client.activation_table_url:
            original_url = client.activation_table_url
        client.activation_table_url = client._normalize_table_url(activation_table_url)

        codes = []
        for i in range(args.count):
            code = generate_activation_code()
            codes.append(code)

            try:
                # 使用现有字段：姓名 字段存储激活码
                fields = {
                    "姓名": code,  # 使用姓名字段存储激活码
                    "状态": "未使用",  # 状态字段：未使用/已绑定/已过期
                }

                # 如果有时间处理字段，用它来存储有效期
                # fields["时间处理"] = args.validity_days

                if args.customer_name:
                    fields["备注"] = f"客户: {args.customer_name}"

                if args.remark:
                    existing_remark = fields.get("备注", "")
                    fields["备注"] = (
                        f"{existing_remark}; {args.remark}"
                        if existing_remark
                        else args.remark
                    )

                record_id = client.create_record(fields)
                logger.info(f"[{i + 1}/{args.count}] 创建激活码: {code} -> {record_id}")

            except Exception as e:
                logger.error(f"[{i + 1}/{args.count}] 创建激活码失败: {code} -> {e}")

        logger.info(f"成功生成 {len([c for c in codes if True])} 个激活码")
        print(f"\n生成的激活码:")
        for code in codes:
            print(f"  {code}")

        # 恢复原始URL
        if original_url:
            client.activation_table_url = original_url

    except Exception as e:
        logger.error(f"生成激活码失败: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
