import serial
import time
import yaml
import os
import re

class DeviceController:
    def __init__(self):
        # 动态获取 config 路径，保证不管从哪里运行都能找到
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'config', 'settings.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        self.port = config['device']['port']
        self.baud = config['device']['baud']
        self.ser = None

    def connect(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=1, rtscts=False, dsrdtr=False)
        time.sleep(2)
        self.ser.read_all()  # 清空历史缓冲区
        print(f"✅ [DeviceController] 设备已连接: {self.port}")

    def send_cmd(self, cmd):
        if not self.ser:
            raise Exception("串口未连接！")
        self.ser.write((cmd + "\r\n").encode('utf-8'))
        time.sleep(1.5)  # 等待设备处理
        return self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')

    def get_memory_info(self):
        """解析 free 命令，返回全部内存列（单位: KB）。
        返回 dict: {'total','used','free','cache'}；解析失败返回 None。
        """
        res = self.send_cmd("free")

        # 正则匹配 Mem: 后的 总内存 已用 空闲 共享/缓存
        match = re.search(r'Mem:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', res)
        if not match:
            print("⚠️ 无法从 free 命令输出中解析出内存数据！")
            return None
        return {
            'total': int(match.group(1)),
            'used': int(match.group(2)),
            'free': int(match.group(3)),
            'cache': int(match.group(4)),
        }

    def get_free_memory(self):
        """获取空闲内存 (单位: KB)。保留旧接口兼容。"""
        info = self.get_memory_info()
        return info['free'] if info else 0

    def close(self):
        if self.ser:
            self.ser.close()
            print("🔒 [DeviceController] 串口已关闭")