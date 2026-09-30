"""Android 压力测试（需真机，标记 integration）。

对设备施加 CPU / 内存压力，持续采样性能指标，验证：
- 压力期间设备不崩溃、温度不超限、内存不跌破下限
- 压力移除后资源能回落

运行：
    pytest test_cases/android/test_android_stress.py -m integration
    python run.py --platform android --include-integration

产物（写入 CLOUDGAME_REPORT_DIR）：
- android_stress_log.csv：每次采样的阶段/时间/CPU/可用内存/电量/温度
- android_stability_summary.txt：追加压测结论
"""
import csv
import logging
import os
import shutil
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
    return os.environ.get('CLOUDGAME_REPORT_DIR') or os.path.join(base_dir, 'reports')


def _append_summary(text):
    path = os.path.join(_report_dir(), 'android_stability_summary.txt')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text + '\n')


@pytest.fixture
def real_device():
    adb_on_path = shutil.which(ANDROID_CFG['adb_path'])
    if not adb_on_path:
        pytest.skip('PATH 中找不到 adb，跳过安卓压力测试')

    dev = AdbDevice(host=ANDROID_CFG['host'], port=int(ANDROID_CFG['port']),
                    adb_path=ANDROID_CFG['adb_path'])
    if not dev.connect():
        pytest.skip(f'网络 ADB 设备 {ANDROID_CFG["host"]}:{ANDROID_CFG["port"]} 连接失败')
    yield dev
    # 无论测试成败，确保压力被清理
    dev.stress_stop()
    dev.close()


def _sample_row(writer, phase, idx, dev):
    mem = dev.get_meminfo()
    cpu = dev.get_cpu_usage(interval=1.0)
    bat = dev.get_battery()
    row = [
        phase, idx, time.strftime('%H:%M:%S'),
        mem['available'] if mem else '',
        cpu if cpu is not None else '',
        bat.get('level') if bat else '',
        bat.get('temp') if bat else '',
    ]
    writer.writerow(row)
    logger.info("[%s] #%s CPU=%s%% 可用内存=%sKB 温度=%s°C",
                phase, idx, cpu, row[3], row[6])
    return row


@pytest.mark.integration
def test_cpu_stress(real_device):
    """CPU 压力测试：占满核心，验证温度/设备稳定，施压后 CPU 回落。"""
    s = ANDROID_CFG.get('stress', {})
    duration = s.get('cpu_duration_sec', 30)
    interval = s.get('sample_interval_sec', 2)
    max_temp = s.get('max_temp', 50)

    log_path = os.path.join(_report_dir(), 'android_stress_log.csv')
    new_file = not os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(['阶段', '序号', '时间', '可用内存(KB)',
                             'CPU(%)', '电量(%)', '温度(°C)'])

        # 基线
        _sample_row(writer, '基线', 0, real_device)
        # 施压
        workers = real_device.stress_cpu_start()
        logger.info("CPU 压力已启动（%s 进程），持续 %ss...", workers, duration)
        end = time.time() + duration
        temps, cpus = [], []
        i = 1
        while time.time() < end:
            row = _sample_row(writer, 'CPU压力', i, real_device)
            if row[6] not in ('', None):
                temps.append(float(row[6]))
            if row[4] not in ('', None):
                cpus.append(float(row[4]))
            i += 1
            time.sleep(max(0, interval - 1))

        # 停止压力
        real_device.stress_stop()
        time.sleep(3)
        # 恢复采样
        row = _sample_row(writer, '恢复', 0, real_device)
        recovery_cpu = float(row[4]) if row[4] not in ('', None) else None

    peak_temp = max(temps) if temps else 0
    peak_cpu = max(cpus) if cpus else 0
    temp_ok = peak_temp <= max_temp
    recover_ok = recovery_cpu is None or recovery_cpu < 50
    summary = (f"[CPU压力] 施压 {duration}s | 温度峰值 {peak_temp}°C "
               f"(阈值 {max_temp}) {'OK' if temp_ok else 'FAIL'} | "
               f"CPU 峰值 {peak_cpu:.0f}% | 停止后 CPU {recovery_cpu}% "
               f"{'OK' if recover_ok else 'FAIL(未回落)'}")
    logger.info(summary)
    _append_summary(summary)
    assert temp_ok, f"压力期间温度超限: {peak_temp}°C > {max_temp}°C"
    assert recover_ok, f"停止 CPU 压力后 3s，CPU 仍为 {recovery_cpu}%，疑似未恢复"


@pytest.mark.integration
def test_mem_stress(real_device):
    """内存压力测试：占用指定内存，验证可用内存不跌破下限、设备不崩。"""
    s = ANDROID_CFG.get('stress', {})
    size_mb = s.get('mem_size_mb', 200)
    duration = s.get('mem_duration_sec', 30)
    interval = s.get('sample_interval_sec', 2)
    min_mem = s.get('min_available_mem_kb', 100000)
    max_temp = s.get('max_temp', 50)

    log_path = os.path.join(_report_dir(), 'android_stress_log.csv')
    new_file = not os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(['阶段', '序号', '时间', '可用内存(KB)',
                             'CPU(%)', '电量(%)', '温度(°C)'])

        _sample_row(writer, '基线', 0, real_device)
        real_device.stress_mem_start(size_mb)
        logger.info("内存压力已启动（占用 %s MB），持续 %ss...", size_mb, duration)
        end = time.time() + duration
        mems, temps = [], []
        i = 1
        while time.time() < end:
            row = _sample_row(writer, '内存压力', i, real_device)
            if row[3] not in ('', None):
                mems.append(float(row[3]))
            if row[6] not in ('', None):
                temps.append(float(row[6]))
            i += 1
            time.sleep(max(0, interval - 1))

        real_device.stress_stop()
        time.sleep(2)
        row = _sample_row(writer, '恢复', 0, real_device)
        recovery_mem = float(row[3]) if row[3] not in ('', None) else None

    min_avail = min(mems) if mems else 0
    peak_temp = max(temps) if temps else 0
    mem_ok = min_avail >= min_mem
    temp_ok = peak_temp <= max_temp
    recover_ok = recovery_mem is None or recovery_mem > min_mem
    summary = (f"[内存压力] 占用 {size_mb}MB 持续 {duration}s | 最小可用内存 "
               f"{min_avail:.0f} KB (阈值 {min_mem}) {'OK' if mem_ok else 'FAIL'} | "
               f"温度峰值 {peak_temp}°C {'OK' if temp_ok else 'FAIL'} | "
               f"释放后可用内存 {recovery_mem:.0f} KB {'OK' if recover_ok else 'FAIL(未恢复)'}")
    logger.info(summary)
    _append_summary(summary)
    assert mem_ok, (f"压力期间可用内存跌破阈值: {min_avail:.0f} KB < {min_mem} KB，"
                    f"疑似内存不足或泄漏")
    assert temp_ok, f"压力期间温度超限: {peak_temp}°C > {max_temp}°C"
    assert recover_ok, f"释放内存压力后，可用内存仍为 {recovery_mem:.0f} KB，未恢复"
