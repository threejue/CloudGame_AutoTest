"""pytest 共享 fixture：Linux 串口硬件探测。

默认套件不依赖硬件也能"全绿"，并能容忍"设备刚被前序用例重启"的场景：
- 串口打不开（无适配器/被占用）：立即判定无硬件，用例 skip；
- 串口能打开但 shell 无应答（设备可能正在重启引导）：有界重试等待其回壳；
- 收到 shell 计算结果：设备在线，正常运行。
"""
import logging
import re
import time

import pytest
import serial

from core.device_base import load_config
from core.device_controller import get_device

logger = logging.getLogger(__name__)

# 单次探测时长：串口能打开 ≠ 有设备，必须收到 shell 计算结果才算可用
_PROBE_TIMEOUT = 2.5
# 设备重启后等待回壳的总时长与重试间隔（串口能打开但无应答时才重试）
_REBOOT_WAIT_SEC = 30
_REBOOT_RETRY_INTERVAL = 3
# 探测算式与其唯一结果。不用 echo token：环回链路会原样回传命令本身，
# 而真正的 shell 才会算出结果 6912（命令文本里不含 6912，环回骗不过去）
_PROBE_A, _PROBE_B, _PROBE_RESULT = 1234, 5678, str(1234 + 5678)

# 探测结果三态
ALIVE = 'alive'        # 串口可开且 shell 有应答
NO_PORT = 'no_port'    # 串口打不开（无适配器/被占用）
NO_SHELL = 'no_shell'  # 串口可开但无有效 shell（设备未启动/重启中/环回噪声）


def _probe_once(cfg):
    """单次探测，返回 ALIVE / NO_PORT / NO_SHELL。"""
    dev_cfg = cfg['device']
    ser = None
    try:
        ser = serial.Serial(dev_cfg['port'], dev_cfg['baud'], timeout=0.2,
                            rtscts=False, dsrdtr=False)
        ser.reset_input_buffer()
        # 先敲个回车唤醒可能的 shell，再发算术展开（BusyBox ash 支持 $(( ))）
        ser.write(b'\r\n')
        ser.write(f'echo $(({_PROBE_A}+{_PROBE_B}))\r\n'.encode('utf-8'))

        deadline = time.time() + _PROBE_TIMEOUT
        buf = ''
        while time.time() < deadline:
            n = ser.in_waiting
            if n:
                chunk = ser.read(n).decode('utf-8', errors='ignore')
                buf += chunk
                # 结果独立成行（允许回显命令行共存）；shell 输出必为可打印文本
                if re.search(rf'(?<!\d){_PROBE_RESULT}(?!\d)', buf):
                    printable = sum(1 for c in buf if c in '\r\n\t' or 32 <= ord(c) < 127)
                    if printable / max(len(buf), 1) > 0.9:
                        return ALIVE
            else:
                time.sleep(0.02)
        logger.warning("串口 %s 可打开但 %ss 内无有效 shell 应答",
                       dev_cfg['port'], _PROBE_TIMEOUT)
        return NO_SHELL
    except serial.SerialException as e:
        logger.warning("串口 %s 不可用：%s", dev_cfg['port'], e)
        return NO_PORT
    finally:
        if ser is not None and ser.is_open:
            ser.close()


def wait_for_serial_device(cfg):
    """探测串口设备是否在线。

    端口能打开但 shell 无应答时，按有界间隔重试（容忍设备刚被重启）；
    端口根本打不开则立即放弃（无硬件，不必空等）。
    :return: True 设备在线；False 不可用。
    """
    status = _probe_once(cfg)
    if status == ALIVE:
        return True
    if status == NO_PORT:
        return False

    # NO_SHELL：可能正在重启，有界等待回壳
    port = cfg['device']['port']
    deadline = time.time() + _REBOOT_WAIT_SEC
    while time.time() < deadline:
        logger.info("串口 %s 无 shell 应答，%ss 后重试（等待设备重启完成）...",
                    port, _REBOOT_RETRY_INTERVAL)
        time.sleep(_REBOOT_RETRY_INTERVAL)
        status = _probe_once(cfg)
        if status == ALIVE:
            logger.info("设备已重新回到 shell，继续执行")
            return True
        if status == NO_PORT:
            return False
    logger.warning("等待 %ss 后串口 %s 仍无 shell 应答，视为无设备",
                   _REBOOT_WAIT_SEC, port)
    return False


@pytest.fixture(scope="module")
def device():
    """Linux 串口设备 fixture：平台不符或硬件无应答时自动 skip。"""
    cfg = load_config()
    if cfg.get('platform', 'linux') != 'linux':
        pytest.skip(f"当前 platform={cfg.get('platform')!r}，跳过 Linux 串口用例")

    if not wait_for_serial_device(cfg):
        pytest.skip(f"串口 {cfg['device']['port']} 无应答设备，跳过 Linux 串口用例")

    dev = get_device()
    dev.connect()
    yield dev
    dev.close()


def report_dir():
    """当次运行的报告目录（由 run.py 通过环境变量传入；缺省回退 reports/）。"""
    import os
    return os.environ.get('CLOUDGAME_REPORT_DIR')
