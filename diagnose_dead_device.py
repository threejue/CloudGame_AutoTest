"""死设备诊断入口：对无法开机的设备做被动串口抓取 + 自动分级诊断。

与 test_boot_stability 的区别：
- 跳过"启动游戏 / 软重启"前置（死设备无法响应命令，那两步是空跑）
- 仅做：上电 -> capture_boot_log -> analyze_and_report
- 适合"电源灯亮但不开机"的设备

用法：
    python diagnose_dead_device.py                # 用默认 60s 超时
    python diagnose_dead_device.py --timeout 120  # 死设备/启动慢可加长
"""
import argparse
import os
import sys

import yaml

from utils.boot_analyzer import BootAnalyzer

base_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(base_dir, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description='死设备被动串口诊断')
    parser.add_argument('--timeout', type=int, default=60,
                        help='抓取超时秒数（死设备/启动慢可加长，默认 %(default)s）')
    args = parser.parse_args()

    port = config['device']['port']
    baud = config['device']['baud']

    print('=' * 60)
    print('  死设备诊断模式')
    print('=' * 60)
    print(f'串口: {port}  波特: {baud}  超时: {args.timeout}s')
    print()
    print('重要前置检查：')
    print('  若结论为"无串口输出"，请先用一台能正常开机的设备')
    print('  接同一根串口线验证 COM 口/波特/接线 OK，排除串口链路问题。')
    print()
    print('操作步骤：')
    print('  1. 把串口线接到死设备的 TX/RX/GND（先不通电）')
    print('  2. 现在给死设备上电（插电源）')
    print('  3. 回到这里按回车，开始被动抓取启动日志')
    print()

    try:
        input('已给设备上电，按回车开始抓取（或 Ctrl+C 退出）...')
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。')
        return 1

    analyzer = BootAnalyzer(port=port, baud=baud, timeout=args.timeout)
    print()
    is_booted = analyzer.capture_boot_log()

    print()
    print('=' * 60)
    if is_booted:
        print('设备成功启动！shell 提示符已出现，未发生变砖。')
        print('（若仍无法正常使用，可能是应用层问题，非启动故障）')
        rc = 0
    else:
        print('设备未能完成启动，进入诊断...')
        conclusion = analyzer.analyze_and_report()
        print('-' * 60)
        print(conclusion)
        print('-' * 60)
        print()
        print('完整启动日志已保存至 reports/boot_log_*.txt')
        print('若结论是"无串口输出"：')
        print('  - 优先用正常设备验证串口链路')
        print('  - 再用万用表测 3.3V/1.8V/DDR VDDQ 电源轨、RESET 复位线、晶振')
        print('  - 手摸 SoC 是否发热（发热=在跑，不发热=未启动）')
        rc = 2
    print('=' * 60)
    return rc


if __name__ == '__main__':
    sys.exit(main())
