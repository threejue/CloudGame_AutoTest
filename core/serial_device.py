"""Linux 端设备实现：通过 pyserial 直连串口 shell（如 TinaLinux 终端）。"""
import logging
import time

import serial

from .device_base import DeviceInterface, load_config

logger = logging.getLogger(__name__)


class SerialDevice(DeviceInterface):
    """串口设备。读取策略：静默间隔判定输出结束 + 总超时兜底。"""

    def __init__(self, config=None):
        cfg = (config or load_config())['device']
        self.port = cfg['port']
        self.baud = cfg['baud']
        self.read_timeout = cfg.get('timeout', 2)       # 单条命令总超时(秒)
        self.read_idle = cfg.get('read_idle_sec', 0.4)  # 静默多久判定输出结束(秒)
        self.ser = None

    def connect(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=1,
                                 rtscts=False, dsrdtr=False)
        time.sleep(2)
        self.ser.read_all()  # 清空历史缓冲区
        print(f"✅ [SerialDevice] 设备已连接: {self.port}")

    def send_cmd(self, cmd):
        if not self.ser:
            raise Exception("串口未连接！")
        # 清掉命令前的残留输出，避免上一条结果混入本次
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r\n").encode('utf-8'))

        # 累积读取：串口持续静默 read_idle 秒即认为输出结束，
        # 超过 read_timeout 兜底退出，避免持续吐数据时单次快照截断。
        deadline = time.time() + self.read_timeout
        chunks = []
        last_recv = None
        while time.time() < deadline:
            n = self.ser.in_waiting
            if n:
                chunks.append(self.ser.read(n))
                last_recv = time.time()
            elif last_recv is not None and time.time() - last_recv >= self.read_idle:
                break
            else:
                time.sleep(0.02)
        return b''.join(chunks).decode('utf-8', errors='ignore')

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None
            print("🔒 [SerialDevice] 串口已关闭")
