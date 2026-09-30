"""统一日志配置。

约定：各业务模块只使用 logger = logging.getLogger(__name__)，
不自行调用 logging.basicConfig；日志在入口（run.py / android.py /
diagnose_dead_device.py）调用 setup_logging() 统一配置。
pytest 运行时则由 pytest.ini 的 log_cli_* 选项管理输出。
"""
import logging
import os
import sys

_CONFIGURED = False

DEFAULT_FORMAT = '%(asctime)s %(levelname)-7s %(name)s: %(message)s'
DEFAULT_DATEFMT = '%H:%M:%S'


def setup_logging(level=logging.INFO, log_file=None, fmt=DEFAULT_FORMAT):
    """配置根 logger（幂等，重复调用不会叠加 handler）。

    :param level: 日志级别
    :param log_file: 可选，额外把日志写入该文件
    :param fmt: 日志格式
    """
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level)

    if not _CONFIGURED:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(fmt, DEFAULT_DATEFMT))
        root.addHandler(console)
        _CONFIGURED = True

    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(fmt, DEFAULT_DATEFMT))
        root.addHandler(file_handler)
