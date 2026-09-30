"""Android 设备远程 ADB 性能测试工具。

传输/连接/内存能力由 core.adb_device.AdbDevice 统一提供（实现了
DeviceInterface），本脚本只在其上扩展 CPU 与电池采样，并提供 CLI：
周期采集 CPU 使用率 / 内存 / 电池电量温度，写入 reports/android_perf.csv 并汇总。

用法：
    python android.py                                # 用 settings.yaml 默认参数
    python android.py --host 192.168.1.50 --port 5555
    python android.py --count 60 --interval 2        # 60 次、每 2 秒一次
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime

from core.adb_device import AdbDevice
from core.device_base import load_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_HEADER = ['时间', 'CPU使用率(%)', '总内存(KB)', '已用(KB)', '可用(KB)',
              '电池电量(%)', '电池温度(°C)']


class AndroidDevice(AdbDevice):
    """AdbDevice + 性能采样扩展（CPU / 电池 / 设备信息）。"""

    # ---------- 设备信息 ----------
    def get_props(self):
        return {
            '型号': self.shell('getprop ro.product.model'),
            'Android版本': self.shell('getprop ro.build.version.release'),
            '序列号': self.shell('getprop ro.serialno'),
        }

    # ---------- CPU ----------
    @staticmethod
    def _parse_cpu_times(stat_text):
        """解析 /proc/stat 首行，返回 (busy_jiffies, total_jiffies)。"""
        m = re.search(r'^cpu\s+([\d\s]+)$', stat_text, re.M)
        if not m:
            return None
        vals = [int(x) for x in m.group(1).split()]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        return total - idle, total

    def get_cpu_usage(self, interval=1.0):
        """两次采样 /proc/stat 做差，返回 CPU 使用率百分比；失败返回 None。"""
        t1 = self._parse_cpu_times(self.shell('cat /proc/stat'))
        time.sleep(interval)
        t2 = self._parse_cpu_times(self.shell('cat /proc/stat'))
        if not t1 or not t2:
            return None
        busy_delta = t2[0] - t1[0]
        total_delta = t2[1] - t1[1]
        return round(busy_delta * 100.0 / total_delta, 1) if total_delta > 0 else 0.0

    # ---------- 电池 ----------
    def get_battery(self):
        """dumpsys battery，返回电量(%)与温度(°C)；无电池设备对应值为 None。"""
        text = self.shell('dumpsys battery')
        level_m = re.search(r'^\s*level:\s*(\d+)', text, re.M)
        temp_m = re.search(r'^\s*temperature:\s*(\d+)', text, re.M)
        return {
            'level': int(level_m.group(1)) if level_m else None,
            'temp': int(temp_m.group(1)) / 10.0 if temp_m else None,  # 0.1°C -> °C
        }


def main():
    cfg = load_config()['android']

    parser = argparse.ArgumentParser(description='Android 远程 ADB 性能测试')
    parser.add_argument('--host', default=cfg['host'], help=f'设备 IP（默认 {cfg["host"]}）')
    parser.add_argument('--port', type=int, default=cfg['port'], help=f'adb 端口（默认 {cfg["port"]}）')
    parser.add_argument('--count', type=int, default=cfg['sample_count'],
                        help=f'采样次数（默认 {cfg["sample_count"]}）')
    parser.add_argument('--interval', type=float, default=cfg['sample_interval'],
                        help=f'采样间隔秒（默认 {cfg["sample_interval"]}）')
    parser.add_argument('--adb', default=cfg['adb_path'], help='adb 可执行文件路径')
    parser.add_argument('--csv', default=os.path.join(BASE_DIR, 'reports', 'android_perf.csv'),
                        help='CSV 输出路径')
    args = parser.parse_args()

    print('=' * 60)
    print('  Android 设备性能测试（远程 ADB）')
    print('=' * 60)
    print(f'目标: {args.host}:{args.port}  采样: {args.count} 次 x {args.interval}s')

    try:
        dev = AndroidDevice(host=args.host, port=args.port, adb_path=args.adb)
    except FileNotFoundError as e:
        print(f'❌ {e}')
        return 2

    if not dev.connect():
        print('排查建议：1) 设备与本机网络互通；2) 设备已开启网络调试(adb tcpip 5555)；'
              '3) 无防火墙拦截端口。')
        return 1

    try:
        props = dev.get_props()
        print(f'设备: {props["型号"]}  Android {props["Android版本"]}  SN={props["序列号"]}')
        print('-' * 60)

        os.makedirs(os.path.dirname(args.csv), exist_ok=True)
        rows = []
        # 每次覆盖写，保证是本轮干净数据
        with open(args.csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)

            for i in range(1, args.count + 1):
                ts = datetime.now().strftime('%H:%M:%S')
                cpu = dev.get_cpu_usage(interval=min(1.0, args.interval))
                mem = dev.get_meminfo()
                bat = dev.get_battery()

                if mem is None:
                    print(f'[{i}/{args.count}] {ts}  采集失败（设备无响应？）')
                    continue

                row = [ts, cpu if cpu is not None else '',
                       mem['total'], mem['used'], mem['available'],
                       bat['level'] if bat['level'] is not None else '',
                       bat['temp'] if bat['temp'] is not None else '']
                writer.writerow(row)
                f.flush()
                rows.append(row)
                mem_pct = mem['used'] * 100.0 / mem['total'] if mem['total'] else 0
                print(f'[{i}/{args.count}] {ts}  CPU {cpu}%  '
                      f'内存已用 {mem_pct:.0f}%（可用 {mem["available"]} KB）  '
                      f'电量 {bat["level"]}%  温度 {bat["temp"]}°C')

                if i < args.count:
                    time.sleep(max(0, args.interval - 1.0))  # get_cpu_usage 已含 1s

        # ---------- 汇总 ----------
        if not rows:
            print('\n⚠️ 未采集到任何有效数据。')
            return 1
        cpus = [r[1] for r in rows if r[1] != '']
        avail = [r[4] for r in rows]
        temps = [r[6] for r in rows if r[6] != '']
        total = rows[0][2]
        print('=' * 60)
        print('📊 性能汇总')
        print(f'  CPU 使用率   : 平均 {sum(cpus)/len(cpus):.1f}%  峰值 {max(cpus)}%')
        print(f'  可用内存     : 最小 {min(avail)} KB / 总 {total} KB')
        print(f'  电池温度     : 最高 {max(temps)}°C' if temps else '  电池温度     : 无数据')
        print(f'📄 明细已保存: {args.csv}')
        return 0
    finally:
        dev.close()


if __name__ == '__main__':
    sys.exit(main())
