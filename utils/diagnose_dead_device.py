"""死设备诊断入口：对无法开机的设备做被动串口抓取 + 自动分级诊断。

与 linux/test_boot_stability 的区别：
- 跳过"启动游戏 / 软重启"前置（死设备无法响应命令，那两步是空跑）
- 仅做：上电 -> capture_boot_log -> analyze_and_report
- 适合"电源灯亮但不开机"的设备

用法（在项目根目录执行）：
    python -m utils.diagnose_dead_device                # 默认 60s 超时
    python -m utils.diagnose_dead_device --timeout 120  # 死设备/启动慢可加长
"""
import argparse
import logging
import os
import sys

import yaml

# 支持直接以脚本方式运行（python utils/diagnose_dead_device.py）：
# 把项目根目录加入 sys.path，保证能 import core / utils 包
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.log_setup import setup_logging          # noqa: E402
from utils.boot_analyzer import BootAnalyzer      # noqa: E402

logger = logging.getLogger(__name__)

with open(os.path.join(_PROJECT_ROOT, 'config', 'settings.yaml'),
          'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description='死设备被动串口诊断')
    parser.add_argument('--timeout', type=int, default=60,
                        help='抓取超时秒数（死设备/启动慢可加长，默认 %(default)s）')
    args = parser.parse_args()

    port = config['device']['port']
    baud = config['device']['baud']

    logger.info("=" * 60)
    logger.info("死设备诊断模式")
    logger.info("=" * 60)
    logger.info("串口: %s  波特: %s  超时: %ss", port, baud, args.timeout)
    logger.info("重要前置检查：若结论为\"无串口输出\"，请先用一台能正常开机的设备"
                "接同一根串口线验证 COM 口/波特/接线 OK，排除串口链路问题。")
    logger.info("操作步骤：1) 把串口线接到死设备的 TX/RX/GND（先不通电）；"
                "2) 现在给死设备上电（插电源）。")

    try:
        # 交互式回车确认，不属于日志范畴，保留内置输入提示
        input('已给设备上电，按回车开始抓取（或 Ctrl+C 退出）...')
    except (KeyboardInterrupt, EOFError):
        logger.info("已取消。")
        return 1

    analyzer = BootAnalyzer(port=port, baud=baud, timeout=args.timeout)
    is_booted = analyzer.capture_boot_log()

    logger.info("=" * 60)
    if is_booted:
        logger.info("设备成功启动！shell 提示符已出现，未发生变砖。"
                    "（若仍无法正常使用，可能是应用层问题，非启动故障）")
        rc = 0
    else:
        logger.error("设备未能完成启动，进入诊断...")
        conclusion = analyzer.analyze_and_report()
        logger.info("-" * 60)
        logger.info("%s", conclusion)
        logger.info("-" * 60)
        logger.info("完整启动日志已保存至当次报告目录（或 reports/）下")
        logger.info("若结论是\"无串口输出\"："
                    "- 优先用正常设备验证串口链路；"
                    "- 再用万用表测 3.3V/1.8V/DDR VDDQ 电源轨、RESET 复位线、晶振；"
                    "- 手摸 SoC 是否发热（发热=在跑，不发热=未启动）。")
        rc = 2
    logger.info("=" * 60)
    return rc


if __name__ == '__main__':
    sys.exit(main())
