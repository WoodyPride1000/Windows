import serial
import time
import threading
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# データ共有のためのスレッドセーフなキュー (最大表示点数を100に設定)
data_queue_yaw_angle = collections.deque(maxlen=100)

# シリアルポート読み込み関数
def read_from_serial(ser_port, baud_rate):
    try:
        ser = serial.Serial(ser_port, baud_rate, timeout=0.1)
        print(f"シリアルポート {ser_port} を開きました。")
    except serial.SerialException as e:
        print(f"シリアルポートを開けませんでした: {e}")
        return

    try:
        while True:
            if ser.in_waiting > 0:
                # 改行コード '\n' まで読み込むことを想定
                # マイクロコントローラーから送られるデータが必ず '\n' で終わるようにしてください
                line = ser.readline().decode('ascii').strip() # 例: "123.7\n" を "123.7" に変換

                if line: # 空行でなければ処理
                    try:
                        # 1. 受信した文字列を浮動小数点数に変換
                        raw_yaw_float = float(line)

                        # 2. 小数点以下を四捨五入して1度単位の整数にする
                        # Pythonのround()関数は、小数点以下が0.5の場合、最も近い偶数に丸める「偶数丸め」がデフォルトです。
                        # 一般的な四捨五入（0.5以上で切り上げ）が必要な場合は、`int(raw_yaw_float + 0.5)` のような工夫が必要です。
                        # ただし、負の数の場合は `int(raw_yaw_float - 0.5)` のような処理が必要になり複雑になります。
                        # ここでは、簡潔かつ一般的な数値処理として `round()` を使用します。
                        # もし厳密な「0.5で切り上げ」が必要なら、別途ロジックを検討しましょう。
                        rounded_yaw_angle = round(raw_yaw_float)

                        # # 厳密な四捨五入（0.5以上は常に切り上げ）が必要な場合の例
                        # if raw_yaw_float >= 0:
                        #     rounded_yaw_angle = int(raw_yaw_float + 0.5)
                        # else: # 負の数の場合
                        #     rounded_yaw_angle = int(raw_yaw_float - 0.5)


                    except ValueError:
                        print(f"データパースエラー: 数値に変換できません。受信データ: '{line}'")
                        continue # 不完全なデータはスキップ

                    data_queue_yaw_angle.append(rounded_yaw_angle)
                    # print(f"受信: 生データ={raw_yaw_float}, 丸め後={rounded_yaw_angle}") # デバッグ用

            else:
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("シリアル読み込みスレッドを停止します。")
    finally:
        ser.close()
        print("シリアルポートを閉じました。")

# グラフ更新関数
def animate_with_queue(i):
    current_time_display = time.time()
    # キューに入っているデータの時間点を生成（表示用）
    # 200ms間隔でデータが来ると仮定し、最新のデータを基準に時間を逆算
    time_points = [current_time_display - (len(data_queue_yaw_angle) - j -1) * 0.2 for j in range(len(data_queue_yaw_angle))]

    line_yaw_angle.set_data(time_points, list(data_queue_yaw_angle))

    # Y軸の自動調整
    ax.relim()
    ax.autoscale_view(True,True,True)

    # X軸の範囲を調整（最新のデータが右端に来るように）
    if time_points:
        end_time = time_points[-1]
        start_time = end_time - (data_queue_yaw_angle.maxlen * 0.2)
        ax.set_xlim(start_time, end_time + 0.2)

    return line_yaw_angle,

if __name__ == "__main__":
    # シリアル通信スレッドを開始
    serial_port = 'COM3' # <-- ご自身の環境に合わせて変更してください (例: '/dev/ttyUSB0')
    baud_rate = 9600     # <-- ご自身のデバイスのボーレートに合わせて変更してください
    serial_thread = threading.Thread(target=read_from_serial, args=(serial_port, baud_rate), daemon=True)
    serial_thread.start()

    # グラフの初期設定
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    line_yaw_angle, = ax.plot([], [], 'b-') # 青色の線でプロット

    ax.set_title('MPU6050 ヨー軸角度 (1度単位)')
    ax.set_ylabel('角度 (度)')
    ax.set_xlabel('時間')
    ax.grid(True)
    # ヨー軸角度の一般的な範囲（例: -180度から180度、または0度から360度）に合わせてY軸範囲を固定することも検討
    # ax.set_ylim(-180, 180) # または ax.set_ylim(0, 360)

    # アニメーションの開始: 200msごとに更新
    ani = animation.FuncAnimation(fig, animate_with_queue, interval=200, blit=True)

    plt.tight_layout()
    plt.show()
