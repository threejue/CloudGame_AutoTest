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
    """持续采样设备内存写入 CSV，手动按 Ctrl+C 结束后断言空闲内存达标。

    采样结束方式（见 config/settings.yaml 的 sampling 段）：
    - manual_stop=true（默认）：一直采样，直到在控制台按 Ctrl+C 手动结束；
    - max_samples>0：采样次数达到上限自动结束（可作为无人值守时的安全兜底，
      手动 Ctrl+C 依然随时可提前结束）。
    KeyboardInterrupt 在本用例内部被捕获：停止采样后仍会完成断言，
    不会中止整个 pytest 会话（注意不要连按两次 Ctrl+C）。
    """
    sampling = config['sampling']
    interval = sampling['interval_sec']
    manual_stop = sampling.get('manual_stop', True)
    max_samples = int(sampling.get('max_samples', 0) or 0)  # 0 = 不限
    threshold = config['thresholds']['min_free_memory_kb']

    # 每次运行重置日志，保证数据来自本次采样
    if os.path.exists(MEMORY_CSV):
        os.remove(MEMORY_CSV)

    free_values = []
    stopped_manually = False
    i = 0
    logger.info("内存采样开始（间隔 %ss），按 Ctrl+C 结束采样%s",
                interval, "" if manual_stop else f"，或采满 {max_samples} 次自动结束")
    try:
        while True:
            i += 1
            info = device.get_memory_info()
            if not info:
                logger.warning("[第%s次] 解析失败，跳过", i)
            else:
                log_memory_sample(MEMORY_CSV, {
                    'time': time.strftime('%H:%M:%S'),
                    'total': info['total'],
                    'used': info['used'],
                    'free': info['free'],
                    'cache': info['cache'],
                })
                free_values.append(info['free'])
                logger.info("[第%s次] 空闲内存: %s KB", i, info['free'])

            # 达到安全上限自动结束（max_samples=0 表示不限）
            if max_samples and i >= max_samples:
                logger.info("已达到采样上限 %s 次，自动结束", max_samples)
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        # Ctrl+C：优雅停止采样，继续往下走断言（吞掉异常，不冒泡给 pytest）
        stopped_manually = True
        logger.info("收到 Ctrl+C，手动结束采样（共完成 %s 次）", len(free_values))

    assert free_values, "❌ 未采集到任何内存数据！"
    min_free = min(free_values)
    end_way = "手动结束" if stopped_manually else "自动结束"
    logger.info("采样%s：共 %s 次，最小空闲内存: %s KB",
                end_way, len(free_values), min_free)
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
