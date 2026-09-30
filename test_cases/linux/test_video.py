import logging
import re

import pytest

logger = logging.getLogger(__name__)

# device fixture 由 test_cases/conftest.py 统一提供（含无硬件自动 skip）


def test_video_stream_quality(device):
    """测试视频流质量（延迟与丢包率）"""
    logger.info("正在抓取视频流日志...")

    # 1. 抓取最后 100 行日志（避免卡死）
    res = device.send_cmd("tail -n 100 /tmp/anygame.log")

    # 2. 正则提取 delay_avg 和 package_loss
    delays = re.findall(r'delay_avg:(\d+)', res)
    losses = re.findall(r'package_loss:(\d+)', res)

    # 3. 容错：如果没抓到日志（比如游戏没启动），跳过测试
    if not delays or not losses:
        pytest.skip("⚠️ 未在日志中找到视频流数据，请确认游戏是否正在运行。")

    # 4. 提取最大值进行断言
    max_delay = max([int(d) for d in delays])
    max_loss = max([int(l) for l in losses])

    logger.info("视频流数据：最大平均延迟 = %sms, 最大丢包率 = %s%%", max_delay, max_loss)

    # 5. 核心断言：延迟不超过 50ms，丢包率不超过 2%
    assert max_delay <= 50, f"❌ 延迟过高！最大延迟 {max_delay}ms，超过阈值 50ms"
    assert max_loss <= 2, f"❌ 丢包率过高！最大丢包 {max_loss}%，超过阈值 2%"

    logger.info("视频流质量达标！")
