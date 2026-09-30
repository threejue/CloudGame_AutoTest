import pytest
import os
import sys

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 云游戏终端自动化测试框架启动...")
    print("=" * 50)

    # 1. 运行 Pytest 测试，自动生成 Allure 报告（需安装 allure-pytest）
    # -s: 允许打印 print 输出; -v: 显示详细日志
    # -m "not manual": 默认排除需人工介入的用例（如拔插电源的 boot 稳定性测试）
    exit_code = pytest.main(["-s", "-v", "-m", "not manual", "test_cases/"])

    # 2. 如果测试通过，自动绘制内存折线图
    # 假设测试过程中已经生成了 device_memory_log.csv
    from utils.plotter import draw_memory_chart

    csv_path = os.path.join(os.path.dirname(__file__), 'reports', 'device_memory_log.csv')
    img_path = os.path.join(os.path.dirname(__file__), 'reports', 'memory_chart.png')

    if os.path.exists(csv_path):
        print("\n📊 正在生成内存趋势图...")
        draw_memory_chart(csv_path, img_path)
    else:
        print("\n⚠️ 未找到设备内存日志，跳过图表生成。")

    print("\n✅ 自动化测试执行完毕。")
    sys.exit(exit_code)