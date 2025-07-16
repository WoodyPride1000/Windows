import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import time
import queue # スレッド間の通信用

class ServoControllerGUI:
    # 初期化コマンドの定義
    INIT_CMND = 0x4E
    INIT_DATA = [0x30, 0x30, 0x30, 0x30, 0x30, 0x30]

    # チルト制御コマンドの定義
    TILT_CONTROL_CMND = 0x43
    TILT_STOP_DATA = [0x30, 0x30, 0x30, 0x30, 0x30, 0x30]
    TILT_UP_DATA = [0x31, 0x30, 0x30, 0x30, 0x30, 0x30]
    TILT_DOWN_DATA = [0x32, 0x30, 0x30, 0x30, 0x30, 0x30]

    # 角度指定チルト制御コマンドの定義
    TILT_ANGLE_CMND = 0x44
    TILT_ANGLE_SIGN_MINUS = 0x32 # '-' (ASCII '2')
    TILT_ANGLE_SIGN_NONE = 0x33 # 符号なし (正) (ASCII '3')
    TILT_ANGLE_SIGN_PLUS = 0x34 # '+' (ASCII '4')

    # レスポンスにおけるチルト状態 (CMND 43h のDATA 1バイト目)
    TILT_STATUS_STOP = 0x30
    TILT_STATUS_UP = 0x31
    TILT_STATUS_DOWN = 0x32
    TILT_STATUS_UPPER_LIMIT = 0x38 # 上限界
    TILT_STATUS_LOWER_LIMIT = 0x39 # 下限界

    def __init__(self, master):
        self.master = master
        master.title("サーボ制御ソフトウェア")

        self.serial_port = None
        self.serial_thread = None
        self.running = False
        self.response_queue = queue.Queue() # シリアルスレッドからのレスポンスを受け取るキュー

        # --- GUI要素の配置 ---
        # シリアルポート設定フレーム
        self.port_frame = tk.LabelFrame(master, text="シリアルポート設定", padx=10, pady=10)
        self.port_frame.pack(padx=10, pady=5, fill=tk.X)

        tk.Label(self.port_frame, text="ポート:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.port_var = tk.StringVar(master)
        self.port_options = self.get_available_ports()
        if self.port_options:
            self.port_var.set(self.port_options[0])
        else:
            self.port_var.set("ポートなし")
        self.port_menu = tk.OptionMenu(self.port_frame, self.port_var, *self.port_options if self.port_options else ["なし"])
        self.port_menu.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        tk.Label(self.port_frame, text="ボーレート:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.baudrate_var = tk.StringVar(master)
        self.baudrate_var.set("19200") # デフォルト値
        self.baudrate_entry = tk.Entry(self.port_frame, textvariable=self.baudrate_var, width=10)
        self.baudrate_entry.grid(row=1, column=1, padx=5, pady=2, sticky="ew")

        self.connect_button = tk.Button(self.port_frame, text="接続", command=self.connect_serial)
        self.connect_button.grid(row=0, column=2, padx=5, pady=2)
        self.disconnect_button = tk.Button(self.port_frame, text="切断", command=self.disconnect_serial, state=tk.DISABLED)
        self.disconnect_button.grid(row=1, column=2, padx=5, pady=2)

        # コマンド送信フレーム (汎用)
        self.command_frame = tk.LabelFrame(master, text="汎用コマンド送信", padx=10, pady=10)
        self.command_frame.pack(padx=10, pady=5, fill=tk.X)

        tk.Label(self.command_frame, text="CMND (HEX):").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.cmnd_entry = tk.Entry(self.command_frame, width=5)
        self.cmnd_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        self.cmnd_entry.insert(0, "41") # デフォルト値

        tk.Label(self.command_frame, text="DATA (HEX 例:3031):").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.data_entry = tk.Entry(self.command_frame, width=20)
        self.data_entry.grid(row=1, column=1, padx=5, pady=2, sticky="ew")
        self.data_entry.insert(0, "30") # デフォルト値

        self.send_button = tk.Button(self.command_frame, text="コマンド送信", command=self.send_command_from_gui, state=tk.DISABLED)
        self.send_button.grid(row=0, column=2, rowspan=2, padx=5, pady=2, sticky="ns")

        # 初期化ボタン
        self.init_button = tk.Button(self.command_frame, text="初期化", command=self.send_init_command, state=tk.DISABLED)
        self.init_button.grid(row=0, column=3, rowspan=2, padx=5, pady=2, sticky="ns")

        # --- チルト制御フレーム ---
        self.tilt_control_frame = tk.LabelFrame(master, text="チルト制御 (CMND 43h)", padx=10, pady=10)
        self.tilt_control_frame.pack(padx=10, pady=5, fill=tk.X)

        # チルト制御用ラジオボタン
        self.tilt_mode_var = tk.StringVar(master, value="stop") # 初期値は停止
        
        tk.Radiobutton(self.tilt_control_frame, text="停止", variable=self.tilt_mode_var, value="stop",
                       command=self.on_tilt_mode_change, state=tk.DISABLED).grid(row=0, column=0, padx=5, pady=2, sticky="w")
        tk.Radiobutton(self.tilt_control_frame, text="上", variable=self.tilt_mode_var, value="up",
                       command=self.on_tilt_mode_change, state=tk.DISABLED).grid(row=0, column=1, padx=5, pady=2, sticky="w")
        tk.Radiobutton(self.tilt_control_frame, text="下", variable=self.tilt_mode_var, value="down",
                       command=self.on_tilt_mode_change, state=tk.DISABLED).grid(row=0, column=2, padx=5, pady=2, sticky="w")
        
        self.send_tilt_button = tk.Button(self.tilt_control_frame, text="チルトコマンド送信", command=self.send_tilt_control_command, state=tk.DISABLED)
        self.send_tilt_button.grid(row=0, column=3, padx=5, pady=2)


        # --- 角度指定チルト制御フレーム ---
        self.tilt_angle_frame = tk.LabelFrame(master, text="角度指定チルト制御 (CMND 44h)", padx=10, pady=10)
        self.tilt_angle_frame.pack(padx=10, pady=5, fill=tk.X)

        tk.Label(self.tilt_angle_frame, text="符号:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.angle_sign_var = tk.StringVar(master, value="none") # 初期値は符号なし
        tk.Radiobutton(self.tilt_angle_frame, text="-", variable=self.angle_sign_var, value="minus", state=tk.DISABLED).grid(row=0, column=1, padx=5, pady=2, sticky="w")
        tk.Radiobutton(self.tilt_angle_frame, text="符号なし", variable=self.angle_sign_var, value="none", state=tk.DISABLED).grid(row=0, column=2, padx=5, pady=2, sticky="w")
        tk.Radiobutton(self.tilt_angle_frame, text="+", variable=self.angle_sign_var, value="plus", state=tk.DISABLED).grid(row=0, column=3, padx=5, pady=2, sticky="w")

        tk.Label(self.tilt_angle_frame, text="角度 (0.00～15.0):").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        # 角度入力のエントリにバリデーションを追加
        vcmd = (master.register(self.validate_tilt_angle_input), '%P')
        self.angle_entry = tk.Entry(self.tilt_angle_frame, width=10, validate="key", validatecommand=vcmd, state=tk.DISABLED)
        self.angle_entry.grid(row=1, column=1, columnspan=3, padx=5, pady=2, sticky="ew")
        self.angle_entry.insert(0, "0.00") # デフォルト値

        self.send_angle_tilt_button = tk.Button(self.tilt_angle_frame, text="角度指定チルト送信", command=self.send_angle_tilt_command, state=tk.DISABLED)
        self.send_angle_tilt_button.grid(row=1, column=4, padx=5, pady=2)

        # --- レスポンス表示エリア ---
        self.response_frame = tk.LabelFrame(master, text="通信ログとレスポンス", padx=10, pady=10)
        self.response_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        self.response_text = scrolledtext.ScrolledText(self.response_frame, width=70, height=15, state=tk.DISABLED, wrap=tk.WORD)
        self.response_text.pack(expand=True, fill=tk.BOTH)

        # ログファイル保存ボタン
        self.save_log_button = tk.Button(self.response_frame, text="ログを保存", command=self.save_log)
        self.save_log_button.pack(pady=5)
        
        # ウィンドウを閉じるときの処理
        master.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 定期的にキューをチェックしてGUIを更新
        self.master.after(100, self.process_queue)

        # 初期状態でチルト関連ボタンの状態を設定
        self._update_tilt_button_states() 

    def get_available_ports(self):
        """利用可能なシリアルポートをリストアップして返す."""
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def _update_tilt_button_states(self):
        """チルト関連ボタンの有効/無効状態を更新するヘルパー関数."""
        state = tk.NORMAL if self.serial_port and self.serial_port.is_open else tk.DISABLED
        
        # チルト制御フレームのラジオボタンと送信ボタン
        for radio in self.tilt_control_frame.winfo_children():
            if isinstance(radio, tk.Radiobutton):
                radio.config(state=state)
        self.send_tilt_button.config(state=state)

        # 角度指定チルト制御フレームのラジオボタン、入力、送信ボタン
        for radio in self.tilt_angle_frame.winfo_children():
            if isinstance(radio, tk.Radiobutton):
                radio.config(state=state)
        self.angle_entry.config(state=state)
        self.send_angle_tilt_button.config(state=state)


    def connect_serial(self):
        """シリアルポートに接続する."""
        port = self.port_var.get()
        try:
            baudrate = int(self.baudrate_var.get())
        except ValueError:
            messagebox.showerror("エラー", "ボーレートは数値で入力してください。")
            return

        if not port or port == "ポートなし":
            messagebox.showerror("エラー", "接続するポートを選択してください。")
            return

        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5 # 受信タイムアウト
            )
            self.log_message(f"{port} に接続しました。\n")
            self.running = True
            self.serial_thread = threading.Thread(target=self._serial_reader_thread, daemon=True)
            self.serial_thread.start()

            # ボタンの状態を更新
            self.connect_button.config(state=tk.DISABLED)
            self.disconnect_button.config(state=tk.NORMAL)
            self.send_button.config(state=tk.NORMAL)
            self.init_button.config(state=tk.NORMAL)
            self._update_tilt_button_states() # チルト関連ボタンの状態も更新
            self.port_menu.config(state=tk.DISABLED)
            self.baudrate_entry.config(state=tk.DISABLED)

        except serial.SerialException as e:
            messagebox.showerror("エラー", f"シリアルポートのオープンに失敗しました: {e}")
            self.log_message(f"エラー: シリアルポートのオープンに失敗しました: {e}\n")

    def disconnect_serial(self):
        """シリアルポートを切断する."""
        if self.serial_port and self.serial_port.is_open:
            self.running = False
            if self.serial_thread and self.serial_thread.is_alive():
                # スレッドが安全に終了するのを待つ (最大1秒)
                self.serial_thread.join(timeout=1)
            self.serial_port.close()
            self.log_message(f"シリアルポートを切断しました。\n")
            
            # ボタンの状態を更新
            self.connect_button.config(state=tk.NORMAL)
            self.disconnect_button.config(state=tk.DISABLED)
            self.send_button.config(state=tk.DISABLED)
            self.init_button.config(state=tk.DISABLED)
            self._update_tilt_button_states() # チルト関連ボタンの状態も更新
            self.port_menu.config(state=tk.NORMAL)
            self.baudrate_entry.config(state=tk.NORMAL)

    def calculate_bcc(self, data_bytes):
        """BCC (Block Check Character) を計算する (XOR方式)."""
        # BCCの計算方法がXORでない場合は修正が必要です
        bcc = 0
        for b in data_bytes:
            bcc ^= b
        return bcc

    def send_command_internal(self, cmnd_byte, data_bytes_list):
        """シリアルポートへコマンドを送信する内部関数."""
        if not self.serial_port or not self.serial_port.is_open:
            self.response_queue.put("エラー: シリアルポートが接続されていません。\n")
            return False

        # コマンドフレームの構築
        stx = 0x02
        ext = 0x03
        data_part = bytes(data_bytes_list) # DATAはバイト列として扱う

        # BCC計算用のバイト列（STXからEXTまで）
        bcc_calc_data = bytes([stx, cmnd_byte]) + data_part + bytes([ext])
        bcc = self.calculate_bcc(bcc_calc_data)

        # 送信する最終的なバイト列
        command_frame = bytes([stx, cmnd_byte]) + data_part + bytes([ext, bcc])

        self.response_queue.put(f"送信データ (HEX): {' '.join(f'{b:02X}' for b in command_frame)}\n")

        try:
            self.serial_port.write(command_frame)
            return True
        except serial.SerialException as e:
            self.response_queue.put(f"エラー: コマンド送信失敗: {e}\n")
            return False

    def receive_response_internal(self):
        """シリアルポートからのレスポンスを受信する内部関数."""
        start_time = time.time()
        response_data = b''
        # 100ms以内、またはスレッドが停止するまで受信を試みる
        while self.running and (time.time() - start_time) * 1000 < 100: 
            if self.serial_port.in_waiting > 0:
                response_data += self.serial_port.read(self.serial_port.in_waiting)
            time.sleep(0.001) # 短いポーリング間隔

        if response_data:
            self.response_queue.put(f"受信データ (HEX): {' '.join(f'{b:02X}' for b in response_data)}\n")
            
            # 受信データの解析とBCCチェック
            # レスポンスフォーマットが STX, CMND/STATUS, DATA..., EXT, BCC と仮定
            if len(response_data) >= 4: # 最低限の長さ (STX, CMND, EXT, BCC)
                received_bcc = response_data[-1]
                # レスポンスのBCC計算範囲を調整してください (STXからEXTまで)
                calculated_bcc_resp = self.calculate_bcc(response_data[:-1]) 
                
                if received_bcc == calculated_bcc_resp:
                    self.response_queue.put("BCCチェック: OK\n")
                    return response_data
                else:
                    self.response_queue.put(f"BCCチェック: エラー (受信: {received_bcc:02X}, 計算: {calculated_bcc_resp:02X})\n")
                    return None
            else:
                self.response_queue.put("レスポンスデータが短すぎます。\n")
                return None
        else:
            self.response_queue.put("レスポンスがありませんでした。\n")
            return None

    def _serial_reader_thread(self):
        """バックグラウンドでシリアルポートからの予期せぬ受信を監視するスレッド."""
        while self.running:
            if self.serial_port and self.serial_port.is_open and self.serial_port.in_waiting > 0:
                unexpected_data = self.serial_port.read(self.serial_port.in_waiting)
                self.response_queue.put(f"警告: 予期せぬデータを受信しました: {' '.join(f'{b:02X}' for b in unexpected_data)}\n")
            time.sleep(0.05) # 短い間隔でポーリング

    def _command_sender_with_retry(self, cmnd_byte, data_bytes_list, callback_on_success=None):
        """コマンド送信とリトライ処理を行うスレッド関数."""
        max_retries = 3
        command_successful = False
        for attempt in range(max_retries):
            self.response_queue.put(f"コマンド送信試行: {attempt + 1}/{max_retries}\n")
            
            if self.send_command_internal(cmnd_byte, data_bytes_list):
                response = self.receive_response_internal()
                if response:
                    # BCCチェックOKの場合、ここで追加のレスポンスチェックを行う
                    if callback_on_success:
                        if callback_on_success(response):
                            command_successful = True
                            # callback_on_success内で詳細メッセージがすでにキューに投入されていると想定
                            break # 成功したらリトライを終了
                        else:
                            self.response_queue.put("レスポンス内容が期待値と異なります。リトライします。\n")
                    else:
                        # カスタムチェックがない場合のデフォルト成功メッセージ
                        command_successful = True
                        self.response_queue.put(f"コマンド成功！ レスポンス: {response.hex()}\n\n")
                        break
                else:
                    self.response_queue.put("レスポンス受信失敗、またはBCCエラー。リトライします。\n")
            else:
                self.response_queue.put("コマンド送信失敗。リトライします。\n")
            
            if attempt < max_retries - 1: # 最終試行の場合は待機しない
                time.sleep(0.2) # 次のリトライまでの待機

        if not command_successful:
            self.response_queue.put("コマンド送信に失敗しました (リトライ回数超過)。\n\n")

    def send_command_from_gui(self):
        """GUIからの通常コマンド送信をトリガーする."""
        cmnd_hex_str = self.cmnd_entry.get().strip()
        data_hex_str = self.data_entry.get().strip()

        try:
            cmnd_byte = int(cmnd_hex_str, 16)
            if not (0x41 <= cmnd_byte <= 0x5A):
                raise ValueError("CMNDは41hから5Ahの範囲で入力してください。")
        except ValueError as e:
            messagebox.showerror("入力エラー", f"CMNDは16進数(例:41)で入力してください。: {e}")
            return

        data_bytes_list = []
        try:
            if data_hex_str:
                # 2文字ずつ区切って16進数に変換
                for i in range(0, len(data_hex_str), 2):
                    data_bytes_list.append(int(data_hex_str[i:i+2], 16))
        except ValueError:
            messagebox.showerror("入力エラー", "DATAは16進数(例:3031)で入力してください。")
            return

        # コマンド送信とリトライ処理を別スレッドで実行
        command_sender_thread = threading.Thread(
            target=self._command_sender_with_retry,
            args=(cmnd_byte, data_bytes_list, None) # 通常コマンドはカスタムチェックなし
        )
        command_sender_thread.daemon = True # メインスレッド終了時に一緒に終了
        command_sender_thread.start()

    def send_init_command(self):
        """初期化コマンドを送信する."""
        self.log_message("初期化コマンドを送信します...\n")
        # _command_sender_with_retry スレッドを起動
        command_sender_thread = threading.Thread(
            target=self._command_sender_with_retry,
            args=(self.INIT_CMND, self.INIT_DATA, self.check_init_response) # 初期化レスポンスチェック関数を渡す
        )
        command_sender_thread.daemon = True
        command_sender_thread.start()

    def check_init_response(self, response_bytes):
        """初期化コマンドに対するレスポンスをチェックする."""
        if response_bytes is None:
            self.response_queue.put("初期化コマンド レスポンス: 不明 (BCCエラーまたはタイムアウト)\n")
            return False

        # レスポンスフォーマット: STX, CMND/STATUS, DATA(6), EXT, BCC (計10バイト)
        expected_full_length = 10 
        if len(response_bytes) != expected_full_length:
            self.response_queue.put(f"初期化コマンド レスポンス: フォーマットが期待値と異なります。期待 {expected_full_length}バイト, 実際 {len(response_bytes)}バイト\n")
            return False

        response_cmnd = response_bytes[1] # STXの次がCMND/STATUS
        response_data = list(response_bytes[2:-2]) # CMNDの次からEXTの手前までがDATA

        expected_cmnd = self.INIT_CMND
        expected_data = self.INIT_DATA

        is_cmnd_match = (response_cmnd == expected_cmnd)
        is_data_match = (response_data == expected_data)

        if is_cmnd_match and is_data_match:
            self.response_queue.put("初期化コマンド レスポンス: OK (期待値と一致)\n")
            return True
        else:
            self.response_queue.put(f"初期化コマンド レスポンス: 不一致！\n")
            self.response_queue.put(f"  期待CMND: {expected_cmnd:02X}, 実際CMND: {response_cmnd:02X}\n")
            self.response_queue.put(f"  期待DATA: {' '.join(f'{b:02X}' for b in expected_data)}, 実際DATA: {' '.join(f'{b:02X}' for b in response_data)}\n")
            return False

    def on_tilt_mode_change(self):
        """チルト制御ラジオボタンが変更されたときにログを更新する (デバッグ用)."""
        self.log_message(f"チルトモード選択: {self.tilt_mode_var.get()}\n")

    def send_tilt_control_command(self):
        """チルト制御コマンド (CMND 43h) を送信する."""
        mode = self.tilt_mode_var.get()
        cmnd_byte = self.TILT_CONTROL_CMND
        data_bytes = []

        if mode == "stop":
            data_bytes = self.TILT_STOP_DATA
            self.log_message("チルト停止コマンドを送信します...\n")
        elif mode == "up":
            data_bytes = self.TILT_UP_DATA
            self.log_message("チルト上コマンドを送信します...\n")
        elif mode == "down":
            data_bytes = self.TILT_DOWN_DATA
            self.log_message("チルト下コマンドを送信します...\n")
        else:
            messagebox.showerror("エラー", "不正なチルトモードが選択されました。")
            return

        command_sender_thread = threading.Thread(
            target=self._command_sender_with_retry,
            args=(cmnd_byte, data_bytes, self.check_tilt_control_response)
        )
        command_sender_thread.daemon = True
        command_sender_thread.start()

    def check_tilt_control_response(self, response_bytes):
        """チルト制御コマンド (CMND 43h) のレスポンスをチェックする."""
        if response_bytes is None:
            self.response_queue.put("チルト制御 レスポンス: 不明 (BCCエラーまたはタイムアウト)\n")
            return False

        # レスポンスフォーマット: STX(1), CMND(1), DATA(6), EXT(1), BCC(1) = 10バイト
        expected_full_length = 10
        if len(response_bytes) != expected_full_length:
            self.response_queue.put(f"チルト制御 レスポンス: フォーマットが期待値と異なります。期待 {expected_full_length}バイト, 実際 {len(response_bytes)}バイト\n")
            return False

        response_cmnd = response_bytes[1]
        response_status_byte = response_bytes[2] # DATA 1バイト目

        if response_cmnd != self.TILT_CONTROL_CMND:
            self.response_queue.put(f"チルト制御 レスポンス: CMNDが不一致！ 期待 {self.TILT_CONTROL_CMND:02X}, 実際 {response_cmnd:02X}\n")
            return False

        status_map = {
            self.TILT_STATUS_STOP: "停止",
            self.TILT_STATUS_UP: "上",
            self.TILT_STATUS_DOWN: "下",
            self.TILT_STATUS_UPPER_LIMIT: "上限界",
            self.TILT_STATUS_LOWER_LIMIT: "下限界"
        }
        status_text = status_map.get(response_status_byte, f"不明な状態 ({response_status_byte:02X})")
        
        self.response_queue.put(f"チルト制御 レスポンス: OK. 状態: {status_text}\n")
        return True


    def validate_tilt_angle_input(self, P):
        """角度入力フィールドのバリデーション (0.00～15.0の数値のみ許可)."""
        # P は、変更が許可された場合にエントリに表示されるテキスト
        if P == "":
            return True # 空入力は許可 (削除時など)
        
        # 小数点を含む数値であるか、および0-9の文字、または小数点であるかチェック
        # 正規表現を使うとより堅牢だが、ここではシンプルに
        if not all(c.isdigit() or c == '.' for c in P):
            return False
            
        try:
            value = float(P)
            # 0.00 から 15.0 までの範囲をチェック
            # ただし、入力中は中間状態がありえるので、最終的なフォーマットチェックは送信時に行うのが良い
            if 0.00 <= value <= 15.0:
                # 厳密な小数点以下2桁のチェックは送信時に行う
                return True
            else:
                # 範囲外の場合は許可しない
                return False
        except ValueError:
            # floatに変換できない場合は許可しない
            return False

    def send_angle_tilt_command(self):
        """角度指定チルト制御コマンド (CMND 44h) を送信する."""
        angle_str = self.angle_entry.get().strip()
        sign_mode = self.angle_sign_var.get()

        try:
            angle_float = float(angle_str)
            if not (0.00 <= angle_float <= 15.0):
                messagebox.showerror("入力エラー", "角度は0.00から15.0の範囲で入力してください。")
                return
        except ValueError:
            messagebox.showerror("入力エラー", "角度は数値で入力してください。")
            return

        cmnd_byte = self.TILT_ANGLE_CMND
        data_bytes = []

        # 1バイト目: 符号
        if sign_mode == "minus":
            data_bytes.append(self.TILT_ANGLE_SIGN_MINUS)
            self.log_message(f"角度指定チルトコマンド（- {angle_float:.2f}）を送信します...\n")
        elif sign_mode == "none":
            data_bytes.append(self.TILT_ANGLE_SIGN_NONE)
            self.log_message(f"角度指定チルトコマンド（符号なし {angle_float:.2f}）を送信します...\n")
        elif sign_mode == "plus":
            data_bytes.append(self.TILT_ANGLE_SIGN_PLUS)
            self.log_message(f"角度指定チルトコマンド（+ {angle_float:.2f}）を送信します...\n")
        else:
            messagebox.showerror("エラー", "不正な符号が選択されました。")
            return

        # 2-4バイト目: 角度3桁 (30h, 30h, 30h 〜 31h, 35h, 30h)
        # floatを100倍して整数にし、3桁になるようにゼロ埋めしたASCII文字に変換
        angle_int_times_100 = int(round(angle_float * 100)) # 例: 12.34 -> 1234
        
        # 15.0 (1500) が最大なので、常に4桁になる可能性を考慮し、
        # 3桁のデータにするために `15.0` の場合を `150` と解釈するか、仕様を再確認してください。
        # 現在の仕様「0.00〜15.0」で「角度３桁」は、15.00 -> "150" と解釈し、小数点以下2桁目を無視するのか、
        # あるいは「15.0」が150で、その下位2桁が小数点以下であるかを別途伝えるのか、確認が必要です。
        # ここでは「15.0」を「150」と捉えて3桁のASCIIとするようにします。
        # 例: 1.23 -> "123", 12.3 -> "123", 0.05 -> "005"
        # 15.00は1500ですが、3桁にするため、`150`として処理します。
        
        # 0.00〜15.0 を 0〜150 の整数値として扱う
        # 仕様「角度3桁」と「0.00〜15.0」の組み合わせから、
        # 15.0 -> 150 (3桁)
        # 1.23 -> 123 (3桁)
        # 0.05 -> 005 (3桁)
        # のように変換すると想定。
        
        # 15.00 を 150 とするには 10 を掛ける。
        # 小数点以下2桁がコマンドで表現できない場合があるため、サーボの仕様を確認してください。
        # ここでは「0.00〜15.0」は「0〜150」の整数として扱われるものと仮定し、
        # 入力値を10倍して文字列化するようにします。
        angle_for_command = int(round(angle_float * 10)) # 例: 1.23 -> 12.3 -> 12, 15.0 -> 150
        
        # 最大15.0なので150まで。これを3桁にゼロ埋め
        angle_str_padded = f"{angle_for_command:03d}" 
        
        if len(angle_str_padded) > 3:
             messagebox.showerror("内部エラー", "計算された角度値が3桁を超えました。入力値と変換ロジックを確認してください。")
             return

        for char_digit in angle_str_padded:
            data_bytes.append(ord(char_digit)) # ASCII '0' -> 0x30

        # 5-6バイト目: 予備 (30h, 30h)
        data_bytes.extend([0x30, 0x30])

        # データバイトが6バイトになることを確認
        if len(data_bytes) != 6:
            messagebox.showerror("内部エラー", f"角度指定チルトのデータバイト数が不正です: {len(data_bytes)} (期待値: 6)")
            return

        command_sender_thread = threading.Thread(
            target=self._command_sender_with_retry,
            args=(cmnd_byte, data_bytes, self.check_tilt_angle_response)
        )
        command_sender_thread.daemon = True
        command_sender_thread.start()

    def check_tilt_angle_response(self, response_bytes):
        """角度指定チルト制御コマンド (CMND 44h) のレスポンスをチェックする."""
        # 仕様によると、角度指定チルト制御のレスポンスはCMND 43hと同じ
        # そのため、check_tilt_control_response を再利用します。
        self.response_queue.put("角度指定チルト レスポンスを確認中...\n")
        # ただし、返ってくるCMNDは43hですが、これは送信したCMND 44hとは異なります。
        # サーボの仕様として、角度指定コマンドのレスポンスがチルト制御と同じ「状態」を返す
        # ということなので、ここでは `TILT_CONTROL_CMND` (0x43) を期待します。
        # `check_tilt_control_response` は `TILT_CONTROL_CMND` をチェックするので問題ありません。
        return self.check_tilt_control_response(response_bytes)

    def log_message(self, message):
        """GUIのテキストエリアにメッセージを追加する."""
        self.response_text.config(state=tk.NORMAL)
        self.response_text.insert(tk.END, message)
        self.response_text.see(tk.END) # 最新のメッセージまでスクロール
        self.response_text.config(state=tk.DISABLED)

    def process_queue(self):
        """キューにデータがあれば取り出してGUIに表示する (メインスレッドで実行)."""
        try:
            while True:
                message = self.response_queue.get_nowait()
                self.log_message(message)
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.process_queue) # 100msごとにキューをチェック

    def save_log(self):
        """表示されているログをファイルに保存する."""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="ログファイルを保存"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.response_text.get("1.0", tk.END))
                messagebox.showinfo("保存完了", f"ログを {file_path} に保存しました。")
            except Exception as e:
                messagebox.showerror("保存エラー", f"ログの保存に失敗しました: {e}")

    def on_closing(self):
        """ウィンドウを閉じる際の処理."""
        self.disconnect_serial() # アプリケーション終了時にシリアルポートを閉じる
        self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ServoControllerGUI(root)
    root.mainloop()
