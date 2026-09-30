"""Android 端设备实现：通过网络 ADB（adb connect host:port）操作设备。

仅依赖外部 adb 可执行文件（platform-tools），不依赖任何第三方 Python 库。
内存口径适配 Android：基类默认解析 BusyBox `free`，这里改用 /proc/meminfo，
但对外仍返回与接口一致的 {'total','used','free','cache'} 契约。
"""
import os
import re
import shutil
import subprocess

from .device_base import DeviceInterface, load_config


class AdbDevice(DeviceInterface):
    def __init__(self, config=None, host=None, port=None, adb_path=None, timeout=10):
        cfg = (config or load_config()).get('android', {})
        self.host = host or cfg.get('host', '127.0.0.1')
        self.port = int(port if port is not None else cfg.get('port', 5555))
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
                print(f'✅ [AdbDevice] 已连接设备: {self.serial}')
                return True
            print(f'❌ [AdbDevice] 已连接但设备状态异常（期望 device，'
                  f'实际 {state or "?"!r}）。若为 unauthorized，请在设备屏幕上点"允许调试"。')
            return False
        print(f'❌ [AdbDevice] adb connect 失败: {out or err}')
        return False

    def send_cmd(self, cmd, timeout=None):
        """执行 adb shell 命令，返回 stdout 文本；失败返回空串。"""
        rc, out, err = self._run(['-s', self.serial, 'shell', cmd], timeout=timeout)
        if rc != 0 and err:
            print(f'⚠️ adb shell 命令失败 [{cmd}]: {err}')
        return out

    # shell 作为语义化别名，Android 侧调用更直观
    def shell(self, cmd, timeout=None):
        return self.send_cmd(cmd, timeout=timeout)

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
            print("⚠️ 无法从 /proc/meminfo 解析出内存数据！")
            return None
        return {k: info[k] for k in ('total', 'used', 'free', 'cache')}

    def close(self):
        self._run(['disconnect', self.serial])
        print(f'🔒 [AdbDevice] 已断开: {self.serial}')
