from __future__ import annotations

import time
import traceback

from loguru import logger

from src.config.logger import setup_logger
from src.config.settings import get_config
from src.core.engine import TaskEngine
from src.core.system import configure_dpi_awareness
from src.ui.flet_error import show_error_page


def main() -> None:
    setup_logger()
    configure_dpi_awareness()

    cfg = get_config()
    try:
        engine = TaskEngine(cfg)

        from src.ui.flet_app import FletApp
        app = FletApp(engine)
        app.run()
    except Exception as exc:
        logger.critical(f"程序崩溃退出: {exc}")
        logger.critical(f"详细错误:\n{traceback.format_exc()}")
        show_error_page("启动失败", [str(exc)])
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
