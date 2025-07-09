import time
import math
import threading
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from smbus2 import SMBus # For MPU6050 communication
import serial # For USB serial communication for temperature sensor

# --- MPU6050 Class (as provided) ---
class MPU6050:
    def __init__(self, bus_id=1, address=0x68):
        self.bus_id = bus_id
        self.address = address
        self.bus = SMBus(self.bus_id)
        self.PWR_MGMT_1 = 0x6B
        self.ACCEL_XOUT_H = 0x3B
        self.GYRO_XOUT_H = 0x43
        self.TEMP_OUT_H = 0x41
        self.bus.write_byte_data(self.address, self.PWR_MGMT_1, 0)

    def read_i2c_word(self, reg):
        high = self.bus.read_byte_data(self.address, reg)
        low = self.bus.read_byte_data(self.address, reg + 1)
        value = (high << 8) | low
        if value >= 0x8000:
            value = -((65535 - value) + 1)
        return value

    def get_accel(self):
        return {
            'x': self.read_i2c_word(self.ACCEL_XOUT_H) / 16384.0,
            'y': self.read_i2c_word(self.ACCEL_XOUT_H + 2) / 16384.0,
            'z': self.read_i2c_word(self.ACCEL_XOUT_H + 4) / 16384.0
        }

    def get_gyro(self):
        return {
            'x': self.read_i2c_word(self.GYRO_XOUT_H) / 131.0,
            'y': self.read_i2c_word(self.GYRO_XOUT_H + 2) / 131.0,
            'z': self.read_i2c_word(self.GYRO_XOUT_H + 4) / 131.0
        }

    def get_temp(self):
        raw_temp = self.read_i2c_word(self.TEMP_OUT_H)
        return raw_temp / 340.0 + 36.53

    def close(self):
        self.bus.close()

# --- データ共有のためのキュー ---
# グラフは散布図になるため、X, Yデータをペアで保持
# (X, Y) は (角度, 温度) のペアになる
data_queue_plot_points = collections.deque(maxlen=100) # 最大100個のデータペアを表示

# スレッド間でデータを渡すための最新値保持変数 (シンプルな同期)
latest_yaw_angle = 0.0
latest_temperature = -999.0 # 初期値は無効な値とする

# ロック機構 (データ競合防止のため)
data_lock = threading.Lock()

# --- MPU6050 データ取得・処理スレッド ---
def read_mpu6050_data_thread(mpu):
    global latest_yaw_angle, data_lock
    yaw = 0.0
    last_time = time.time()
    try:
        while True:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            gyro_data = mpu.get_gyro()
            
            delta_yaw = gyro_data['z'] * dt
            yaw += delta_yaw

            # ヨー角を 0度から360度 の範囲に正規化
            yaw = yaw % 360
            if yaw < 0:
                yaw += 360

            # 小数点以下を四捨五入して1度単位の整数にする
            rounded_yaw_angle = round(yaw)

            with data_lock:
                latest_yaw_angle = rounded_yaw_angle

            # 約200ms間隔でデータを取得
            time.sleep(max(0, 0.2 - dt))

    except KeyboardInterrupt:
        print("MPU6050 データ取得スレッドを停止します。")
    except Exception as e:
        print(f"MPU6050 データ取得中にエラーが発生しました: {e}")
    finally:
        mpu.close()
        print("MPU6050 バスを閉じました。")

