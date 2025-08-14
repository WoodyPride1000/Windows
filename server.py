import eventlet
eventlet.monkey_patch() # この行がファイルの先頭にあることを確認

from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO
import serial
import threading
import time
from datetime import datetime, timedelta
import re
import collections

app = Flask(__name__, static_url_path='', static_folder='.')

socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')

GNSS_PORT = '/dev/ttyUSB0' # 例: '/dev/ttyUSB0' (Linux) or 'COM3' (Windows)
BAUD_RATE = 115200

gnss_data = {
    'lat': 35.681236,
    'lng': 139.767125,
    'alt': 0.0,
    'heading': 90.0, # 初期値は90.0にしておきます
    'speed': 0.0,
    'fix': '0',      # GGA, GSAの測位品質/モード
    'hdop': 99.9,    # 水平精度低下率 (GGA/GSA)
    'pdop': 99.9,    # 位置精度低下率 (GSA)
    'vdop': 99.9,    # 垂直精度低下率 (GSA)
    'num_satellites': 0, # GGAのみ
    'satellites_in_use': [], # GSAで測位に使用中の衛星PRN IDリスト
    'mode_ma': '',   # GSAの測位モード (M=手動, A=自動)
    'mode_fix_type': '1', # GSAの測位タイプ (1=Fixなし, 2=2D, 3=3D)
    'rms': 0.0,      # GST: Standard deviation of pseudoranges
    'smjr_std': 0.0, # GST: Standard deviation of semi-major axis of error elli>
    'smnr_std': 0.0, # GST: Standard deviation of semi-minor axis of error elli>
    'orient': 0.0,   # GST: Orientation of semi-major axis of error ellipse
    'lat_std': 0.0,  # GST: Standard deviation of latitude error
    'lon_std': 0.0,  # GST: Standard deviation of longitude error
    'alt_std': 0.0,  # GST: Standard deviation of altitude error
    'vtg_course_true': 0.0, # VTG: Course over ground, degrees True
    'vtg_course_mag': 0.0,  # VTG: Course over ground, degrees Magnetic
    'vtg_speed_knots': 0.0, # VTG: Speed over ground, knots
    'vtg_speed_kmh': 0.0,   # VTG: Speed over ground, km/h
    'vtg_mode_ind': '',     # VTG: Mode indicator (A, D, E, M, N, P, S)
    'timestamp_utc': '',
    'date_utc': '',
    'datetime_iso': ''
}

MAX_HISTORY_SIZE = 50 
gnss_data_history = collections.deque(maxlen=MAX_HISTORY_SIZE)

# NMEA → Decimal 度変換 (より堅牢に数値部分を抽出)
def convert_to_decimal(value, direction):
    if not value:
        return 0.0
    
    try:
        # 数値部分のみを正規表現で抽出

        match = re.match(r'^\d+(\.\d+)?', value)
        if not match:
            return 0.0
        
        float_value_str = match.group(0) # 抽出された数値文字列
        
        if '.' not in float_value_str:
            return 0.0 # 小数点がない場合も不正とみなす (NMEAの緯度経度では必須)
        
        parts = float_value_str.split('.')
        degrees_str = parts[0]
        minutes_str = parts[1]
        
        degrees = 0.0
        minutes = 0.0

        if len(degrees_str) >= 4: # 緯度または経度 (DDMM.MMMM or DDDMM.MMMM)
            # 緯度/経度に応じた度の部分を抽出
            if len(degrees_str) == 4: # 緯度 DDMM
                degrees = float(degrees_str[0:2])
                minutes = float(degrees_str[2:] + '.' + minutes_str)
            elif len(degrees_str) >= 5: # 経度 DDDMM (少なくとも5桁あれば経度と>
                degrees = float(degrees_str[0:3])
                minutes = float(degrees_str[3:] + '.' + minutes_str)
            else:
                return 0.0 # 不明なフォーマット

            decimal_degrees = degrees + (minutes / 60.0)
            
            if direction in ['S', 'W']:
                decimal_degrees *= -1
                
            return decimal_degrees
    except (ValueError, IndexError):
        return 0.0
    return 0.0

