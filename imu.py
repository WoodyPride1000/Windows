# ... (前略) ...

def read_from_serial(ser_port, baud_rate):
    try:
        ser = serial.Serial(ser_port, baud_rate, timeout=0.1)
        print(f"シリアルポート {ser_port} を開きました。")
    except serial.SerialException as e:
        print(f"シリアルポートを開けませんでした: {e}")
        return

    try:
        while True:
            # 改行コード '\n' まで読み込む（一般的なシリアル通信の形式）
            # または、固定長のデータが送られてくる場合は ser.read(固定長)
            if ser.in_waiting > 0:
                line = ser.readline().decode('ascii').strip() # 例: "123.45\n" を "123.45" に変換

                if line: # 空行でなければ処理
                    try:
                        # 受信した文字列を浮動小数点数に変換
                        yaw_angle = float(line)

                        # 必要であれば、角度の範囲を調整（例: -180～180度にするなど）
                        # if yaw_angle > 180:
                        #     yaw_angle -= 360

                    except ValueError:
                        print(f"データパースエラー: 数値に変換できません。受信データ: '{line}'")
                        continue # 不完全なデータはスキップ

                    data_queue_combined_value.append(yaw_angle)
                    # print(f"受信: ヨー軸角度={yaw_angle}") # デバッグ用

            else:
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("シリアル読み込みスレッドを停止します。")
    finally:
        ser.close()
        print("シリアルポートを閉じました。")

# ... (後略 - animate_with_queue関数やmain関数はほぼ同じでOK) ...

if __name__ == "__main__":
    # ... (中略) ...
    ax.set_title('MPU6050 ヨー軸角度') # タイトルを変更
    ax.set_ylabel('角度 (度)')
    # ... (後略) ...
