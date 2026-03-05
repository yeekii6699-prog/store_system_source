from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta

from src.config.settings import get_config
from src.services.followup import (
    FollowupCandidate,
    FollowupMessageResult,
    LLMClient,
    build_snapshot_hash,
    evaluate_candidate,
    load_followup_runtime_config,
)


def _mock_candidate(index: int) -> FollowupCandidate:
    now = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
    return FollowupCandidate(
        record_id=f"mock_{index}",
        wechat_id=f"wx_mock_{index}",
        nickname=f"客户{index}",
        phone="13800000000",
        last_visit_at=now - timedelta(days=8 + index),
        last_consume_at=now - timedelta(days=2),
        last_consume_summary="到店护理项目",
        last_followup_at=None,
        followup_status="待回访",
        followup_snapshot_hash="",
        followup_attempts=0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="自动回访 smoke 验证脚本")
    parser.add_argument("--dry-run", action="store_true", help="仅验证流程不发送")
    parser.add_argument("--limit", type=int, default=2, help="处理条数")
    parser.add_argument("--mock-llm", action="store_true", help="使用模拟LLM结果")
    parser.add_argument(
        "--mock-wechat-fail", action="store_true", help="模拟微信发送失败"
    )
    args = parser.parse_args()

    cfg = get_config()
    runtime_cfg = load_followup_runtime_config(cfg)
    runtime_cfg.dry_run = runtime_cfg.dry_run or args.dry_run

    llm = LLMClient(runtime_cfg)
    sent_count = 0
    skip_count = 0
    fail_count = 0
    results: list[dict[str, str | bool]] = []

    now = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
    for i in range(max(1, args.limit)):
        candidate = _mock_candidate(i)
        snapshot = build_snapshot_hash(candidate, runtime_cfg.prompt_version)
        decision = evaluate_candidate(
            candidate,
            runtime_cfg,
            now,
            hour_sent_count=0,
            day_sent_count=0,
        )

        if decision.decision == "skip":
            skip_count += 1
            results.append(
                {
                    "record_id": candidate.record_id,
                    "result": "skip",
                    "reason_code": decision.reason_code,
                    "snapshot": snapshot,
                }
            )
            continue

        if args.mock_llm:
            compose = FollowupMessageResult(
                text=f"{candidate.nickname}，您好！感谢您近期到店，想确认您的体验是否满意，欢迎回复我为您安排更适合的服务。",
                fallback_used=False,
                reason_code="mock_llm",
                reason_detail="mock_llm",
            )
        else:
            compose = llm.compose(candidate)

        if runtime_cfg.dry_run:
            skip_count += 1
            results.append(
                {
                    "record_id": candidate.record_id,
                    "result": "skip",
                    "reason_code": "dry_run",
                    "fallback_used": compose.fallback_used,
                    "snapshot": snapshot,
                }
            )
            continue

        if args.mock_wechat_fail:
            fail_count += 1
            results.append(
                {
                    "record_id": candidate.record_id,
                    "result": "fail",
                    "reason_code": "wechat_send_failed",
                    "fallback_used": compose.fallback_used,
                    "snapshot": snapshot,
                }
            )
            continue

        sent_count += 1
        results.append(
            {
                "record_id": candidate.record_id,
                "result": "sent",
                "reason_code": compose.reason_code,
                "fallback_used": compose.fallback_used,
                "snapshot": snapshot,
            }
        )

    print(
        json.dumps(
            {
                "sent_count": sent_count,
                "skip_count": skip_count,
                "fail_count": fail_count,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
