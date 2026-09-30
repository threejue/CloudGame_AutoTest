import pandas as pd
import matplotlib.pyplot as plt
import csv
import os


MEMORY_CSV_HEADER = ['时间', '总内存(KB)', '已用(KB)', '空闲(KB)', '缓存(KB)']


def log_memory_sample(csv_path, sample):
    """将一次内存采样追加写入 CSV。文件不存在时自动写表头。
    :param csv_path: CSV 路径（建议绝对路径）
    :param sample: dict，含 time/total/used/free/cache（单位 KB）
    :return: True 写入成功；False 失败。
    """
    parent = os.path.dirname(csv_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    new_file = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    try:
        with open(csv_path, 'a', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(MEMORY_CSV_HEADER)
            writer.writerow([sample['time'], sample['total'], sample['used'],
                             sample['free'], sample['cache']])
        return True
    except Exception as e:
        print(f"❌ 写入内存日志失败: {e}")
        return False


def draw_memory_chart(csv_path, output_path, min_free_kb=None):
    """
    根据CSV文件绘制内存趋势图。
    已用/空闲拆为两个子图、各自独立 Y 轴量程（不从 0 起），
    避免基数 ~200000KB 而波动仅几百 KB 时曲线被压成平线。
    :param csv_path: 输入的CSV文件路径
    :param output_path: 输出的图片路径
    :param min_free_kb: 空闲内存告警阈值(KB)，传入则在空闲子图上画阈值线
    """
    # 1. 容错：检查文件是否存在
    if not os.path.exists(csv_path):
        print(f"❌ 找不到数据文件：{csv_path}，请先运行采集脚本！")
        return False

    # 2. 读取CSV，解决中文乱码
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
    except Exception:
        try:
            df = pd.read_csv(csv_path, encoding='gbk')
        except Exception as e:
            print(f"❌ 读取CSV失败：{e}")
            return False

    # 3. 容错：检查列数是否足够
    if len(df.columns) < 4:
        print(f"❌ CSV列数不足，无法解析内存数据。当前列数: {len(df.columns)}")
        return False

    # 4. 提取列
    time_col = df.columns[0]
    used_col = df.columns[2]
    free_col = df.columns[3]
    x, used, free = df[time_col], df[used_col], df[free_col]

    # 5. 上下两个子图共享 X 轴，各自独立 Y 量程
    fig, (ax_used, ax_free) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    # 已用内存
    ax_used.plot(x, used, marker='o', markersize=3, color='red', label='Used (KB)')
    ax_used.axhline(used.mean(), color='red', linestyle='--', alpha=0.4,
                    label=f'mean {used.mean():.0f}')
    ax_used.set_ylabel('Used Memory (KB)')
    ax_used.set_title('Device Memory Trend (Low Memory Alert)')
    ax_used.grid(True, alpha=0.3)
    ax_used.margins(y=0.3)  # Y 轴围绕数据范围留白，微小波动可见
    ax_used.legend(loc='upper right', fontsize=8)

    # 空闲内存：Y 轴始终围绕实际数据设量程，保证微小波动可见
    ax_free.plot(x, free, marker='o', markersize=3, color='green', label='Free (KB)')
    ax_free.axhline(free.mean(), color='green', linestyle='--', alpha=0.4,
                    label=f'mean {free.mean():.0f}')
    f_lo, f_hi = float(free.min()), float(free.max())
    f_pad = (f_hi - f_lo) * 0.3 or max(abs(f_hi) * 0.05, 1.0)
    f_bound_lo, f_bound_hi = f_lo - f_pad, f_hi + f_pad
    ax_free.set_ylim(f_bound_lo, f_bound_hi)
    if min_free_kb is not None:
        if f_bound_lo <= min_free_kb <= f_bound_hi:
            # 阈值落在视野内：直接画线
            ax_free.axhline(min_free_kb, color='orange', linestyle=':', linewidth=2,
                            label=f'threshold {min_free_kb}')
        else:
            # 阈值远离当前数据（很安全或已危险）：文字标注，不拉大 Y 量程
            headroom = f_lo / min_free_kb if min_free_kb else float('inf')
            ax_free.text(0.99, 0.03,
                         f'threshold {min_free_kb} KB | min {f_lo:.0f} KB '
                         f'({headroom:.1f}x headroom)',
                         transform=ax_free.transAxes, ha='right', va='bottom',
                         fontsize=8, color='darkorange',
                         bbox=dict(boxstyle='round,pad=0.3', fc='white',
                                   ec='darkorange', alpha=0.8))
    ax_free.set_ylabel('Free Memory (KB)')
    ax_free.set_xlabel('Time')
    ax_free.grid(True, alpha=0.3)
    ax_free.legend(loc='upper right', fontsize=8)

    plt.setp(ax_free.get_xticklabels(), rotation=45, ha='right')
    fig.tight_layout()

    # 6. 保存图片（使用传入的参数），并关闭画布释放内存
    fig.savefig(output_path)
    plt.close(fig)

    print(f"🎉 图表已生成：{output_path}")
    return True