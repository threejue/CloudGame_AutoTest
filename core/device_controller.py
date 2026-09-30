"""设备工厂：按 config/settings.yaml 的 platform 选择具体后端。

保留 DeviceController 这个历史类名，test_cases 中的
`DeviceController()` / connect() / send_cmd() / get_memory_info() / close()
无需任何修改，实际实例会是 SerialDevice 或 AdbDevice。

也可直接用 create_device(platform=...) 显式指定。
"""
from .device_base import DeviceInterface, load_config
from .serial_device import SerialDevice
from .adb_device import AdbDevice

# platform 配置值 -> 实现类
_BACKENDS = {
    'serial': SerialDevice,      # Linux 串口终端（pyserial）
    'linux_serial': SerialDevice,
    'android': AdbDevice,        # Android 网络 ADB
    'android_adb': AdbDevice,
}


def create_device(platform=None, config=None):
    """创建设备实例。platform 为空时读 settings.yaml 顶层 platform（默认 serial）。"""
    cfg = config or load_config()
    platform = platform or cfg.get('platform', 'serial')
    backend = _BACKENDS.get(str(platform).lower())
    if backend is None:
        raise ValueError(
            f"未知 platform: {platform!r}，可选: {sorted(set(_BACKENDS))}")
    return backend(cfg)


class DeviceController:
    """兼容旧调用的工厂类：DeviceController() 按配置返回真实后端实例。"""

    def __new__(cls, platform=None, config=None):
        return create_device(platform=platform, config=config)


__all__ = ['DeviceController', 'create_device', 'DeviceInterface',
           'SerialDevice', 'AdbDevice']
