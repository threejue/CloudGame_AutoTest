import serial
import time
import re
import os
import yaml
from datetime import datetime


def _load_device_config():
    """从 config/settings.yaml 读取 device 配置（port/baud）。"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)['device']


class BootAnalyzer:
    def __init__(self, port=None, baud=None, timeout=60):
        # port/baud 未显式传入时回退到配置文件，避免硬编码 COM3
        if port is None or baud is None:
            cfg = _load_device_config()
            port = port if port is not None else cfg['port']
            baud = baud if baud is not None else cfg['baud']
        self.port = port
        self.baud = baud
        self.timeout = timeout  # 最大等待启动时间（秒）
        self.log_content = ""

    def capture_boot_log(self):
        """被动抓取设备上电后的启动日志"""
        ser = None
        try:
            # 关键：打开串口，但不发送任何字符，防止打断 U-Boot
            ser = serial.Serial(self.port, self.baud, timeout=1, rtscts=False, dsrdtr=False)
            print(f"\n📥 已连接串口 {self.port}，请立刻给设备重新上电...")

            start_time = time.time()
            boot_success = False

            # 持续读取直到超时
            while time.time() - start_time < self.timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    self.log_content += data
                    print(data, end='')  # 实时打印启动过程

                    # 看到稳定的 shell 提示符（如 root@TinaLinux:/# ）才算启动成功。
                    # 必须匹配累积缓冲 self.log_content：提示符跨分块到达时不会漏判；
                    # 用精确正则替代 "# "，避免日志里任意 # 字符造成的假阳性。
                    if re.search(r'root@[\w\-]+:[^\n]*#', self.log_content):
                        boot_success = True
                        break
                time.sleep(0.1)

            return boot_success

        except Exception as e:
            print(f"❌ 串口打开/读取失败: {e}")
            return False
        finally:
            # 读取中途异常（如设备拔出）也要保证串口释放，避免端口泄漏
            if ser is not None and ser.is_open:
                ser.close()

    def analyze_and_report(self):
        """分析日志并输出诊断结论"""
        print("\n" + "=" * 50)
        print("🩺 正在分析启动日志，生成诊断报告...")

        # 1. 毫无输出：硬件级故障
        if len(self.log_content.strip()) < 10:
            conclusion = "❌ 严重故障：串口无任何输出。\n" \
                         "👉 根因猜测：U-Boot引导程序损坏、DDR内存虚焊、或主控未启动。\n" \
                         "👉 建议：检查硬件供电，检查TX/RX接线，需返厂或拆机维修。"

        # 2. U-Boot 卡死
        elif "U-Boot" in self.log_content and "Starting kernel" not in self.log_content:
            conclusion = "❌ 严重故障：卡在 U-Boot 阶段。\n" \
                         "👉 根因猜测：引导参数丢失、Flash分区表损坏。\n" \
                         "👉 建议：需通过TF卡或专用工具重新烧录 U-Boot。"

        # 3. 内核崩溃 (Kernel Panic)
        elif "Kernel panic" in self.log_content:
            panic_msg = re.search(r'Kernel panic - not syncing: (.*)', self.log_content)
            msg = panic_msg.group(1) if panic_msg else "未知原因"
            conclusion = f"❌ 严重故障：内核崩溃 (Kernel Panic)。\n" \
                         f"👉 根因猜测：{msg}\n" \
                         f"👉 建议：排查内存是否耗尽，或驱动加载冲突。"

        # 4. 文件系统损坏
        elif "VFS: Unable to mount" in self.log_content or "UBIFS error" in self.log_content:
            conclusion = "❌ 严重故障：根文件系统损坏。\n" \
                         "👉 根因猜测：异常断电导致 UBIFS/OverlayFS 元数据损坏。\n" \
                         "👉 建议：开发需优化文件系统掉电保护机制。"
        else:
            conclusion = "⚠️ 未识别到已知崩溃特征，请人工检查完整日志。"

        print(conclusion)

        # 保存完整日志供开发分析
        report_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports')
        os.makedirs(report_dir, exist_ok=True)
        log_file = os.path.join(report_dir, f"boot_crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(self.log_content)
        print(f"\n📄 完整启动日志已保存至: {log_file}")

        return conclusion