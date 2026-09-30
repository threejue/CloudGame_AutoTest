# 云游戏终端自动化测试框架 (CloudGame_AutoTest)

## 一、项目简介

一套面向云游戏终端的自动化测试框架，针对设备（嵌入式 Linux / Android）频繁出现的
**无法开机、变砖、内存溢出、视频流延迟丢包** 等问题，提供：

- 通过 **串口（pyserial）** 对嵌入式 Linux（如 TinaLinux）终端的自动控制与健康巡检；
- 通过 **网络 ADB** 对 Android 终端的远程连接与性能（CPU/内存/电池）采集；
- 异常掉电后的 **启动黑匣子日志抓取与自动分级诊断**；
- 内存采样写入 CSV 并自动生成趋势图；
- 统一的 pytest 用例编排、配置驱动与多后端设备抽象。

核心设计目标：**上层用例与设备传输方式解耦** —— 一套测试代码可在串口 Linux 终端和
Android ADB 设备之间切换，几乎无需改动。

## 二、技术栈

| 类别 | 选型 |
|---|---|
| 语言 | Python 3.8+ |
| 测试框架 | pytest |
| 串口通信 | pyserial |
| Android 通信 | 系统 `adb`（platform-tools，无第三方 Python 库） |
| 配置 | PyYAML |
| 数据与图表 | pandas、matplotlib、numpy |

## 三、架构设计

### 分层结构

```text
入口层      run.py / android.py / diagnose_dead_device.py
              │  编排：pytest 执行、采样循环、被动诊断
测试层      test_cases/        只面向 DeviceInterface 编程，不感知传输方式
              │
核心层      core/
   device_base.py        DeviceInterface(ABC)：connect/send_cmd/close + 通用能力模板方法
   serial_device.py      SerialDevice  —— pyserial 实现（Linux 串口端）
   adb_device.py         AdbDevice     —— 网络 adb 实现（Android 端）
   device_controller.py  工厂：按 settings.yaml 的 platform 返回具体实现
              │
工具层      utils/plotter.py       CSV 采样落盘 + 双子图内存趋势图
            utils/boot_analyzer.py 上电启动日志被动抓取 + 变砖分级诊断
              │
配置层      config/settings.yaml   唯一配置入口
产物层      reports/               CSV / PNG / 启动日志（被 .gitignore 忽略）
```

### 设备抽象（设计精髓）

[core/device_base.py](core/device_base.py) 用 ABC 只规定三个原语：`connect()` /
`send_cmd(cmd)` / `close()`，并以 **模板方法** 在基类提供通用能力
（`get_memory_info` 解析 BusyBox `free`、`get_free_memory`、`reboot`）。

- [SerialDevice](core/serial_device.py) 实现三原语即可复用全部上层能力；
- [AdbDevice](core/adb_device.py) 同样实现三原语，并因 Android 无标准 `free` 输出而
  **覆盖** `get_memory_info`（改读 `/proc/meminfo`），但对外仍返回统一契约
  `{total, used, free, cache}`；
- [DeviceController](core/device_controller.py) 保留历史类名，通过工厂按
  `platform` 返回真实后端，因此 `test_cases/` 中原有
  `DeviceController()` 调用 **零改动**。

新增一种设备后端（如 SSH 设备）只需：继承 `DeviceInterface`，实现三个原语，
在工厂 `_BACKENDS` 注册即可，测试层与工具层完全不变。

## 四、目录结构

```text
├── config/
│   └── settings.yaml          # 全局配置（后端选择/串口/采样/阈值/ADB/boot）
├── core/
│   ├── device_base.py         # 设备统一接口 + 通用内存解析 + 配置加载
│   ├── serial_device.py       # 串口(pyserial)实现
│   ├── adb_device.py          # 网络 ADB 实现
│   └── device_controller.py   # 设备工厂（兼容旧类名）
├── test_cases/
│   ├── test_health.py         # 内存健康/运行时长/重启耗时（串口端）
│   ├── test_video.py          # 视频流延迟与丢包率（读 /tmp/anygame.log）
│   ├── test_boot_stability.py # 异常掉电启动稳定性（marker: manual）
│   └── test_android_adb.py    # ADB 连接与内存读取（离线单测 + 真机集成）
├── utils/
│   ├── plotter.py             # CSV 采样写入 + 内存趋势图
│   └── boot_analyzer.py       # 启动黑匣子 + 变砖分级诊断
├── reports/                   # 运行产物（CSV/PNG/日志），不入版本库
├── run.py                     # 一键执行：pytest + 自动出内存图
├── android.py                 # Android 远程 ADB 性能采样 CLI
├── diagnose_dead_device.py    # 死设备被动诊断 CLI
├── pytest.ini                 # marker 注册（manual / integration）
├── requirements.txt
└── .gitignore
```

## 五、快速开始

### 1. 环境准备

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

- 串口端：安装 USB 转串口驱动，确认串口号（Windows 如 `COM3`，Linux 如 `/dev/ttyUSB0`）。
- Android 端：安装 platform-tools 并确保 `adb` 在 PATH（或在配置中写绝对路径）。

### 2. 修改配置

编辑 [config/settings.yaml](config/settings.yaml)：

```yaml
# 选择后端：serial（Linux 串口）或 android（网络 ADB）
platform: 'serial'

device:                 # serial 后端使用
  port: 'COM3'
  baud: 115200

android:                # android 后端 / android.py 使用
  host: '192.168.1.100'
  port: 5050
```

### 3. 运行

