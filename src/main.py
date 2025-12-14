from __future__ import annotations

import time

from loguru import logger

from src.config.logger import setup_logger
from src.config.settings import get_config
from src.core.engine import TaskEngine
from src.core.system import check_environment, configure_dpi_awareness, run_self_check
from src.ui.console import ConsoleApp


def main() -> None:
    setup_logger()
    configure_dpi_awareness()

    cfg = get_config()
    env_ok, errors, warnings = check_environment(cfg)
    for warn in warnings:
        logger.warning("环境自检提示：{}", warn)
    if not env_ok:
        ConsoleApp.show_env_error(errors)
        raise RuntimeError("环境检测失败")

    run_self_check()

    engine = TaskEngine(cfg)
    app = ConsoleApp(engine)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.critical(f"程序崩溃退出: {exc}")
        time.sleep(5)
        raise
