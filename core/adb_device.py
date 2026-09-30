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

    # ---------- 重启与等待 ----------

    def reboot(self):
        """通过 adb reboot 重启设备（而非 shell reboot），更可靠。"""
        rc, out, err = self._run(['reboot'], timeout=5)
        logger.info("AdbDevice 已发送 reboot: %s", out or err)
        return rc == 0

    def wait_for_device(self, timeout=120):
        """等待设备重新上线（adb get-state=device）。
        reboot 后网络 ADB 不会自动重连，因此循环中会主动 adb connect。
        :return: True 设备在 timeout 内上线且 boot_completed；False 超时。
        """
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            # 主动重连（reboot 后网络设备需要重新 adb connect）
            self._run(['connect', self.serial], timeout=5)
            rc, state, _ = self._run(['-s', self.serial, 'get-state'], timeout=3)
            if rc == 0 and state.strip() == 'device':
                boot = self.shell('getprop sys.boot_completed', timeout=3).strip()
                if boot == '1':
                    return True
            time.sleep(2)
        return False

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

    # ---------- 压力测试 ----------

    def stress_cpu_start(self, workers=None):
        """启动 CPU 压力进程（yes > /dev/null）。
        :param workers: 压力进程数，默认 = CPU 核心数
        :return: 启动的进程数
        """
        if workers is None:
            cores = self.shell('nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo').strip()
            workers = int(cores) if cores.isdigit() else 4
        # 用 sh -c 后台起多个 yes，避免依赖 stress 工具
        self.shell(
            f'for i in $(seq 1 {workers}); do yes > /dev/null & done')
        logger.info("CPU 压力启动: %s 个 yes 进程", workers)
        return workers

    def stress_mem_start(self, size_mb, duration_sec=0):
        """占用内存：向 /dev/shm 写入指定大小的文件。
        :param size_mb: 占用内存大小(MB)
        :param duration_sec: 0=持续占用直到 stop；>0=N 秒后自动释放
        """
        # 先清理可能残留的压力文件
        self.shell('rm -f /dev/shm/cg_stress_mem 2>/dev/null')
        if duration_sec > 0:
            self.shell(
                f'dd if=/dev/zero of=/dev/shm/cg_stress_mem bs=1M count={size_mb} '
                f'2>/dev/null & sleep {duration_sec}; rm -f /dev/shm/cg_stress_mem &')
        else:
            self.shell(
                f'dd if=/dev/zero of=/dev/shm/cg_stress_mem bs=1M count={size_mb} 2>/dev/null')
        logger.info("内存压力启动: 占用 %s MB (%s)", size_mb,
                    f"{duration_sec}s 后自动释放" if duration_sec else "持续")

    def stress_stop(self):
        """停止所有压力进程并释放内存。"""
        self.shell('pkill -9 yes 2>/dev/null; rm -f /dev/shm/cg_stress_mem 2>/dev/null')
        logger.info("压力测试已停止，已清理 yes 进程与 /dev/shm/cg_stress_mem")

    # ---------- 画面监控（帧率 / 延迟 / 丢包） ----------

    def get_refresh_rate(self):
        """读取屏幕刷新率（Hz），来自 SurfaceFlinger。"""
        out = self.shell('dumpsys SurfaceFlinger --latency')
        # 第一行通常是 vsync period（纳秒）
        lines = out.strip().splitlines()
        if lines:
            try:
                period_ns = int(lines[0].split()[0])
                if period_ns > 0:
                    return round(1_000_000_000 / period_ns, 1)
            except (ValueError, IndexError):
                pass
        return None

    def get_foreground_package(self):
        """获取当前前台应用包名（用于 gfxinfo 监控）。"""
        out = self.shell('dumpsys window | grep mCurrentFocus')
        m = re.search(r'(\w+(?:\.\w+)+)/', out)
        return m.group(1) if m else None

    def get_fps(self, package=None, duration=3.0):
        """估算当前帧率（FPS）。
        优先用两次 dumpsys gfxinfo <pkg> 的已渲染帧数差 / 时间差；
        若 SurfaceView 直出（gfxinfo 帧数不增长），回退到 SurfaceFlinger layer
        的 present 时间戳计算；都不行时返回屏幕刷新率。
        """
        pkg = package or self.get_foreground_package()
        if not pkg:
            return self.get_refresh_rate()
        # 1) gfxinfo 帧计数差值
        def frame_count():
            out = self.shell(f'dumpsys gfxinfo {pkg}')
            m = re.search(r'Total frames rendered:\s*(\d+)', out)
            return int(m.group(1)) if m else 0
        c1 = frame_count()
        time.sleep(duration)
        c2 = frame_count()
        if c2 > c1:
            return round((c2 - c1) / duration, 1)
        # 2) SurfaceFlinger layer present 时间戳（SurfaceView 场景）
        fps = self._fps_from_sf_layer(pkg)
        if fps:
            return fps
        # 3) 回退刷新率
        return self.get_refresh_rate()

    def _fps_from_sf_layer(self, package):
        """从 SurfaceFlinger 指定包的 layer present 时间戳估算 FPS。"""
        list_out = self.shell('dumpsys SurfaceFlinger --list')
        layer = None
        for line in list_out.splitlines():
            if package in line and 'SurfaceView' in line:
                layer = line.strip()
                break
        if not layer:
            return None
        out = self.shell(f'dumpsys SurfaceFlinger --latency "{layer}"')
        # 第一行 vsync period，之后 127 行各 3 列时间戳（ns）
        ts = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    t = int(parts[1])  # 第 2 列是 present 时间戳
                    if t > 0:
                        ts.append(t)
                except ValueError:
                    pass
        if len(ts) < 2:
            return None
        ts.sort()
        intervals = [(ts[i+1] - ts[i]) / 1_000_000 for i in range(len(ts)-1)
                     if ts[i+1] > ts[i]]
        if not intervals:
            return None
        avg_interval = sum(intervals) / len(intervals)
        return round(1000 / avg_interval, 1) if avg_interval > 0 else None

    def get_frame_latency(self, package=None):
        """帧延迟统计（p50/p95/p99，单位 ms）。
        直接解析 dumpsys gfxinfo <pkg> 输出的百分位数字段，比 framestats 更可靠。
        包名为空时自动取前台应用；无数据时返回 None。
        """
        pkg = package or self.get_foreground_package()
        if not pkg:
            return None
        out = self.shell(f'dumpsys gfxinfo {pkg}')
        result = {}
        for pct in ('50th', '90th', '95th', '99th'):
            m = re.search(rf'{pct} percentile:\s*(\d+)ms', out)
            if m:
                result['p' + pct.rstrip('th')] = int(m.group(1))
        # 卡顿率
        jm = re.search(r'Janky frames:\s*\d+\s*\(([\d.]+)%\)', out)
        if jm:
            result['jank_pct'] = round(float(jm.group(1)), 2)
        return result if result else None

    def get_net_drops(self):
        """读取各网卡的丢包/错误计数，用于两次采样做差。
        返回 {iface: {'rx_err','rx_drop','tx_err','tx_drop'}}。
        """
        out = self.shell('cat /proc/net/dev')
        result = {}
        for line in out.splitlines()[2:]:  # 跳过两行表头
            if ':' not in line:
                continue
            iface, stats = line.split(':', 1)
            cols = stats.split()
            if len(cols) < 16:
                continue
            result[iface.strip()] = {
                'rx_bytes': int(cols[0]),
                'rx_err': int(cols[2]),
                'rx_drop': int(cols[3]),
                'tx_bytes': int(cols[8]),
                'tx_err': int(cols[10]),
                'tx_drop': int(cols[11]),
            }
        return result

    @staticmethod
    def diff_net_drops(before, after):
        """计算两次 get_net_drops 的丢包增量，返回各接口的 drops 总和。"""
        total = {'rx_err': 0, 'rx_drop': 0, 'tx_err': 0, 'tx_drop': 0}
        for iface, a in after.items():
            b = before.get(iface, {})
            for k in total:
                total[k] += max(0, a.get(k, 0) - b.get(k, 0))
        return total

    def close(self):
        self._run(['disconnect', self.serial])
        logger.info("AdbDevice 已断开: %s", self.serial)
