import logging
import os
import time

import pytest
import yaml

from utils.plotter import log_memory_sample
from test_cases.conftest import report_dir

logger = logging.getLogger(__name__)

# 加载配置
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(base_dir, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 报告目录：run.py 会创建 reports/run_<时间戳>/ 并通过环境变量传入；
# 单独跑 pytest 时回退到 reports/
_csv_dir = report_dir() or os.path.join(base_dir, 'reports')
MEMORY_CSV = os.path.join(_csv_dir, 'device_memory_log.csv')

# device fixture 由 test_cases/conftest.py 统一提供（含无硬件自动 skip）


def test_memory_health(device):
    """采样设备内存写入 CSV，并断言空闲内存达标。"""
    count = config['sampling']['count']
    interval = config['sampling']['interval_sec']
    threshold = config['thresholds']['min_free_memory_kb']

    # 每次运行重置日志，保证数据来自本次采样
    if os.path.exists(MEMORY_CSV):
        os.remove(MEMORY_CSV)

    free_values = []
    for i in range(count):
        info = device.get_memory_info()
        if not info:
            logger.warning("[%s/%s] 解析失败，跳过", i + 1, count)
            continue
        log_memory_sample(MEMORY_CSV, {
            'time': time.strftime('%H:%M:%S'),
            'total': info['total'],
            'used': info['used'],
            'free': info['free'],
            'cache': info['cache'],
        })
        free_values.append(info['free'])
        logger.info("[%s/%s] 空闲内存: %s KB", i + 1, count, info['free'])
        if i < count - 1:
            time.sleep(interval)

    assert free_values, "❌ 未采集到任何内存数据！"
    min_free = min(free_values)
    logger.info("本次采样 %s 次，最小空闲内存: %s KB", len(free_values), min_free)
    assert min_free > threshold, f"❌ 内存不足！警戒线: {threshold}KB，实测最小: {min_free}KB"


def test_device_uptime(device):
    """测试设备运行状态"""
    res = device.send_cmd("uptime")
    assert "up" in res, "❌ 无法获取系统运行时间！"
    logger.info("系统状态: %s", res.strip())


def test_boot_time(device):
    """测试设备重启并计算开机耗时"""
    import time
    logger.info("正在重启设备...")
    device.send_cmd("reboot")

    start_time = time.time()
    boot_success = False

    # 循环等待，每5秒探测一次是否启动成功
    while time.time() - start_time < 120:  # 最多等2分钟
        time.sleep(5)
        res = device.send_cmd("ls /")
        if "bin" in res:
            boot_success = True
            break

    boot_duration = int(time.time() - start_time)
    assert boot_success, "❌ 设备重启失败，可能变砖了！"
    logger.info("设备重启成功，耗时: %s 秒", boot_duration)
