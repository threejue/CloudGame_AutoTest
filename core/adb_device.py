"""Android 端设备实现：通过网络 ADB（adb connect host:port）操作设备。

仅依赖外部 adb 可执行文件（platform-tools），不依赖任何第三方 Python 库。
除 connect/send_cmd/close 三个原语外，还提供 Android 侧的性能采集能力：
内存(/proc/meminfo)、CPU(/proc/stat)、电池(dumpsys battery)、设备属性(getprop)。
内存口径适配 Android，但对外仍返回与基类一致的 {'total','used','free','cache'} 契约。
"""
import logging
import os
import re
import shutil
import subprocess
import time

from .device_base import BaseDevice, load_config

logger = logging.getLogger(__name__)


class AdbDevice(BaseDevice):
    def __init__(self, config=None, host=None, port=None, adb_path=None, timeout=10):
        cfg = (config or load_config()).get('android', {})
        self.host = host or cfg.get('host', '127.0.0.1')
        self.port = int(port if port is not None else cfg.get('port', 5050))
        self.serial = f'{self.host}:{self.port}'
        self.timeout = timeout

        adb_path = adb_path or cfg.get('adb_path', 'adb')
        # 未写绝对路径时在 PATH 中查找，找不到提前报清楚
        self.adb = shutil.which(adb_path) or (
            adb_path if os.path.isabs(adb_path) and os.path.exists(adb_path) else None)
        if not self.adb:
            raise FileNotFoundError(
                f"找不到 adb：{adb_path!r}。请在 settings.yaml 的 android.adb_path "
                f"配置正确路径，或将 platform-tools 加入 PATH。")

    def _run(self, args, timeout=None):
        """执行 adb 子命令，返回 (returncode, stdout, stderr)。"""
        try:
            p = subprocess.run([self.adb] + args,
                               capture_output=True, text=True, encoding='utf-8',
                               errors='ignore', timeout=timeout or self.timeout)
            return p.returncode, p.stdout.strip(), p.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, '', f'命令超时({timeout or self.timeout}s): adb {" ".join(args)}'
        except FileNotFoundError as e:
            return -1, '', str(e)

    def connect(self):
        """建立网络 adb 连接并确认设备在线（device 状态）。"""
        rc, out, err = self._run(['connect', self.serial], timeout=8)
        text = f'{out} {err}'.lower()
        if rc == 0 and ('connected to' in text or 'already connected' in text):
            rc2, state, _ = self._run(['-s', self.serial, 'get-state'])
            if rc2 == 0 and state.strip() == 'device':
                logger.info("AdbDevice 已连接设备: %s", self.serial)
                return True
            logger.error("AdbDevice 已连接但设备状态异常（期望 device，实际 %r）。"
                         "若为 unauthorized，请在设备屏幕上点\"允许调试\"。", state or '?')
            return False
        logger.error("AdbDevice adb connect 失败: %s", out or err)
        return False

    def send_cmd(self, cmd, timeout=None):
        """执行 adb shell 命令，返回 stdout 文本；失败返回空串。"""
        rc, out, err = self._run(['-s', self.serial, 'shell', cmd], timeout=timeout)
        if rc != 0 and err:
            logger.warning("adb shell 命令失败 [%s]: %s", cmd, err)
        return out

    # shell 作为语义化别名，Android 侧调用更直观
    def shell(self, cmd, timeout=None):
        return self.send_cmd(cmd, timeout=timeout)

    # ---------- 内存 ----------

    def get_meminfo(self):
        """解析 /proc/meminfo，返回 total/used/available/free/cache（KB）。"""
        text = self.shell('cat /proc/meminfo')
        kb = {name: int(val)
              for name, val in re.findall(r'^(\w+):\s+(\d+)\s*kB', text, re.M)}
        if 'MemTotal' not in kb or 'MemAvailable' not in kb:
            return None
        total = kb['MemTotal']
        return {
            'total': total,
            'used': total - kb['MemAvailable'],
            'available': kb['MemAvailable'],
            'free': kb.get('MemFree', 0),
            'cache': kb.get('Cached', 0),
        }

    def get_memory_info(self):
        """覆盖基类：适配 Android 内存口径，但保持接口契约不变。"""
        info = self.get_meminfo()
        if info is None:
            logger.warning("无法从 /proc/meminfo 解析出内存数据")
            return None
        return {k: info[k] for k in ('total', 'used', 'free', 'cache')}

    # ---------- CPU ----------

    @staticmethod
    def _parse_cpu_times(stat_text):
        """解析 /proc/stat 首行，返回 (busy_jiffies, total_jiffies)。"""
        m = re.search(r'^cpu\s+([\d\s]+)$', stat_text, re.M)
        if not m:
            return None
        vals = [int(x) for x in m.group(1).split()]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        return total - idle, total

    def get_cpu_usage(self, interval=1.0):
        """两次采样 /proc/stat 做差，返回 CPU 使用率百分比；失败返回 None。"""
        t1 = self._parse_cpu_times(self.shell('cat /proc/stat'))
        time.sleep(interval)
        t2 = self._parse_cpu_times(self.shell('cat /proc/stat'))
        if not t1 or not t2:
            return None
        busy_delta = t2[0] - t1[0]
        total_delta = t2[1] - t1[1]
        return round(busy_delta * 100.0 / total_delta, 1) if total_delta > 0 else 0.0

    # ---------- 电池 ----------

    def get_battery(self):
        """dumpsys battery，返回电量(%)与温度(°C)；无电池设备对应值为 None。"""
        text = self.shell('dumpsys battery')
        level_m = re.search(r'^\s*level:\s*(\d+)', text, re.M)
        temp_m = re.search(r'^\s*temperature:\s*(\d+)', text, re.M)
        return {
            'level': int(level_m.group(1)) if level_m else None,
            'temp': int(temp_m.group(1)) / 10.0 if temp_m else None,  # 0.1°C -> °C
        }

    # ---------- 设备信息 ----------

    def get_props(self):
        """读取常见设备属性。"""
        return {
            '型号': self.shell('getprop ro.product.model'),
            'Android版本': self.shell('getprop ro.build.version.release'),
            '序列号': self.shell('getprop ro.serialno'),
        }

    def close(self):
        self._run(['disconnect', self.serial])
        logger.info("AdbDevice 已断开: %s", self.serial)
