"""pytest 共享 fixture：Linux 串口硬件探测。

默认套件不依赖硬件也能"全绿"：仅当 platform=linux 且串口能打开 **且设备
shell 有应答** 时才运行用例；否则（平台不符 / 无适配器 / 端口被占 /
有端口但无设备响应）自动 skip。
"""
import logging
import os
import re
import time

import pytest
import serial

from core.device_base import load_config
from core.device_controller import get_device

logger = logging.getLogger(__name__)

# 探测总时长：串口能打开 ≠ 有设备，必须收到 shell 计算结果才算可用
_PROBE_TIMEOUT = 2.5
# 探测算式与其唯一结果。不用 echo token：环回链路会原样回传命令本身，
# 而真正的 shell 才会算出结果 6912（命令文本里不含 6912，环回骗不过去）
_PROBE_A, _PROBE_B, _PROBE_RESULT = 1234, 5678, str(1234 + 5678)


def _serial_device_alive(cfg):
    """打开串口并发计算命令，收到 shell 计算结果才认为设备在线。"""
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
                        return True
            else:
                time.sleep(0.02)
        logger.warning("串口 %s 可打开但 %ss 内无有效 shell 应答，视为无设备",
                       dev_cfg['port'], _PROBE_TIMEOUT)
        return False
    except serial.SerialException as e:
        logger.warning("串口 %s 不可用：%s", dev_cfg['port'], e)
        return False
    finally:
        if ser is not None and ser.is_open:
            ser.close()


@pytest.fixture(scope="module")
def device():
    """Linux 串口设备 fixture：平台不符或硬件无应答时自动 skip。"""
    cfg = load_config()
    if cfg.get('platform', 'linux') != 'linux':
        pytest.skip(f"当前 platform={cfg.get('platform')!r}，跳过 Linux 串口用例")

    if not _serial_device_alive(cfg):
        pytest.skip(f"串口 {cfg['device']['port']} 无应答设备，跳过 Linux 串口用例")

    dev = get_device()
    dev.connect()
    yield dev
    dev.close()


def report_dir():
    """当次运行的报告目录（由 run.py 通过环境变量传入；缺省回退 reports/）。"""
    return os.environ.get('CLOUDGAME_REPORT_DIR')
