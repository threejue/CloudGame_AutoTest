"""Android 设备稳定性测试（需真机，标记 integration）。

包含两类稳定性测试，结果均落盘到当次报告目录（CLOUDGAME_REPORT_DIR）：
- test_boot_stability：反复通过 adb reboot 重启设备，验证每次都能在超时内
  重新上线。产物：android_boot_log.csv + 追加到 android_stability_summary.txt
- test_resource_stability：持续采样内存/CPU/电池，断言不持续失控。
  产物：android_resource_log.csv + 追加到 android_stability_summary.txt

运行：
    pytest test_cases/android/test_android_stability.py -m integration
    python run.py --platform android --include-integration
"""
import csv
import logging
import os
import shutil
import subprocess
import time

import pytest
import yaml

from core.adb_device import AdbDevice

logger = logging.getLogger(__name__)

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(base_dir, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

ANDROID_CFG = config['android']


def _report_dir():
    """当次运行的报告目录（run.py 通过环境变量传入；单独跑 pytest 时回退 reports/）。"""
    return os.environ.get('CLOUDGAME_REPORT_DIR') or os.path.join(base_dir, 'reports')


def _append_summary(text):
    """把一行/一段结果追加到报告目录的汇总文件。"""
    path = os.path.join(_report_dir(), 'android_stability_summary.txt')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text + '\n')


@pytest.fixture
def real_device():
    adb_on_path = shutil.which(ANDROID_CFG['adb_path'])
    if not adb_on_path:
        pytest.skip('PATH 中找不到 adb，跳过安卓稳定性测试')

    dev = AdbDevice(host=ANDROID_CFG['host'], port=int(ANDROID_CFG['port']),
                    adb_path=ANDROID_CFG['adb_path'])
    # 直接尝试连接（会执行 adb connect），不要求设备已在 adb devices 列表中
    if not dev.connect():
        pytest.skip(f'网络 ADB 设备 {ANDROID_CFG["host"]}:{ANDROID_CFG["port"]} 连接失败'
                    f'（请确认设备在线、已开启网络 ADB 并在屏幕上允许调试）')
    yield dev
    dev.close()


@pytest.mark.integration
def test_boot_stability(real_device):
    """反复重启设备，验证每次都能在超时内重新上线，并记录每次耗时。"""
    bs = ANDROID_CFG.get('boot_stability', {})
    count = bs.get('reboot_count', 3)
    timeout = bs.get('boot_timeout_sec', 180)

    log_path = os.path.join(_report_dir(), 'android_boot_log.csv')
    with open(log_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['轮次', '重启耗时(秒)', '状态', 'uptime'])

        durations = []
        for i in range(1, count + 1):
            logger.info("第 %s/%s 次重启...", i, count)
            assert real_device.reboot(), f"第 {i} 次 reboot 命令发送失败"
            start = time.time()

            if not real_device.wait_for_device(timeout=timeout):
                writer.writerow([i, '-', 'FAIL(超时未上线)', ''])
                pytest.fail(f"第 {i} 次重启后设备 {timeout}s 内未上线，疑似变砖")

            elapsed = round(time.time() - start, 1)
            durations.append(elapsed)
            uptime = real_device.shell('uptime')
            assert uptime, f"第 {i} 次重启后 shell 无响应"
            writer.writerow([i, elapsed, 'OK', uptime.strip()[:80]])
            logger.info("第 %s 次重启成功，耗时 %ss: %s", i, elapsed, uptime.strip()[:60])

    avg = round(sum(durations) / len(durations), 1)
    summary = (f"[重启稳定性] 连续 {count} 次重启均成功 | "
               f"耗时: 最短 {min(durations)}s / 最长 {max(durations)}s / 平均 {avg}s")
    logger.info(summary)
    _append_summary(summary)


@pytest.mark.integration
def test_resource_stability(real_device):
    """持续采样内存/CPU/电池，断言资源不持续失控，采样数据写入 CSV。"""
    rs = ANDROID_CFG.get('resource_stability', {})
    sample_count = rs.get('sample_count', 20)
    interval = rs.get('sample_interval_sec', 5)
    min_mem = rs.get('min_available_mem_kb', 200000)
    max_cpu = rs.get('max_cpu_usage', 95)

    log_path = os.path.join(_report_dir(), 'android_resource_log.csv')
    min_available = None
    cpu_peaks = []
    with open(log_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['序号', '时间', '可用内存(KB)', 'CPU(%)', '电量(%)', '温度(°C)'])

        for i in range(1, sample_count + 1):
            mem = real_device.get_meminfo()
            cpu = real_device.get_cpu_usage(interval=1.0)
            bat = real_device.get_battery()
            avail = mem['available'] if mem else None
            if avail is not None:
                min_available = avail if min_available is None else min(min_available, avail)
            if cpu is not None:
                cpu_peaks.append(cpu)
            writer.writerow([
                i, time.strftime('%H:%M:%S'),
                avail if avail is not None else '',
                cpu if cpu is not None else '',
                bat.get('level') if bat else '',
                bat.get('temp') if bat else '',
            ])
            logger.info("[%s/%s] 可用内存=%s KB, CPU=%s%%",
                        i, sample_count, avail, cpu)
            if i < sample_count:
                time.sleep(max(0, interval - 1))

    assert min_available is not None, "未采集到内存数据"
    peak_cpu = max(cpu_peaks) if cpu_peaks else 0
    mem_ok = min_available >= min_mem
    cpu_ok = peak_cpu <= max_cpu
    summary = (f"[资源稳定性] 采样 {sample_count} 次 | "
               f"最小可用内存 {min_available} KB (阈值 {min_mem}) {'OK' if mem_ok else 'FAIL'} | "
               f"CPU 峰值 {peak_cpu}% (阈值 {max_cpu}) {'OK' if cpu_ok else 'FAIL'}")
    logger.info(summary)
    _append_summary(summary)
    assert mem_ok, (
        f"可用内存跌破阈值：实测最小 {min_available} KB < {min_mem} KB，疑似内存泄漏")
    assert cpu_ok, (
        f"CPU 使用率爆表：峰值 {peak_cpu}% > {max_cpu}%，疑似进程暴走")
