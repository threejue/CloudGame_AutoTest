"""设备控制统一接口。

所有设备后端（Linux 串口终端 / Android 网络 ADB …）都实现 DeviceInterface，
上层 test_cases / utils 只面向该接口编程，与具体传输方式解耦。
"""
import abc
import logging
import os
import re

import yaml

logger = logging.getLogger(__name__)


def load_config():
    """读取 config/settings.yaml（各后端共享同一份配置）。"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, 'config', 'settings.yaml'),
              'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


class DeviceInterface(abc.ABC):
    """设备统一接口。后端必须实现 connect / send_cmd / close 三个原语，
    内存采集/重启等通用能力由本基类基于 send_cmd 提供（模板方法）。"""

    @abc.abstractmethod
    def connect(self):
        """建立与设备的连接，成功返回真值。"""
        raise NotImplementedError

    @abc.abstractmethod
    def send_cmd(self, cmd):
        """向设备发送一条 shell 命令，返回命令输出文本（str）。"""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self):
        """释放连接资源（串口/ adb 连接等）。"""
        raise NotImplementedError

    # ---------- 通用能力（默认实现，子类可覆盖） ----------

    def reboot(self):
        """软重启设备。"""
        return self.send_cmd("reboot")

    def get_memory_info(self):
        """解析 `free` 命令，返回全部内存列（单位 KB）。
        返回 dict: {'total','used','free','cache'}；解析失败返回 None。
        适用于 BusyBox/TinaLinux 风格输出；Android 端在 AdbDevice 中覆盖。
        """
        res = self.send_cmd("free")
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
        """获取空闲内存 (单位 KB)。保留旧接口兼容。"""
        info = self.get_memory_info()
        return info['free'] if info else 0
