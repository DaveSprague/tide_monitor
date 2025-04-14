import sys
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import serial
from serial.tools import list_ports
from datetime import datetime
import csv
import re
import os
os.environ["DISPLAY"] = ":0"


from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QComboBox, QLabel, QTextEdit
from PyQt5.QtCore import QThread, pyqtSignal
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator

def get_data_directory():
    """Get the appropriate directory for storing application data"""
    if getattr(sys, 'frozen', False):
        # Running as bundled exe/app
        if sys.platform == 'darwin':  # macOS
            data_dir = os.path.expanduser('~/Library/Application Support/TideSensorPlotter')
        elif sys.platform == 'win32':  # Windows
            data_dir = os.path.join(os.environ.get('APPDATA'), 'TideSensorPlotter')
        else:
            raise RuntimeError("Unsupported platform")
    else:
        # Running in development
        data_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create directory if it doesn't exist
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    
    return data_dir

# Define data file path
data_file = os.path.join(get_data_directory(), 'tide_sensor_data.csv')

def read_data_from_file(file_path):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                reader = csv.reader(file)
                next(reader)  # Skip the header row
                return [(datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S'), float(row[1]), float(row[2]), float(row[3]), float(row[4])) for row in reader]
    except Exception as e:
        pass
        # print(f"Error reading from file: {e}")
    return []

def write_data_to_file(file_path, data):
    try:
        file_exists = os.path.isfile(file_path)
        with open(file_path, 'a') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(['Timestamp', 'Battery Voltage (V)', 'Solar Voltage (V)', 'Ultrasonic Range', 'RSSI'])
            for row in data:
                writer.writerow(row)
        # print(f"Data written to {file_path}")
    except Exception as e:
        pass
        # print(f"Error writing to file: {e}")

def parse_message(message):
    """Extract field values from the incoming message."""
    field_map = {
        'V': 'battery_voltage',
        's': 'solar_voltage',
        'S': 'sensor_id',
        'C': 'msg_count',
        'U': 'ultrasonic_range',
        'r': 'rssi',
        'n': 'signal_to_noise_ratio'
    }
    
    data = {}
    
    matches = re.findall(r'([A-Za-z])(-?\d+)', message)
    # example: S1,V4106,C55,U841,s6835,r-58,n12
    for key, value in matches:
        if key in field_map:
            if key == 'V' or key == 's':
                data[field_map[key]] = int(value) / 1000.0  # Convert milliVolts to Volts
            else:
                data[field_map[key]] = int(value)
    
    return data

class SerialReaderThread(QThread):
    data_updated = pyqtSignal(list)
    message_received = pyqtSignal(str)

    def __init__(self, serial_port, baudrate=115200):
        super().__init__()
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.running = True

    def run(self):
        ser = serial.Serial(self.serial_port, self.baudrate, timeout=1)
        data = read_data_from_file(data_file)
        # print(f"Initial data loaded from {data_file}: {data}")

        while self.running:
            if ser.in_waiting > 0:
                line = ser.readline()
                # print(line)  # Print the raw line for debugging
                decoded_line = line.decode('utf-8', errors='ignore').strip()
                self.message_received.emit(datetime.now().strftime('%Y-%m-%d %H:%M:%S') + " :: " + decoded_line)
                if len(decoded_line) < 10 or decoded_line[0] != 'S' or len(decoded_line) > 40:
                    continue
                parsed_data = parse_message(decoded_line)
                battery = parsed_data.get('battery_voltage')
                solar = parsed_data.get('solar_voltage')
                ultrasonic = parsed_data.get('ultrasonic_range')
                rssi = parsed_data.get('rssi')
                # print(f"{datetime.now()}  Battery={battery}, Solar={solar}, Ultrasonic={ultrasonic}, RSSI={rssi}")  # Print parsed values for debugging
                if battery is not None and solar is not None and ultrasonic is not None and rssi is not None:
                    timestamp = datetime.now()
                    data.append((timestamp, battery, solar, ultrasonic, rssi))
                    write_data_to_file(data_file, [(timestamp.strftime('%Y-%m-%d %H:%M:%S'), battery, solar, ultrasonic, rssi)])
                    self.data_updated.emit(data)

        ser.close()

    def stop(self):
        self.running = False
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        matplotlib.use('Qt5Agg')

        self.setWindowTitle("Serial Data Plotter")
        self.setGeometry(100, 100, 2000, 1200)

        self.serial_reader_thread = None

        layout = QVBoxLayout()

        # Create a horizontal layout for the controls
        controls_layout = QHBoxLayout()

        # Serial port selection
        port_group = QHBoxLayout()
        self.port_label = QLabel("Port:")
        port_group.addWidget(self.port_label)
        self.port_combo = QComboBox()
        self.port_combo.addItems(self.get_serial_ports())
        port_group.addWidget(self.port_combo)
        controls_layout.addLayout(port_group)

        # Add some spacing
        controls_layout.addSpacing(20)

        # Start/Stop buttons
        button_group = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_reading)
        self.start_button.setEnabled(False)
        button_group.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_reading)
        self.stop_button.setEnabled(True)
        button_group.addWidget(self.stop_button)

        # Add delete button
        self.delete_button = QPushButton("Delete Data")
        self.delete_button.clicked.connect(self.delete_data)
        button_group.addWidget(self.delete_button)

        controls_layout.addLayout(button_group)

        # Add some spacing
        controls_layout.addSpacing(20)

        # Message display
        message_group = QHBoxLayout()
        self.message_label = QLabel("Latest Message:")
        message_group.addWidget(self.message_label)
        self.message_display = QTextEdit()
        self.message_display.setReadOnly(True)
        self.message_display.setMaximumHeight(50)  # Limit height to one or two lines
        message_group.addWidget(self.message_display)
        controls_layout.addLayout(message_group)

        # Add the controls layout to the main layout
        layout.addLayout(controls_layout)

        # Matplotlib figure
        self.fig, self.axs = plt.subplots(2, 2, figsize=(18, 12))
        self.fig.tight_layout(pad=6.0)

        # Integrate the Matplotlib figure into the PyQt layout
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.start_reading()

    def get_serial_ports(self):
        # ports = [port.device for port in list_ports.comports() if port.device.startswith('/dev/cu.usbserial')]
        ports = [port.device for port in list_ports.comports() ]
        return ports

    def start_reading(self):
        serial_port = self.port_combo.currentText()
        self.serial_reader_thread = SerialReaderThread(serial_port)
        self.serial_reader_thread.data_updated.connect(self.update_plot_data)
        self.serial_reader_thread.message_received.connect(self.display_message)
        self.serial_reader_thread.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_reading(self):
        if self.serial_reader_thread:
            self.serial_reader_thread.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def delete_data(self):
        if os.path.exists(data_file):
            os.remove(data_file)
            # print(f"Deleted {data_file}")
        else:
            pass
            # print(f"{data_file} does not exist")

    def display_message(self, message):
        self.message_display.append(message)

    def update_plot_data(self, data):
        # print("Data updated:", data[-1])  # Debug print
        self.data = data
        self.update_plot()

    def update_plot(self, frame=None):
        if not hasattr(self, 'data') or not self.data:
            return

        # print("Updating plot with data:", self.data[-1])  # Debug print

        data = self.data[-20000:]  # Limit data to the last 10000 points

        # Convert to DataFrame for easy plotting
        df = pd.DataFrame(data, columns=['Timestamp', 'Battery Voltage (V)', 'Solar Voltage (V)', 'Ultrasonic Range', 'RSSI'])
        df.set_index('Timestamp', inplace=True)

        # Replace missing data with NaN
        df.replace({0: np.nan}, inplace=True)

        for ax in self.axs.flat:
            ax.clear()

        date_format = mdates.DateFormatter('%Y-%m-%d\n%H:%M:%S')
        date_locator = mdates.MinuteLocator(interval=5)  # Set interval to 5 minutes

        self.axs[0, 0].plot(df.index, df['Ultrasonic Range'], label='Ultrasonic Range', color='tab:green')
        self.axs[0, 0].set_ylim(0, max(1200, df['Ultrasonic Range'].max()))
        self.axs[0, 0].set_xlabel("Time", fontsize=10)
        self.axs[0, 0].set_ylabel("Ultrasonic Range", fontsize=10)
        self.axs[0, 0].set_title("Ultrasonic Range Over Time", fontsize=12, loc='left')
        self.axs[0, 0].legend(loc='upper left', fontsize=10)
        self.axs[0, 0].tick_params(axis='both', labelsize=10)
        self.axs[0, 0].xaxis.set_major_formatter(date_format)
        self.axs[0, 0].xaxis.set_major_locator(date_locator)
        self.axs[0, 0].xaxis.set_major_locator(MaxNLocator(nbins=6))


        self.axs[0, 1].plot(df.index, df['RSSI'], label='RSSI', color='tab:red')
        self.axs[0, 1].set_ylim(-150, max(0, df['RSSI'].max()))
        self.axs[0, 1].set_xlabel("Time", fontsize=10)
        self.axs[0, 1].set_ylabel("RSSI", fontsize=10)
        self.axs[0, 1].set_title("RSSI Over Time", fontsize=12, loc='left')
        self.axs[0, 1].legend(loc='upper left', fontsize=10)
        self.axs[0, 1].tick_params(axis='both', labelsize=10)
        self.axs[0, 1].xaxis.set_major_formatter(date_format)
        self.axs[0, 1].xaxis.set_major_locator(date_locator)
        self.axs[0, 1].xaxis.set_major_locator(MaxNLocator(nbins=6))  # Limit the number of ticks

        self.axs[1, 0].plot(df.index, df['Battery Voltage (V)'], label='Battery Voltage', color='tab:blue')
        self.axs[1, 0].set_ylim(1.0, max(4.4, df['Battery Voltage (V)'].max()))
        self.axs[1, 0].set_xlabel("Time", fontsize=10)
        self.axs[1, 0].set_ylabel("Battery Voltage (V)", fontsize=10)
        self.axs[1, 0].set_title("Battery Voltage Over Time", fontsize=12, loc='left')
        self.axs[1, 0].legend(loc='upper left', fontsize=10)
        self.axs[1, 0].tick_params(axis='both', labelsize=10)
        self.axs[1, 0].xaxis.set_major_formatter(date_format)
        self.axs[1, 0].xaxis.set_major_locator(date_locator)
        self.axs[1, 0].xaxis.set_major_locator(MaxNLocator(nbins=6))  # Limit the number of ticks

        self.axs[1, 1].plot(df.index, df['Solar Voltage (V)'], label='Solar Voltage', color='tab:orange')
        self.axs[1, 1].set_ylim(0, 9)
        self.axs[1, 1].set_xlabel("Time", fontsize=10)
        self.axs[1, 1].set_ylabel("Solar Voltage (V)", fontsize=10)
        self.axs[1, 1].set_title("Solar Voltage Over Time", fontsize=12, loc='left')
        self.axs[1, 1].legend(loc='upper left', fontsize=10)
        self.axs[1, 1].tick_params(axis='both', labelsize=10)
        self.axs[1, 1].xaxis.set_major_formatter(date_format)
        self.axs[1, 1].xaxis.set_major_locator(date_locator)
        self.axs[1, 1].xaxis.set_major_locator(MaxNLocator(nbins=6))  # Limit the number of ticks

        self.canvas.draw()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())  # Note the underscore after execs
