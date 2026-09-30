import argparse
import logging
import os
import sys
from datetime import datetime

import pytest
import yaml

from core.log_setup import setup_logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 平台 -> pytest 目标路径
_PLATFORM_TARGETS = {
    'linux': 'test_cases/linux',
    'android': 'test_cases/android',
    'all': 'test_cases',
}


def main():
    parser = argparse.ArgumentParser(description='云游戏终端自动化测试框架统一入口')
    parser.add_argument('--platform', choices=['linux', 'android', 'all'],
                        default='all',
                        help='只运行指定平台的用例（linux/android/all），'
                             '默认 all。例如只跑安卓：python run.py --platform android')
    parser.add_argument('--include-integration', action='store_true',
                        help='同时运行标记为 integration 的真机用例（默认排除）')
    args = parser.parse_args()

    with open(os.path.join(BASE_DIR, 'config', 'settings.yaml'),
              'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 指定具体平台时，覆盖本次运行的生效后端（横幅与 get_device() 默认一致）
    if args.platform in ('linux', 'android'):
        config['platform'] = args.platform

    # 1. 每次运行创建独立的时间戳报告目录，产物互不覆盖
    report_dir = os.path.join(
        BASE_DIR, 'reports', f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(report_dir, exist_ok=True)
    os.environ['CLOUDGAME_REPORT_DIR'] = report_dir

    setup_logging(log_file=os.path.join(report_dir, 'run.log'))
    logger.info("=" * 50)
    logger.info("云游戏终端自动化测试框架启动 (平台=%s)", config.get('platform'))
    if args.include_integration:
        logger.info("已启用 integration 真机用例")
    logger.info("本次报告目录: %s", report_dir)
    logger.info("=" * 50)

    # 2. 运行 Pytest 测试
    # marker 过滤：默认排除 manual（人工拔插电源）与 integration（需真机）
    marker_expr = 'not manual'
    if not args.include_integration:
        marker_expr += ' and not integration'

    target = _PLATFORM_TARGETS[args.platform]
    exit_code = pytest.main(["-s", "-v", "-m", marker_expr, target])

    # 3. 只要采集到内存 CSV 就绘制趋势图
    from utils.plotter import draw_memory_chart

    csv_path = os.path.join(report_dir, config['paths']['log_csv'])
    img_path = os.path.join(report_dir, config['paths']['chart_png'])

    if os.path.exists(csv_path):
        logger.info("正在生成内存趋势图...")
        draw_memory_chart(csv_path, img_path,
                          min_free_kb=config['thresholds']['min_free_memory_kb'])
    else:
        logger.warning("未找到设备内存日志（%s），跳过图表生成。", csv_path)

    # 若运行了安卓稳定性测试，打印汇总
    summary_path = os.path.join(report_dir, 'android_stability_summary.txt')
    if os.path.exists(summary_path):
        logger.info("=" * 50)
        logger.info("安卓稳定性测试汇总:")
        with open(summary_path, encoding='utf-8') as f:
            for line in f:
                logger.info("  %s", line.strip())
        logger.info("=" * 50)

    logger.info("自动化测试执行完毕，产物见: %s", report_dir)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
