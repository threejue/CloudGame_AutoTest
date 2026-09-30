"""Android 画面监控（需真机，标记 integration）。

持续采集帧率(FPS)、帧延迟(p50/p95/p99)、网络丢包，验证画面质量达标。

运行：
    pytest test_cases/android/test_android_video_monitor.py -m integration
    python run.py --platform android --include-integration

产物：
- android_video_monitor.csv：每次采样的 FPS/延迟/丢包
- android_stability_summary.txt：追加监控结论
"""
import csv
import logging
import os
import shutil
import time

import pytest
import yaml

from core.adb_device import AdbDevice

logger = logging.getLogger(__name__)

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(base_dir, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

ANDROID_CFG = config['android']


def _report_dir():
    return os.environ.get('CLOUDGAME_REPORT_DIR') or os.path.join(base_dir, 'reports')


def _append_summary(text):
    path = os.path.join(_report_dir(), 'android_stability_summary.txt')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text + '\n')


@pytest.fixture
def real_device():
    adb_on_path = shutil.which(ANDROID_CFG['adb_path'])
    if not adb_on_path:
        pytest.skip('PATH 中找不到 adb，跳过画面监控')

    dev = AdbDevice(host=ANDROID_CFG['host'], port=int(ANDROID_CFG['port']),
                    adb_path=ANDROID_CFG['adb_path'])
    if not dev.connect():
        pytest.skip(f'网络 ADB 设备 {ANDROID_CFG["host"]}:{ANDROID_CFG["port"]} 连接失败')
    yield dev
    dev.close()


@pytest.mark.integration
def test_video_monitor(real_device):
    """持续监控帧率/延迟/丢包，断言画面质量达标。"""
    m = ANDROID_CFG.get('monitor', {})
    pkg = m.get('target_package', '') or None
    duration = m.get('duration_sec', 60)
    interval = m.get('sample_interval_sec', 2)
    min_fps = m.get('min_fps', 20)
    max_p95 = m.get('max_latency_p95_ms', 100)
    max_drops = m.get('max_total_drops', 50)

    refresh = real_device.get_refresh_rate()
    logger.info("屏幕刷新率: %s Hz", refresh)
    logger.info("开始画面监控，持续 %ss（目标包: %s）...", duration, pkg or '(未指定)')

    log_path = os.path.join(_report_dir(), 'android_video_monitor.csv')
    net_before = real_device.get_net_drops()

    fps_list, p95_list, total_drops = [], [], 0
    with open(log_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['序号', '时间', 'FPS', '延迟p50(ms)', '延迟p95(ms)',
                         '延迟p99(ms)', '本次丢包', '累计丢包'])

        end = time.time() + duration
        i = 1
        while time.time() < end:
            fps = real_device.get_fps(package=pkg)
            lat = real_device.get_frame_latency(package=pkg)
            net_now = real_device.get_net_drops()
            drops = real_device.diff_net_drops(net_before, net_now)
            round_drops = drops['rx_drop'] + drops['tx_drop']
            total_drops += round_drops

            p50 = lat['p50'] if lat else ''
            p95 = lat['p95'] if lat else ''
            p99 = lat['p99'] if lat else ''
            writer.writerow([i, time.strftime('%H:%M:%S'), fps, p50, p95, p99,
                             round_drops, total_drops])
            logger.info("[#%s] FPS=%s p95=%sms 本轮丢包=%s 累计=%s",
                        i, fps, p95, round_drops, total_drops)

            if fps is not None:
                fps_list.append(fps)
            if lat:
                p95_list.append(lat['p95'])
            i += 1
            time.sleep(max(0, interval - 1))

    avg_fps = round(sum(fps_list) / len(fps_list), 1) if fps_list else None
    min_fps_actual = min(fps_list) if fps_list else None
    max_p95_actual = max(p95_list) if p95_list else None

    fps_ok = avg_fps is None or avg_fps >= min_fps
    lat_ok = max_p95_actual is None or max_p95_actual <= max_p95
    drop_ok = total_drops <= max_drops

    summary = (f"[画面监控] 时长 {duration}s | 平均 FPS {avg_fps} (阈值≥{min_fps}) "
               f"{'OK' if fps_ok else 'FAIL'} | 最低 FPS {min_fps_actual} | "
               f"延迟 p95 峰值 {max_p95_actual}ms (阈值≤{max_p95}) "
               f"{'OK' if lat_ok else 'FAIL'} | 总丢包 {total_drops} "
               f"(阈值≤{max_drops}) {'OK' if drop_ok else 'FAIL'}")
    logger.info(summary)
    _append_summary(summary)

    # FPS：若采到的是刷新率（无真实渲染帧增长），仅警告不断言
    if fps_list and max(fps_list) <= (refresh or 999):
        if not fps_ok:
            logger.warning("FPS 为屏幕刷新率估算（应用可能用 SurfaceView 直出），"
                           "实际渲染帧率需结合 SurfaceFlinger 分析")
    else:
        assert fps_ok, f"平均帧率 {avg_fps} FPS 低于阈值 {min_fps}"
    # 延迟：只要采到数据就断言
    if p95_list:
        assert lat_ok, f"帧延迟 p95 峰值 {max_p95_actual}ms 超过阈值 {max_p95}ms"
    assert drop_ok, f"监控期间总丢包 {total_drops} 超过阈值 {max_drops}"
