# 云游戏终端自动化测试框架 (CloudGame_AutoTest)

## 📖 项目简介
本项目是一套基于 Python + Pytest + PySerial 的嵌入式 Linux 云游戏终端自动化测试框架。
针对设备（TinaLinux）频繁出现的“无法开机”、“变砖”、“内存溢出”等痛点，实现了通过串口对设备的自动化控制、系统健康巡检、异常掉电测试及视频流质量监控。

## 🛠️ 技术栈
- 编程语言: Python 3.x
- 测试框架: Pytest
- 硬件通信: PySerial (串口通信)
- 数据处理: Pandas, Matplotlib
- 版本控制: Git / GitHub

## 📂 目录结构
```text
├── config/                 # 配置文件目录 (settings.yaml)
├── core/                   # 核心驱动层 (封装串口通信、设备控制、重启、日志采集)
├── test_cases/             # 测试用例层 (Pytest用例)
│   ├── test_health.py      # 设备内存、负载、启动耗时测试
│   └── test_video.py       # 视频流延迟与丢包率监控
├── utils/                  # 工具层 (数据解析、图表绘制、启动黑匣子)
├── reports/                # 测试报告与图表输出 (被.gitignore忽略)
├── run.py                  # 自动化测试统一入口
└── requirements.txt        # 项目依赖清单