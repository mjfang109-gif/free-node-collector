"""日志配置模块。"""

import logging
from pathlib import Path


def setup_logger():
    """设置项目日志。"""
    project_root = Path(__file__).parent.parent.resolve()
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    # 创建日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s")
    console_handler.setFormatter(console_formatter)

    # 文件处理器
    file_handler = logging.FileHandler(logs_dir / "app.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(asctime)s - [%(levelname)s] - %(name)s - (%(filename)s:%(lineno)d) - %(message)s")
    file_handler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
