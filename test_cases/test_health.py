import pytest
import time
from core.device_controller import DeviceController
from utils.plotter import log_memory_sample
import yaml
import os

# 加载配置
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(base_dir, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

MEMORY_CSV = os.path.join(base_dir, config['paths']['log_csv'])


@pytest.fixture(scope="module")
def device():
    dev = DeviceController()
    dev.connect()
    yield dev
    dev.close()


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
            print(f"⚠️ [{i + 1}/{count}] 解析失败，跳过")
            continue
        log_memory_sample(MEMORY_CSV, {
            'time': time.strftime('%H:%M:%S'),
            'total': info['total'],
            'used': info['used'],
            'free': info['free'],
            'cache': info['cache'],
        })
        free_values.append(info['free'])
        print(f"[{i + 1}/{count}] 空闲内存: {info['free']} KB")
        if i < count - 1:
            time.sleep(interval)

    assert free_values, "❌ 未采集到任何内存数据！"
    min_free = min(free_values)
    print(f"\n本次采样 {len(free_values)} 次，最小空闲内存: {min_free} KB")
    assert min_free > threshold, f"❌ 内存不足！警戒线: {threshold}KB，实测最小: {min_free}KB"


def test_device_uptime(device):
    """测试设备运行状态"""
    res = device.send_cmd("uptime")
    assert "up" in res, "❌ 无法获取系统运行时间！"
    print(f"\n系统状态: {res.strip()}")


def test_boot_time(device):
    """测试设备重启并计算开机耗时"""
    import time
    print("\n🔄 正在重启设备...")
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
    print(f"\n🎉 设备重启成功，耗时: {boot_duration} 秒")