# --- USB シリアル 温度データ取得・処理スレッド ---
def read_temperature_data_thread(serial_port, baud_rate):
    global latest_temperature, data_lock
    try:
        ser = serial.Serial(serial_port, baud_rate, timeout=0.1)
        print(f"シリアルポート {serial_port} を開きました。")
    except serial.SerialException as e:
        print(f"シリアルポート '{serial_port}' を開けませんでした: {e}")
        print("温度センサーのシリアルポート名を確認してください。")
        return

    try:
        while True:
            expected_data_length = 6 

            if ser.in_waiting >= expected_data_length:
                raw_data = ser.read(expected_data_length)

                try:
                    tens_char_byte = raw_data[3:4]
                    ones_char_byte = raw_data[4:5]

                    tens_digit = int(tens_char_byte.decode('ascii'))
                    ones_digit = int(ones_char_byte.decode('ascii'))

                    positive_value = tens_digit * 10 + ones_digit
                    actual_temperature = -positive_value

                    if not (-90 <= actual_temperature <= -20):
                        print(f"警告: 範囲外の温度値を受信しました: {actual_temperature} (元データ: {raw_data.hex()})")

                    with data_lock:
                        latest_temperature = actual_temperature

                except (IndexError, ValueError) as e:
                    print(f"温度データパースエラー: {e} - 受信データ: {raw_data.hex()}")
                    print("ASCII文字が数値に変換できない、またはデータ長が不足している可能性があります。")
                    continue
            else:
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("温度データ取得スレッドを停止します。")
    finally:
        ser.close()
        print(f"シリアルポート {serial_port} を閉じました。")

# --- Matplotlib グラフ描画 ---

def animate_graph(i):
    global latest_yaw_angle, latest_temperature, data_lock

    with data_lock:
        current_yaw = latest_yaw_angle
        current_temp = latest_temperature

    # 有効な温度データが受信された場合のみプロット対象に追加
    if current_temp != -999.0: # 初期値でないことを確認
        # 最新のデータペアを追加
        # (X, Y) の順で、今回は (角度, 温度) にする
        if len(data_queue_plot_points) == data_queue_plot_points.maxlen:
            data_queue_plot_points.popleft() # キューが満杯なら一番古いデータを削除
        data_queue_plot_points.append((current_yaw, current_temp)) # ここで順番を入れ替える

    # グラフデータを更新
    # キューからX軸データとY軸データを分離
    # X軸は角度、Y軸は温度
    plot_yaws = [p[0] for p in data_queue_plot_points]
    plot_temps = [p[1] for p in data_queue_plot_points]

    line_plot.set_data(plot_yaws, plot_temps) # ここで順番を入れ替える

    # Y軸（温度）の範囲を固定
    ax.set_ylim(-90, -20) 

    # X軸（角度）の範囲を固定
    ax.set_xlim(0, 360) 

    return line_plot,

# --- メインプログラム実行 ---

if __name__ == "__main__":
    # --- MPU6050 の初期化とスレッド開始 ---
    try:
        mpu = MPU6050()
        print("MPU6050 の初期化に成功しました。")
    except Exception as e:
        print(f"MPU6050 の初期化に失敗しました: {e}")
        print("I2C が有効になっていること、および MPU6050 が正しく配線されていることを確認してください。")
        exit()
    mpu_thread = threading.Thread(target=read_mpu6050_data_thread, args=(mpu,), daemon=True)
    mpu_thread.start()

    # --- 温度センサーのシリアルポート設定とスレッド開始 ---
    # !!! ここをあなたの環境に合わせて変更してください !!!
    temperature_serial_port = '/dev/ttyUSB0' # <-- 例: /dev/ttyUSB0, /dev/ttyUSB1 など
    temperature_baud_rate = 9600 # <-- 温度センサー側のボーレートに合わせる

    temp_thread = threading.Thread(target=read_temperature_data_thread, args=(temperature_serial_port, temperature_baud_rate), daemon=True)
    temp_thread.start()

    # --- Matplotlib グラフ描画の初期化 ---
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    line_plot, = ax.plot([], [], 'o-') # プロットスタイルを点と線に (scatterでも可)

    ax.set_title('ヨー軸角度と温度の関係') # タイトルも変更
    ax.set_xlabel('ヨー軸角度 (度)') # X軸ラベルも変更
    ax.set_ylabel('温度 (度)') # Y軸ラベルも変更
    ax.grid(True)

    # アニメーションを開始 (グラフ更新間隔は200msで維持)
    ani = animation.FuncAnimation(fig, animate_graph, interval=200, blit=True)

    plt.tight_layout()
    plt.show()