| 目的 | 命令 |
|---|---|
| 一键跑串口端全套并出内存图 | `python run.py` |
| Android 远程性能采样 | `python android.py --host <IP> --port 5050` |
| 诊断无法开机的设备 | `python diagnose_dead_device.py` |
| 只跑某类用例 | `pytest test_cases/test_health.py -v` |

## 六、功能与使用说明

### 6.1 一键测试 `run.py`

执行 pytest（默认排除 `manual` 与 `integration` 用例），随后只要存在内存 CSV
就生成双子图趋势图（测试失败也会出图，便于排查低内存问题）。
产物：`reports/device_memory_log.csv`、`reports/memory_chart.png`。

### 6.2 内存趋势图

[utils/plotter.py](utils/plotter.py) 将「已用 / 空闲」拆为上下两个子图，
**各自独立 Y 轴量程并围绕数据自适应**（不从 0 起），解决了「基数约 20 万 KB、
波动仅几百 KB 时曲线被压成平线」的问题；空闲子图还会标注低内存阈值与安全余量。

### 6.3 Android 性能采集 `android.py`

周期采集 **CPU 使用率**（`/proc/stat` 两次采样做差）、**内存**（`/proc/meminfo`）、
**电池电量/温度**（`dumpsys battery`），实时写入 `reports/android_perf.csv`
并在结束打印平均/峰值汇总。所有命令走最底层、跨 Android 版本兼容的接口。

设备侧一次性准备：与电脑同局域网 → USB 连一次执行 `adb tcpip 5050`（或开启
「无线调试」，注意无线调试实际端口以设备显示为准）→ 在配置中填设备 IP。

### 6.4 死设备诊断 `diagnose_dead_device.py`

对无法开机的设备，跳过「启动游戏/软重启」等前置（死设备无法响应命令），
仅做：上电后被动抓取串口日志 → 自动分级：

| 现象 | 诊断结论 |
|---|---|
| 串口零输出 | 硬件级故障（并提示先排查串口链路、再测电源轨/复位/晶振） |
| 卡 U-Boot、未进内核 | 引导参数丢失 / Flash 分区表损坏 |
| Kernel panic | 提取 panic 原因 |
| VFS mount 失败 / UBIFS error | 根文件系统损坏 |

启动成功判定使用精确的 shell 提示符正则并匹配累积缓冲，
避免日志中任意 `#` 字符造成假阳性、或提示符跨分块到达导致漏判。

## 七、测试体系

测试通过 marker 分三类，默认套件无需任何硬件即可收集：

| Marker | 含义 | 默认是否运行 |
|---|---|---|
| （无） | 离线单测 / 串口端用例 | 运行 |
| `manual` | 需人工拔插电源（启动稳定性） | 排除，`-m manual` 运行 |
| `integration` | 需真机（网络 ADB 安卓设备） | 排除，`-m integration` 运行 |

```bash
pytest test_cases/test_android_adb.py              # 离线：mock adb，验证连接判定与内存解析
pytest test_cases/ -m integration                  # 真机集成（设备不在线自动 skip）
pytest test_cases/ -m "not manual and not integration"  # run.py 的默认选择
```

[test_cases/test_android_adb.py](test_cases/test_android_adb.py) 的离线用例覆盖：
adb 缺失、连接成功 / unauthorized / 拒绝三种状态、shell 命令拼装、
`/proc/meminfo` 解析、统一内存契约、空输出容错。

## 八、扩展指南：新增设备后端

1. 新建 `core/ssh_device.py`，定义 `class SshDevice(DeviceInterface)`；
2. 实现 `connect()` / `send_cmd(cmd)` / `close()` 三个原语；
3. 若该平台内存命令口径不同，覆盖 `get_memory_info()`，
   但务必返回 `{total, used, free, cache}`（单位 KB）；
4. 在 [device_controller.py](core/device_controller.py) 的 `_BACKENDS`
   注册映射（如 `'ssh': SshDevice`）；
5. 在 `settings.yaml` 增加对应配置段，并把 `platform` 切到新值。

测试层与 `utils/` 无需任何修改。

## 九、配置项说明（settings.yaml）

| 段 | 关键字段 | 说明 |
|---|---|---|
| `platform` | `serial` / `android` | 设备后端选择 |
| `device` | `port` `baud` `timeout` `read_idle_sec` | 串口参数、命令总超时、静默判定结束时间 |
| `paths` | `log_csv` `chart_png` | CSV 与图表输出路径 |
| `sampling` | `count` `interval_sec` | 内存采样次数与间隔 |
| `thresholds` | `min_free_memory_kb` `max_cpu_temp` | 空闲内存告警阈值（CPU 温度阈值预留） |
| `boot` | `game_dir` `game_bin` | 启动稳定性测试的游戏路径（**需改成真实路径**） |
| `android` | `host` `port` `adb_path` `sample_count` `sample_interval` | ADB 连接与采样参数 |

## 十、已知限制与后续规划

- 串口端用例（test_health/test_video）依赖真实串口设备，未接硬件时会失败；
  尚不具备 Android 离线用例那样的「无设备自动 skip」能力（规划中）。
- `boot.game_dir` 仍为占位符 `/your_game_path`，使用启动稳定性测试前需填真实路径。
- `thresholds.max_cpu_temp` 当前仅预留，尚无对应温度用例。
- Android 真机集成用例目前覆盖连接与内存；CPU/电池解析已有离线验证，可继续补充断言。
- 框架使用 `print` 输出日志，后续可切换为标准 `logging` 并支持日志落盘。
- 暂未提供 CI 配置与打包发布；串口/绘图模块的离线单测覆盖率可进一步提升。
