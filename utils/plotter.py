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


def draw_memory_chart(csv_path, output_path):
    """
    根据CSV文件绘制内存趋势图
    :param csv_path: 输入的CSV文件路径
    :param output_path: 输出的图片路径
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

    # 5. 开始画图
    plt.figure(figsize=(10, 5))
    plt.plot(df[time_col], df[used_col], label='Used Memory (KB)', color='red')
    plt.plot(df[time_col], df[free_col], label='Free Memory (KB)', color='green')

    plt.legend()
    plt.title('Device Memory Trend (Low Memory Alert)')
    plt.xlabel('Time')
    plt.ylabel('Memory (KB)')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # 6. 保存图片（使用传入的参数），并关闭画布释放内存
    plt.savefig(output_path)
    plt.close()

    print(f"🎉 图表已生成：{output_path}")
    return True