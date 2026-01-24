from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import sys

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import BASE_DIR, get_config
from src.services.feishu import FeishuClient


def _fetch_table_schema(client: FeishuClient, table_url: str, label: str) -> Dict[str, Any]:
    fields = client.list_fields(table_url)
    formatted_fields: List[Dict[str, Any]] = []
    for field in fields:
        formatted_fields.append(
            {
                "field_id": field.get("field_id"),
                "field_name": field.get("field_name"),
                "type": field.get("type"),
                "is_primary": field.get("is_primary"),
                "property": field.get("property"),
                "description": field.get("description"),
            }
        )
    return {
        "label": label,
        "table_url": table_url,
        "field_count": len(formatted_fields),
        "fields": formatted_fields,
    }


def main() -> None:
    cfg = get_config()
    profile_url = (cfg.get("FEISHU_PROFILE_TABLE_URL") or "").strip()
    task_url = (cfg.get("FEISHU_TABLE_URL") or "").strip()

    if not profile_url or not task_url:
        logger.error("Missing FEISHU_PROFILE_TABLE_URL or FEISHU_TABLE_URL in config.ini/.env")
        return

    client = FeishuClient(
        app_id=cfg.get("FEISHU_APP_ID"),
        app_secret=cfg.get("FEISHU_APP_SECRET"),
        task_table_url=task_url,
        profile_table_url=profile_url,
    )

    schema = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tables": [
            _fetch_table_schema(client, profile_url, "profile_table"),
            _fetch_table_schema(client, task_url, "appointment_table"),
        ],
    }

    output_dir = BASE_DIR / "dev_debug"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"feishu_table_schema_{timestamp}.json"
    output_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Schema exported: {}", output_path)


if __name__ == "__main__":
    main()
