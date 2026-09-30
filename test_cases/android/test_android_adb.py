"""AdbDevice 的 ADB 连接与内存读取测试。

分两层：
- 离线单测：mock adb 子进程返回，验证连接状态判定、shell 调用、
  /proc/meminfo 解析与内存契约，无需真机，CI/无设备环境可跑；
- 真机集成测试（marker: integration）：仅当网络 ADB 设备在线时运行，
  设备不在线自动 skip；run.py 默认以 -m "not integration" 排除。

运行：
    pytest test_cases/android/test_android_adb.py                 # 离线单测（集成自动 skip）
    pytest test_cases/android/test_android_adb.py -m integration  # 只跑真机集成
"""
import shutil
import subprocess

import pytest

from core.adb_device import AdbDevice
from core.device_base import load_config

MEMINFO_SAMPLE = (
    "MemTotal:        3000000 kB\n"
    "MemFree:          500000 kB\n"
    "MemAvailable:    1200000 kB\n"
    "Buffers:           10000 kB\n"
    "Cached:           900000 kB\n"
)


# ---------------------------------------------------------------------------
# 离线单测：不依赖真机，mock 掉 adb 子进程
# ---------------------------------------------------------------------------

@pytest.fixture
def adb_dev(monkeypatch):
    """构造 AdbDevice，adb 路径与所有子进程调用均被 mock。"""
    monkeypatch.setattr('core.adb_device.shutil.which',
                        lambda name: r'C:\tools\adb.exe')
    return AdbDevice(host='10.0.0.1', port=5050)


def test_adb_not_found_raises(monkeypatch):
    """PATH 中找不到 adb 时构造应抛 FileNotFoundError（提前报清楚）。"""
    monkeypatch.setattr('core.adb_device.shutil.which', lambda name: None)
    with pytest.raises(FileNotFoundError):
        AdbDevice(host='10.0.0.1', adb_path='not-an-adb')


def test_connect_success(adb_dev):
    """connect 成功 + get-state=device => True。"""
    def fake_run(args, timeout=None):
        if args[0] == 'connect':
            return 0, f'connected to {adb_dev.serial}', ''
        if args[-1] == 'get-state':
            return 0, 'device', ''
        return 1, '', 'unexpected call'

    adb_dev._run = fake_run
    assert adb_dev.connect() is True


def test_connect_unauthorized(adb_dev):
    """已 connect 但状态 unauthorized/offline => False（而非误判成功）。"""
    def fake_run(args, timeout=None):
        if args[0] == 'connect':
            return 0, f'connected to {adb_dev.serial}', ''
        return 0, 'unauthorized', ''

    adb_dev._run = fake_run
    assert adb_dev.connect() is False


def test_connect_refused(adb_dev):
    """adb connect 直接失败（目标拒绝）=> False。"""
    adb_dev._run = lambda args, timeout=None: (1, '', 'cannot connect: 10061')
    assert adb_dev.connect() is False


def test_send_cmd_invokes_adb_shell(adb_dev):
    """send_cmd 应拼成 adb -s <serial> shell <cmd> 并回传 stdout。"""
    seen = {}

    def fake_run(args, timeout=None):
        seen['args'] = args
        return 0, 'hello', ''

    adb_dev._run = fake_run
    assert adb_dev.send_cmd('echo hello') == 'hello'
    # _run 收到的是 adb 之后的参数（adb 路径在 _run 内部拼接）
    assert seen['args'] == ['-s', adb_dev.serial, 'shell', 'echo hello']


def test_get_meminfo_parse(adb_dev):
    """/proc/meminfo 各字段正确解析，used=total-available。"""
    adb_dev.shell = lambda cmd, timeout=None: (
        MEMINFO_SAMPLE if cmd == 'cat /proc/meminfo' else '')
    info = adb_dev.get_meminfo()
    assert info == {
        'total': 3000000,
        'used': 1800000,      # 3000000 - 1200000
        'available': 1200000,
        'free': 500000,
        'cache': 900000,
    }


def test_memory_info_contract(adb_dev):
    """get_memory_info 必须返回与 BaseDevice 一致的 4 键契约，
    与串口后端结构对齐，上层 test_cases/utils 无需感知后端。"""
    adb_dev.shell = lambda cmd, timeout=None: (
        MEMINFO_SAMPLE if cmd == 'cat /proc/meminfo' else '')
    contract = adb_dev.get_memory_info()
    assert set(contract) == {'total', 'used', 'free', 'cache'}
    assert contract['total'] == 3000000
    assert contract['used'] == 1800000
    assert contract['free'] == 500000
    assert contract['cache'] == 900000
    assert adb_dev.get_free_memory() == 500000


def test_get_meminfo_empty_output(adb_dev):
    """设备无响应/输出为空时解析返回 None，旧接口返回 0，不抛异常。"""
    adb_dev.shell = lambda cmd, timeout=None: ''
    assert adb_dev.get_meminfo() is None
    assert adb_dev.get_memory_info() is None
    assert adb_dev.get_free_memory() == 0


# ---------------------------------------------------------------------------
# 真机集成测试：需要一台在线的网络 ADB 安卓设备，否则自动 skip
# ---------------------------------------------------------------------------

def _online_serials(adb_path):
    """列出 adb devices 中状态为 device 的序列号。"""
    try:
        p = subprocess.run([adb_path, 'devices'], capture_output=True,
                           text=True, timeout=5)
    except Exception:
        return []
    serials = []
    for line in p.stdout.splitlines()[1:]:  # 跳过 "List of devices attached"
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            serials.append(parts[0])
    return serials


@pytest.fixture
def real_device():
    cfg = load_config()['android']
    adb_on_path = shutil.which(cfg['adb_path'])
    if not adb_on_path:
        pytest.skip('PATH 中找不到 adb，跳过真机集成测试')

    host, port = cfg['host'], int(cfg['port'])
    # 先快速探测：完全没有设备在线时立即 skip，避免 connect 空等超时
    if not _online_serials(adb_on_path):
        pytest.skip(f'当前无任何 adb 设备在线（目标 {host}:{port}），跳过真机集成测试')

    dev = AdbDevice(host=host, port=port, adb_path=cfg['adb_path'])
    if not dev.connect():
        pytest.skip(f'网络 ADB 设备 {host}:{port} 连接失败，跳过真机集成测试')
    yield dev
    dev.close()


@pytest.mark.integration
def test_real_device_connect_and_memory(real_device):
    """真机：验证 ADB 连接可用且内存读数自洽。"""
    info = real_device.get_meminfo()
    assert info is not None, '读取 /proc/meminfo 失败（设备是否已 root/授权？）'
    assert info['total'] > 0, '总内存应大于 0'
    assert 0 <= info['used'] <= info['total'], '已用内存应落在 [0, total]'
    assert 0 < info['available'] <= info['total'], '可用内存应落在 (0, total]'

    contract = real_device.get_memory_info()
    assert set(contract) == {'total', 'used', 'free', 'cache'}
    assert contract['total'] == info['total']