def nmea_time_to_iso(time_str, date_str=''):
    try:
        if '.' in time_str:
            # 小数点以下の秒数を取得し、時刻文字列から削除
            seconds_parts = time_str.split('.')
            time_only_str = seconds_parts[0]
            milliseconds = int(float('0.' + seconds_parts[1]) * 1000)
        else:
            time_only_str = time_str
            milliseconds = 0

        if date_str:
            dt_obj = datetime.strptime(f"{date_str}{time_only_str}", "%d%m%y%H%>
        else:
            # 日付がない場合、システムの日付を使用 (タイムゾーン情報なし)
            today = datetime.utcnow().strftime("%d%m%y")
            dt_obj = datetime.strptime(f"{today}{time_only_str}", "%d%m%y%H%M%S>
        
        dt_obj = dt_obj + timedelta(milliseconds=milliseconds)
            
        return dt_obj.isoformat(timespec='milliseconds') + 'Z' # UTCであること[>
    except (ValueError, IndexError):
        return ''

# ヘルパー関数: 安全なfloat変換
def safe_float_convert(value, default=0.0):
    try:
        return float(value)
    except (ValueError, IndexError):
        return default

# ヘルパー関数: 安全なint変換
def safe_int_convert(value, default=0):
    try:
        return int(float(value)) # intに変換する前にfloatを経由して小数も扱える>
    except (ValueError, IndexError):
        return default

# GNSS受信スレッド
def read_gnss():
    global gnss_data
    # NMEAメッセージの厳格な正規表現パターン（行全体が開始から終了まで一致）
    # ser.read(in_waiting)と組み合わせるため、\r?\n?$は含めない
    nmea_sentence_pattern = re.compile(r'^\$[A-Z]{2}[A-Z]{3},.*?\*[0-9A-F]{2}$')
    
    try:
        # シリアルポートのタイムアウトは短めに設定
        with serial.Serial(GNSS_PORT, BAUD_RATE, timeout=0.1) as ser: 
            print(f"Serial port {GNSS_PORT} opened at {BAUD_RATE} baud.")
            buffer = "" # 受信バッファ
            
            while True:
                # 利用可能な全てのバイトを読み込む
                bytes_to_read = ser.in_waiting 
                if bytes_to_read > 0:
                    char_data = ser.read(bytes_to_read).decode('ascii', errors=>
                    buffer += char_data
                else:
                    # データがない場合は、CPUを占有しないように少し長めにスリー>
                    eventlet.sleep(0.01) # 10ミリ秒スリープ
                    continue # 次のループへ

                # バッファから完全なNMEAメッセージを抽出
                # "$"から次の改行までを1つの候補とし、その後に厳格な正規表現で[>
                while '\n' in buffer:
                    line_end_idx = buffer.find('\n')
                    potential_line = buffer[:line_end_idx].strip() # 改行までを>
                    buffer = buffer[line_end_idx + 1:] # 処理した部分をバッファ>

                    if not potential_line: # 空行はスキップ
                        continue

                    # 正規表現でNMEAメッセージの形式を厳密にチェック
                    if not nmea_sentence_pattern.match(potential_line):
                        print(f"Warning: Skipping non-NMEA formatted line: {pot>
                        eventlet.sleep(0.001) # 不正な行処理後にごく短いスリープ
                        continue

                    # 有効なNMEAメッセージであれば解析
                    print(f"Received NMEA (parsed): {potential_line}")

                    parts = potential_line.split(',')
                    if len(parts) < 2:
                        continue

                    # トークIDとメッセージタイプを抽出
                    sentence_type_raw = parts[0][1:]
                    sentence_type = sentence_type_raw[2:]

                    # HDTの処理 (startswithチェックは維持)
                    if potential_line.startswith('$GNHDT') or potential_line.st>
                        print(f"DEBUG: HDT block entered (startswith check) for>
                        print(f"DEBUG: HDT parts: {parts!r}")

                        if len(parts) > 1:
                            gnss_data['heading'] = safe_float_convert(parts[1])
                            print(f"DEBUG: HDT Heading updated to: {gnss_data['>
                        else:
                            print(f"WARNING: HDT line has insufficient parts: {>

                    elif sentence_type == 'GGA':
                        if len(parts) >= 10:
                            gnss_data['timestamp_utc'] = parts[1]
                            gnss_data['lat'] = convert_to_decimal(parts[2], par>
                            gnss_data['lng'] = convert_to_decimal(parts[4], par>
                            gnss_data['fix'] = parts[6] if len(parts[6]) == 1 a>
                            gnss_data['num_satellites'] = safe_int_convert(part>
                            gnss_data['hdop'] = safe_float_convert(parts[8])
                            gnss_data['alt'] = safe_float_convert(parts[9])

                            if gnss_data['date_utc']:
                                gnss_data['datetime_iso'] = nmea_time_to_iso(gn>
                            else:
                                gnss_data['datetime_iso'] = nmea_time_to_iso(gn>

                    elif sentence_type == 'RMC':
                        if len(parts) >= 10:
                            gnss_data['timestamp_utc'] = parts[1] if len(parts)>
                            gnss_data['lat'] = convert_to_decimal(parts[3], par>
                            gnss_data['lng'] = convert_to_decimal(parts[5], par>
                            gnss_data['speed'] = safe_float_convert(parts[7])
                            gnss_data['date_utc'] = parts[9] if len(parts) > 9 >
                            gnss_data['datetime_iso'] = nmea_time_to_iso(gnss_d>

                    elif sentence_type == 'ZDA':
                        if len(parts) > 4:
                            gnss_data['timestamp_utc'] = parts[1]
                            gnss_data['date_utc'] = f"{parts[2].zfill(2)}{parts>
                            gnss_data['datetime_iso'] = nmea_time_to_iso(gnss_d>

                    # GSAメッセージの解析
                    elif sentence_type == 'GSA':
                        if len(parts) >= 18:
                            gnss_data['mode_ma'] = parts[1] if len(parts) > 1 e>
                            gnss_data['mode_fix_type'] = parts[2] if len(parts)>

                            if gnss_data['mode_fix_type'] == '1': gnss_data['fi>
                            elif gnss_data['mode_fix_type'] == '2': gnss_data['>
                            elif gnss_data['mode_fix_type'] == '3': gnss_data['>

                            sat_ids_in_solution = []
                            for i in range(3, 15): 
                                if len(parts) > i and parts[i]:
                                    sat_ids_in_solution.append(safe_int_convert>
                            gnss_data['satellites_in_use'] = sat_ids_in_solution

                            gnss_data['pdop'] = safe_float_convert(parts[15])
                            gnss_data['hdop'] = safe_float_convert(parts[16])
                            gnss_data['vdop'] = safe_float_convert(parts[17])
                    
                    # GPGSTメッセージの解析
                    elif sentence_type == 'GST':
                        if len(parts) >= 9:
                            gnss_data['rms'] = safe_float_convert(parts[2])
                            gnss_data['smjr_std'] = safe_float_convert(parts[3])
                            gnss_data['smnr_std'] = safe_float_convert(parts[4])
                            gnss_data['orient'] = safe_float_convert(parts[5])
                            gnss_data['lat_std'] = safe_float_convert(parts[6])
                            gnss_data['lon_std'] = safe_float_convert(parts[7])
                            gnss_data['alt_std'] = safe_float_convert(parts[8])
                    
                    # GPVTGメッセージの解析を追加
                    elif sentence_type == 'VTG':
                        # $--VTG,course_true,T,course_mag,M,speed_knots,N,speed>
                        # parts:    0       1          2 3         4 5         >
                        if len(parts) >= 10: # Mode indicator (Field 10) まで存>
                            gnss_data['vtg_course_true'] = safe_float_convert(p>
                            gnss_data['vtg_course_mag'] = safe_float_convert(pa>
                            gnss_data['vtg_speed_knots'] = safe_float_convert(p>
                            gnss_data['vtg_speed_kmh'] = safe_float_convert(par>
                            gnss_data['vtg_mode_ind'] = parts[9] if len(parts) >
                            print(f"DEBUG: VTG data updated: True Course={gnss_>
                    
                    # NMEAパースが成功し、かつ緯度経度が更新されていれば履歴に[>
                    if (gnss_data['lat'] != 0.0 or gnss_data['lng'] != 0.0) and>
                        gnss_data_history.append(gnss_data.copy())
                
                # バッファが過度に大きくなった場合の切り詰め
                if len(buffer) > 1000: # 例: 1000文字を超えたら古い部分を破棄
                    next_dollar = buffer.find('$')
                    if next_dollar != -1:
                        buffer = buffer[next_dollar:]
                    else:
                        buffer = "" # $が見つからなければ全て破棄
                    
    except serial.SerialException as e:
        print(f"[ERROR] Serial port {GNSS_PORT} error: {e}")
        eventlet.sleep(5) 
    except Exception as e:
        print(f"[ERROR] GNSS read failed: {e}")
        eventlet.sleep(1) 

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@socketio.on('connect')
def connect():
    print(f'Client connected from {request.sid}')
    socketio.emit('gnss_history', list(gnss_data_history), to=request.sid)

@socketio.on('ping')
def handle_ping(data):
    print(f"Received ping from client: {data} from {request.sid}")
    socketio.emit('pong', {'message': 'Hello from server!'}, to=request.sid)

def emit_gnss():
    while True:
        socketio.emit('gnss', gnss_data)
        eventlet.sleep(0.2) # 約5Hzでデータを送信

if __name__ == '__main__':
    threading.Thread(target=read_gnss, daemon=True).start()
    socketio.start_background_task(emit_gnss)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)


