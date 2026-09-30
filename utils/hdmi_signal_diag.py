"""显示器检测不到游戏机信号源的诊断工具。

针对云游戏终端（嵌入式 Linux）的 HDMI 输出问题，通过串口复用现有
设备驱动，逐层排查视频输出状态并定位根因：

  驱动层   -> DRM / HDMI 驱动是否存在、dmesg 是否有报错
  连接器层 -> /sys/class/drm 下所有连接器及其状态（不限 HDMI）
  HPD 层    -> 显示器热插拔检测（status=connected?）
  DDC 层    -> EDID 能否读取（I2C 通信）
  输出使能  -> connector enabled / DPMS On
  时序层    -> 是否协商出有效显示模式
  帧缓冲层  -> /dev/fb0 模式是否有效
  应用层    -> 游戏进程是否在跑

用法（在项目根目录执行）：
    python -m utils.hdmi_signal_diag
    python -m utils.hdmi_signal_diag --help
"""
import logging
import os
import re
import sys

# 支持以脚本方式直接运行
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.device_base import load_config        # noqa: E402
from core.device_controller import get_device    # noqa: E402
from core.log_setup import setup_logging         # noqa: E402

logger = logging.getLogger(__name__)


class HdmiSignalDiag:
    """逐层采集视频输出状态并分级诊断。"""

    def __init__(self, device):
        self.dev = device
        self.data = {}

    # ---------- 采集 ----------

    def _cmd(self, cmd, default=''):
        """执行命令并剥离串口 shell 对命令本身的回显。"""
        try:
            raw = self.dev.send_cmd(cmd).strip()
        except Exception as e:
            logger.warning("命令执行失败 [%s]: %s", cmd, e)
            return default
        # 交互 shell 会回显命令本身，按行去掉与命令相同的行
        lines = []
        cmd_words = set(cmd.split())
        for ln in raw.splitlines():
            s = ln.strip()
            # 回显行：与命令相同，或只含命令的部分词且不含真实输出特征
            if s == cmd:
                continue
            words = set(s.split())
            if words and words.issubset(cmd_words) and not re.search(
                    r'(connected|disconnect|enabled|disabled|On|Off|HDMI|LVDS|DSI|\d+x\d+|root@)', s):
                continue
            lines.append(s)
        return '\n'.join(lines).strip()

    def collect(self):
        d = {}
        # 1. DRM 子系统
        drm = self._cmd('ls /sys/class/drm 2>/dev/null')
        d['drm_listing'] = drm
        d['has_drm'] = bool(drm) and 'No such' not in drm

        # 2. 枚举所有连接器（不限 HDMI，覆盖 LVDS/DSI/DPI/TV/HDMI 等）
        connectors = []
        if d['has_drm']:
            for name in drm.split():
                if '-' in name and not name.startswith('card') or re.search(
                        r'(HDMI|LVDS|DSI|DPI|TV|DP|VGA)', name, re.I):
                    base = f'/sys/class/drm/{name}'
                    connectors.append({
                        'name': name,
                        'base': base,
                        'status': self._cmd(f'cat {base}/status 2>/dev/null'),
                        'enabled': self._cmd(f'cat {base}/enabled 2>/dev/null'),
                        'dpms': self._cmd(f'cat {base}/dpms 2>/dev/null'),
                        'modes': self._cmd(f'cat {base}/modes 2>/dev/null'),
                        'edid_size': int(self._cmd(
                            f'wc -c < {base}/edid 2>/dev/null') or '0'),
                    })
        d['connectors'] = connectors
        d['hdmi_connectors'] = [c for c in connectors
                                if 'HDMI' in c['name'].upper()]

        # 3. 帧缓冲
        d['has_fb0'] = 'No such' not in self._cmd('ls -l /dev/fb0 2>/dev/null')
        d['fb_modes'] = self._cmd('cat /sys/class/graphics/fb0/modes 2>/dev/null')
        d['fb_var'] = self._cmd('cat /sys/class/graphics/fb0/virtual_size 2>/dev/null')

        # 4. 厂商特有路径（全志 TinaLinux 等平台不走标准 DRM connector）
        d['vendor_paths'] = {
            'disp': self._cmd('ls /sys/class/disp 2>/dev/null'),
            'vdisp': self._cmd('ls /sys/class/vdisp 2>/dev/null'),
            'hdmi_tx': self._cmd('ls /sys/devices/virtual/hdmi 2>/dev/null'),
        }
        # 全志 disp/hdmi 私有节点（存在时才采集）
        d['allwinner'] = {}
        if d['vendor_paths'].get('disp'):
            aw = d['allwinner']
            aw['disp_sys'] = self._cmd(
                'cat /sys/class/disp/disp/attr/sys 2>/dev/null')
            aw['hpd'] = (self._cmd(
                'cat /sys/devices/virtual/hdmi/hdmi/attr/hpd 2>/dev/null')
                or self._cmd('cat /sys/class/disp/disp/attr/hpd 2>/dev/null'))
            aw['hdmi_enable'] = self._cmd(
                'cat /sys/devices/virtual/hdmi/hdmi/attr/enable 2>/dev/null')
            aw['edid'] = self._cmd(
                'cat /sys/devices/virtual/hdmi/hdmi/attr/edid 2>/dev/null | head -c 16')

        # 5. dmesg 中 HDMI/DRM 相关日志（最近的）
        d['dmesg_hdmi'] = self._cmd(
            "dmesg 2>/dev/null | grep -iE 'hdmi|drm|display|edid' | tail -n 15")

        # 6. 应用层：游戏/视频进程
        d['game_procs'] = self._cmd(
            "ps | grep -E 'anygame|mpv|video|player' | grep -v grep")

        self.data = d
        return d

    # ---------- 诊断 ----------

    def diagnose(self):
        d = self.data

        # 0. DRM 子系统不存在
        if not d['has_drm']:
            return ("DRM 子系统不存在 / 视频驱动未加载",
                    "检查内核是否编译 CONFIG_DRM 及 HDMI 驱动模块是否 insmod；"
                    "确认设备树中 HDMI 节点是否被禁用")

        # 1. 无任何连接器（可能走厂商直出路径，如全志 disp/hdmi）
        if not d['connectors']:
            aw = d.get('allwinner') or {}
            if aw:
                # 全志平台专项诊断
                hpd = aw.get('hpd', '').strip()
                enable = aw.get('hdmi_enable', '').strip()
                disp_sys = aw.get('disp_sys', '')
                edid = aw.get('edid', '')

                if hpd in ('0', '', 'low', 'disconnect'):
                    return ("全志 HDMI：HPD 未检测到显示器（hpd=0）",
                            "显示器未告知设备自己已接入。排查：① HDMI 线/换线；"
                            "② 显示器切到对应输入源；③ 换显示器；"
                            "④ 量 HDMI 19 脚 HPD 电平（接入应为高）；"
                            "⑤ 设备端 HPD 检测电路/上拉电阻")
                if enable in ('0', '', 'disable', 'disabled'):
                    return ("全志 HDMI：HDMI 发射器未使能（hdmi enable=0）",
                            f"echo 1 > /sys/devices/virtual/hdmi/hdmi/attr/enable；"
                            f"并检查 disp 是否选择了 HDMI 输出通道")
                if not edid:
                    return ("全志 HDMI：HPD 已通但 EDID 读不到（DDC/I2C 失败）",
                            "检查 HDMI 线 SDA/SCL、显示器 I2C 上拉、直连显示器排除分配器")
                # 链路层正常，看 disp 输出通道与应用
                if d['has_fb0'] and d['fb_modes'] and d['game_procs']:
                    return ("全志 HDMI：HPD 正常、HDMI 已使能、fb0 有模式、游戏在跑，"
                            "链路层看似正常",
                            "若仍无画面：① 确认 disp 是否将画面路由到 HDMI（cat "
                            "/sys/class/disp/disp/attr/sys 看输出设备）；"
                            "② 应用是否渲染到 fb0；③ 尝试切换 disp 输出通道；"
                            "④ 换显示器/直连排除兼容性")
                return (f"全志 HDMI：hpd={hpd or '?'} enable={enable or '?'} "
                        f"fb_modes={d['fb_modes'][:30] or '(空)'}",
                        "结合上方数值排查：HPD/使能/帧缓冲/应用渲染目标")

            if d['has_fb0'] and d['fb_modes']:
                return (f"DRM 无连接器，但 framebuffer 已配模式({d['fb_modes'][:40]})；"
                        f"设备可能走厂商 HDMI 直出路径",
                        f"HDMI 可能由厂商驱动直控（非标准 DRM connector）。"
                        f"检查：① dmesg 中 HDMI 相关日志；② 厂商特有节点 "
                        f"/sys/class/disp / /sys/devices/virtual/hdmi；"
                        f"③ 确认应用渲染目标是否是 fb0；④ 查 HDMI PHY/transmitter 是否使能")
            return ("DRM 存在但未枚举到任何连接器",
                    "设备树中视频输出节点可能未使能，或驱动 probe 失败；"
                    "查看 dmesg | grep -i hdmi/drm 的报错")

        # 优先分析 HDMI 连接器；没有则用第一个连接器
        cands = d['hdmi_connectors'] or d['connectors']
        c = cands[0]

        # 2. HPD：显示器未被检测到
        if c['status'] == 'disconnected':
            return (f"HPD 未检测到显示器：{c['name']} status=disconnected",
                    "按序排查：① HDMI 线是否插紧/换线；② 显示器切到对应输入源；"
                    "③ 换显示器排除显示器侧 HPD 故障；④ 量 HDMI 19 脚 HPD 电平"
                    "（接入时应为高）；⑤ 检查设备端 HPD 检测电路/上拉")

        if c['status'] != 'connected':
            return (f"连接器状态异常：{c['name']} status={c['status']!r}",
                    "非 connected 的状态通常意味驱动异常或时序未稳定，查看 dmesg")

        # 3. 输出被软件禁用
        if c['enabled'] != 'enabled':
            return (f"输出被软件禁用：{c['name']} enabled={c['enabled']!r}",
                    f"echo enabled > {c['base']}/enabled; "
                    f"echo on > {c['base']}/dpms")

        # 4. DPMS 关闭
        if c['dpms'] and c['dpms'] != 'On':
            return (f"显示电源管理关闭：{c['name']} dpms={c['dpms']!r}",
                    f"echo on > {c['base']}/dpms")

        # 5. EDID 读不到（DDC/I2C 失败）
        if c['edid_size'] == 0:
            return (f"无法读取显示器 EDID：{c['name']} edid_size=0",
                    "HPD 已通但 DDC/I2C 失败：① 检查 HDMI 线 SDA/SCL；"
                    "② 确认显示器 I2C 上拉；③ 劣质分配器/切换器不带 DDC，直连试；"
                    "④ 量 5V 供电是否正常")

        # 6. 无有效显示模式
        if not c['modes']:
            return (f"未协商出任何显示模式：{c['name']} modes 为空",
                    "EDID 可读但模式列表为空，通常是驱动未解析 EDID 或过滤过严；"
                    "查看 dmesg 中 drm/hdmi 的模式过滤日志")

        # 7. 驱动层正常 -> 应用层
        if not d['game_procs']:
            return ("HDMI 链路正常（已连接/使能/有模式/EDID可读），但未发现游戏/视频进程",
                    "启动游戏或视频应用，确认其是否向 fb0 或 DRM 提交画面；"
                    "检查应用日志是否有画面输出报错")

        if d['has_fb0'] and not d['fb_modes']:
            return ("HDMI 链路正常、游戏在跑，但 framebuffer 无有效模式",
                    "确认 fb0 模式：fbset 或 cat /sys/class/graphics/fb0/modes；"
                    "若为空，应用可能走 DRM plane 未用 fbcon，需确认应用渲染目标")

        return ("HDMI 链路各项正常（已连接/使能/DPMS On/有模式/EDID可读/游戏在跑）",
                "若仍无画面：① 显示器切到正确输入源；② 换显示器排除兼容性；"
                "③ 接了分配器/采集卡则直连显示器试；④ 确认应用是否向该连接器"
                "提交 framebuffer（可能渲染到 offscreen plane）")

    # ---------- 报告 ----------

    def print_report(self):
        d = self.data
        print("=" * 60)
        print("HDMI 信号源诊断报告")
        print("=" * 60)

        print(f"\n[DRM 子系统] {'存在' if d['has_drm'] else '不存在'}")
        if d['connectors']:
            for c in d['connectors']:
                tag = 'HDMI' if 'HDMI' in c['name'].upper() else '其他'
                print(f"\n[连接器-{tag}] {c['name']}")
                print(f"  status  : {c['status'] or '(空)'}")
                print(f"  enabled : {c['enabled'] or '(空)'}")
                print(f"  dpms    : {c['dpms'] or '(空)'}")
                print(f"  edid    : {c['edid_size']} bytes "
                      f"{'(可读)' if c['edid_size'] else '(读不到)'}")
                print(f"  modes   : {c['modes'][:120] or '(空)'}")
        else:
            print("  未发现任何 DRM 连接器")

        print(f"\n[Framebuffer] fb0={'存在' if d['has_fb0'] else '不存在'}")
        print(f"  modes: {d['fb_modes'][:80] or '(空)'}")
        print(f"  var  : {d['fb_var'] or '(空)'}")

        vp = {k: v for k, v in d['vendor_paths'].items() if v}
        if vp:
            print(f"\n[厂商特有节点] {vp}")

        aw = d.get('allwinner') or {}
        if aw:
            print(f"\n[全志 disp/hdmi]")
            print(f"  hpd         : {aw.get('hpd', '(空)')}")
            print(f"  hdmi enable : {aw.get('hdmi_enable', '(空)')}")
            print(f"  edid(前16B) : {aw.get('edid', '(空)')}")
            print(f"  disp sys    : {(aw.get('disp_sys') or '(空)')[:200]}")

        if d['dmesg_hdmi']:
            print(f"\n[dmesg HDMI/DRM 相关]")
            for ln in d['dmesg_hdmi'].splitlines():
                print(f"  {ln}")

        print(f"\n[应用进程] {d['game_procs'][:120] or '(无游戏/视频进程)'}")

        root_cause, action = self.diagnose()
        print("\n" + "-" * 60)
        print(f"根因定位: {root_cause}")
        print(f"下一步  : {action}")
        print("=" * 60)
        return root_cause, action


def main():
    setup_logging()
    if '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        return 0

    cfg = load_config()
    if cfg.get('platform', 'linux') != 'linux':
        print(f"当前 platform={cfg.get('platform')!r}，HDMI 诊断仅适用于 Linux 串口设备")
        return 1

    print("正在通过串口连接设备并采集视频输出状态...")
    try:
        dev = get_device()
        dev.connect()
    except Exception as e:
        print(f"设备连接失败: {e}")
        return 1

    try:
        diag = HdmiSignalDiag(dev)
        diag.collect()
        diag.print_report()
        return 0
    finally:
        dev.close()


if __name__ == '__main__':
    sys.exit(main())
