import pytest
import os
import sys

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 云游戏终端自动化测试框架启动...")
    print("=" * 50)

    # 1. 运行 Pytest 测试，自动生成 Allure 报告（需安装 allure-pytest）
    # -s: 允许打印 print 输出; -v: 显示详细日志
    # -m "not manual and not integration":
    #   排除需人工介入的用例（拔插电源）和需真机的集成测试（网络 ADB 设备）
    exit_code = pytest.main(["-s", "-v", "-m", "not manual and not integration",
                             "test_cases/"])

    # 2. 只要采集到内存 CSV 就绘制趋势图（与测试是否全部通过无关：
    #    即使内存阈值用例失败，也能产出图表用于排查低内存问题）
    from utils.plotter import draw_memory_chart

    csv_path = os.path.join(os.path.dirname(__file__), 'reports', 'device_memory_log.csv')
    img_path = os.path.join(os.path.dirname(__file__), 'reports', 'memory_chart.png')

    if os.path.exists(csv_path):
        print("\n📊 正在生成内存趋势图...")
        import yaml
        with open(os.path.join(os.path.dirname(__file__), 'config', 'settings.yaml'),
                  'r', encoding='utf-8') as f:
            _cfg = yaml.safe_load(f)
        draw_memory_chart(csv_path, img_path,
                          min_free_kb=_cfg['thresholds']['min_free_memory_kb'])
    else:
        print("\n⚠️ 未找到设备内存日志，跳过图表生成。")

    print("\n✅ 自动化测试执行完毕。")
    sys.exit(exit_code)