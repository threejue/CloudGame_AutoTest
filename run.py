import logging
import os
import sys
from datetime import datetime

import pytest
import yaml

from core.log_setup import setup_logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    with open(os.path.join(BASE_DIR, 'config', 'settings.yaml'),
              'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 1. 每次运行创建独立的时间戳报告目录，产物互不覆盖
    report_dir = os.path.join(
        BASE_DIR, 'reports', f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(report_dir, exist_ok=True)
    # 通过环境变量告知用例（test_health）与工具（boot_analyzer）报告目录
    os.environ['CLOUDGAME_REPORT_DIR'] = report_dir

    setup_logging(log_file=os.path.join(report_dir, 'run.log'))
    logger.info("=" * 50)
    logger.info("云游戏终端自动化测试框架启动... (platform=%s)", config.get('platform'))
    logger.info("本次报告目录: %s", report_dir)
    logger.info("=" * 50)

    # 2. 运行 Pytest 测试
    # -s: 允许实时输出; -v: 详细日志
    # -m "not manual and not integration":
    #   排除需人工介入的用例（拔插电源）和需真机的集成测试（网络 ADB 设备）
    exit_code = pytest.main(["-s", "-v", "-m", "not manual and not integration",
                             "test_cases/"])

    # 3. 只要采集到内存 CSV 就绘制趋势图（与测试是否全部通过无关：
    #    即使内存阈值用例失败，也能产出图表用于排查低内存问题）
    from utils.plotter import draw_memory_chart

    csv_path = os.path.join(report_dir, config['paths']['log_csv'])
    img_path = os.path.join(report_dir, config['paths']['chart_png'])

    if os.path.exists(csv_path):
        logger.info("正在生成内存趋势图...")
        draw_memory_chart(csv_path, img_path,
                          min_free_kb=config['thresholds']['min_free_memory_kb'])
    else:
        logger.warning("未找到设备内存日志（%s），跳过图表生成。", csv_path)

    logger.info("自动化测试执行完毕，产物见: %s", report_dir)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
