import serial
import time
import threading
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# データ共有のためのスレッドセーフなキュー
data_queue_combined_value = collections.deque(maxlen=100) # 十の位と一の位を結合した値用

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
            # データの最小長を決定
            # 少なくとも5バイト目まで読む必要があるため、最低6バイト（インデックス0から5）を読むと仮定
            # 実際のデバイスが一度に送るデータフレームの最大長に合わせて調整してください。
            expected_data_length = 6

            if ser.in_waiting >= expected_data_length:
                # 必要なバイト数を読み込む。
                raw_data = ser.read(expected_data_length)

                try:
                    # 4バイト目（インデックス3）と5バイト目（インデックス4）のバイトを取得
                    tens_char_byte = raw_data[3:4]  # 1バイトのbytesオブジェクトとして取得
                    ones_char_byte = raw_data[4:5]  # 1バイトのbytesオブジェクトとして取得

                    # ASCIIバイトを文字列にデコードし、整数に変換
                    tens_digit = int(tens_char_byte.decode('ascii'))
                    ones_digit = int(ones_char_byte.decode('ascii'))

                    # 十の位と一の位を組み合わせて数値化
                    positive_value = tens_digit * 10 + ones_digit

                    # 値の範囲が -20から-90なので、受け取った正の値を負の値に変換
                    # ここが「オフセット無し」の解釈で正しい部分です。
                    actual_value = -positive_value

                    # 値が期待される範囲(-90から-20)にあるか軽くチェック
                    if not (-90 <= actual_value <= -20):
                        print(f"警告: 範囲外の値を受信しました: {actual_value} (元データ: {raw_data.hex()})")


                except (IndexError, ValueError) as e:
                    print(f"データパースエラー: {e} - 受信データ: {raw_data.hex()}")
                    print("ASCII文字が数値に変換できない、またはデータ長が不足している可能性があります。")
                    continue # 不完全なデータはスキップ

                data_queue_combined_value.append(actual_value)
                # print(f"受信: 十の位={tens_digit}, 一の位={ones_digit}, 結合値={actual_value}") # デバッグ用

            else:
                # データが足りない場合は少し待つ
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
    time_points = [current_time_display - (len(data_queue_combined_value) - j -1) * 0.2 for j in range(len(data_queue_combined_value))]

    line_combined_value.set_data(time_points, list(data_queue_combined_value))

    # Y軸の自動調整
    ax.relim()
    ax.autoscale_view(True,True,True)

    # X軸の範囲を調整（最新のデータが右端に来るように）
    if time_points:
        end_time = time_points[-1]
        start_time = end_time - (data_queue_combined_value.maxlen * 0.2)
        ax.set_xlim(start_time, end_time + 0.2)

    return line_combined_value,

if __name__ == "__main__":
    # シリアル通信スレッドを開始
    serial_port = 'COM3' # <-- ご自身の環境に合わせて変更してください (例: '/dev/ttyUSB0')
    baud_rate = 9600     # <-- ご自身のデバイスのボーレートに合わせて変更してください
    serial_thread = threading.Thread(target=read_from_serial, args=(serial_port, baud_rate), daemon=True)
    serial_thread.start()

    # グラフの初期設定
    fig, ax = plt.subplots(1, 1, figsize=(10, 6)) # グラフは一つに集約
    line_combined_value, = ax.plot([], [], 'g-') # 緑色の線でプロット

    ax.set_title('測定値') # より一般的なタイトルに変更
    ax.set_ylabel('値')
    ax.set_xlabel('時間')
    ax.grid(True)

    # アニメーションの開始: 200msごとに更新
    ani = animation.FuncAnimation(fig, animate_with_queue, interval=200, blit=True)

    plt.tight_layout()
    plt.show()
