"""设备工厂：按 config/settings.yaml 的 platform 返回具体驱动实例。

platform 取值：
    'linux'   -> SerialDevice（嵌入式 Linux 串口终端，pyserial）
    'android' -> AdbDevice（Android 网络 ADB）

用法：
    from core.device_controller import get_device

    with get_device() as dev:          # 按配置文件选择
        print(dev.send_cmd("uptime"))

    dev = get_device(platform='android')  # 显式指定
    dev.connect(); ...; dev.close()
"""
from .device_base import BaseDevice, load_config
from .serial_device import SerialDevice
from .adb_device import AdbDevice

# platform 配置值 -> 实现类（'serial' 作为 'linux' 的历史别名保留）
_BACKENDS = {
    'linux': SerialDevice,
    'serial': SerialDevice,
    'android': AdbDevice,
}


def get_device(platform=None, config=None):
    """工厂函数：返回一个未连接的具体设备实例（调用方负责 connect/close，
    或直接配合 with 使用）。"""
    cfg = config or load_config()
    platform = platform or cfg.get('platform', 'linux')
    backend = _BACKENDS.get(str(platform).lower())
    if backend is None:
        raise ValueError(
            f"未知 platform: {platform!r}，可选: {sorted(set(_BACKENDS))}")
    return backend(cfg)


__all__ = ['get_device', 'BaseDevice', 'SerialDevice', 'AdbDevice']
