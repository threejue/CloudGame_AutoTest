import pytest
import time
import os
import yaml
from core.device_controller import DeviceController
from utils.boot_analyzer import BootAnalyzer

# 整个文件为人工测试（需拔插电源），默认被 run.py 排除
pytestmark = pytest.mark.manual

# 加载配置
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(base_dir, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)


def test_boot_crash_analysis():
    """测试设备在反复异常重启下的启动稳定性（需人工拔插电源）"""
    print("\n🔄 开始进行启动稳定性专项测试...")

    # 1. 先让设备运行一段时间的游戏，制造内存和存储压力
    dev = DeviceController()
    try:
        dev.connect()
        game_dir = config['boot']['game_dir']
        game_bin = config['boot']['game_bin']
        ret = dev.send_cmd(f"cd {game_dir} && ./{game_bin} &")
        # 路径无效时主动跳过，避免后续压力场景空跑
        if 'not found' in ret or 'No such' in ret:
            pytest.skip(f"游戏路径无效：{game_dir}/{game_bin}，请检查 config/settings.yaml")
        time.sleep(30)  # 跑30秒游戏
        dev.send_cmd("reboot")  # 软重启
    finally:
        dev.close()

    # 2. 等待设备重启完毕（或者在这个瞬间强行拔电，模拟异常掉电）
    time.sleep(2)
    print("🔌 [模拟异常掉电] 请立刻手动拔掉设备电源，等待3秒后再插上！")
    time.sleep(5)  # 给你5秒时间拔插电源

    # 3. 启动黑匣子，抓取上电日志
    analyzer = BootAnalyzer(
        port=config['device']['port'],
        baud=config['device']['baud'],
        timeout=60,
    )
    is_booted = analyzer.capture_boot_log()

    # 4. 分析并断言
    if not is_booted:
        conclusion = analyzer.analyze_and_report()
        pytest.fail(f"设备启动失败！诊断结果：\n{conclusion}")
    else:
        print("\n✅ 设备成功启动，未发生变砖。")
