from PyQt6 import sip

from logger import Logger
from UI_lib.controller_lib import Controller
from PyQt6.QtCore import QFileSystemWatcher
from PyQt6.QtWidgets import QTextBrowser

import logging
import os
import re
import subprocess
import time
#import sip

class FileWatcher:
    """
    Watches a logfile for updates using QFileSystemWatcher and appends changes to a QTextBrowser.
    """
    def __init__(self, log_file, text_browser: QTextBrowser):
        """
        Initializes the file watcher.

        Args:
            log_file (str): Path to the log file.
            text_browser (QTextBrowser): UI element to update with new logs.
        """
        self.log_file = log_file
        self.text_browser = text_browser
        self.last_position = 0
        self.watcher = QFileSystemWatcher()
        self.watcher.addPath(log_file)
        self.watcher.fileChanged.connect(self._read_new_logs)



    def _read_new_logs(self):
        """
        Reads and appends new log content from the file.
        """
        try:
            if self.text_browser is None or sip.isdeleted(self.text_browser):
                #print("[WARN] QTextBrowser was deleted; skipping log append.")
                return

            with open(self.log_file, 'r') as f:
                f.seek(self.last_position)
                new_logs = f.read()
                if new_logs:
                    self.text_browser.append(new_logs)
                    self.text_browser.verticalScrollBar().setValue(
                        self.text_browser.verticalScrollBar().maximum()
                    )
                self.last_position = f.tell()

        except Exception as e:
            print(f"[ERROR] Failed to read log file: {e}")

    '''
    def _read_new_logs(self):
        """
        Reads and appends new log content from the file.
        """

        with open(self.log_file, 'r') as f:
            f.seek(self.last_position)
            new_logs = f.read()
            if new_logs:
                self.text_browser.append(new_logs)
                self.text_browser.verticalScrollBar().setValue(self.text_browser.verticalScrollBar().maximum())
            self.last_position = f.tell()
        #except Exception as e:
         #   print(f"[ERROR] Failed to read log file: {e}")
    '''

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def run_command(log_path, command, log_file=None):
    """
    Runs a shell command and logs the output.

    Args:
        log_path (str): Path where logs are stored.
        command (str): The shell command to execute.
        log_file: Optional file handle to log output to.

    Returns:
        CompletedProcess: The result of subprocess.run
    """
    output = subprocess.run(command, shell=True, capture_output=True, text=True)
    logging.info(f"Command: {command}\nOutput: {output.stdout}")
    return output


class BluezLogger:
    """
    Provides logging, monitoring, and control for Bluetoothd, Pulseaudio, and HCI dump processes.
    """

    def __init__(self, log_path):
        """
        Initializes the BluezLogger object.

        Args:
            log_path (str): Directory path for storing logs.
        """
        self.log_path = log_path
        self.log = Logger("UI")
        self.controller = Controller(self.log)

        self.bluetoothd_process = None
        self.pulseaudio_process = None
        self.hcidump_process = None

        self.bluetoothd_watcher = None
        self.pulseaudio_watcher = None
        self.hci_watcher = None

        self.bluetoothd_logfile_fd = None
        self.pulseaudio_logfile_fd = None
        self.logfile_fd = None

        self.bluetoothd_log_name = None
        self.pulseaudio_log_name = None
        self.hcidump_log_name = None

        self.interface = None

    def start_dbus_service(self):
        """
        Starts the system D-Bus service required for BlueZ.
        """
        print("Starting D-Bus service...")
        dbus_command = "/usr/local/bluez/dbus-1.12.20/bin/dbus-daemon --system --nopidfile"
        self.dbus_process = subprocess.Popen(dbus_command, shell=True)

        print("D-Bus service started successfully.")

    def start_bluetoothd_logs(self, log_text_browser=None):
        """
        Starts bluetoothd process and logs its output.

        Args:
            log_text_browser: Optional QTextBrowser to stream logs to.

        Returns:
            bool: True if bluetoothd started successfully.
        """
        self.bluetoothd_log_name = os.path.join(self.log_path, "bluetoothd.log")
        subprocess.run("pkill -f bluetoothd", shell=True)


        bluetoothd_command = '/usr/local/bluez/bluez-tools/libexec/bluetooth/bluetoothd -nd --compat'
        print(f"[INFO] Starting bluetoothd logs...{bluetoothd_command}")
        self.bluetoothd_process = subprocess.Popen(
            bluetoothd_command.split(),
            stdout=open(self.bluetoothd_log_name, 'a+'),
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )


        if log_text_browser is not None:
            self.bluetoothd_watcher = FileWatcher(self.bluetoothd_log_name, log_text_browser)

        print(f"[INFO] Bluetoothd logs started: {self.bluetoothd_log_name}")
        return True

    def start_pulseaudio_logs(self, log_text_browser=None):
        """
        Starts pulseaudio process and logs its output.

        Args:
            log_text_browser: Optional QTextBrowser to stream logs to.

        Returns:
            bool: True if pulseaudio started successfully.
        """
        self.pulseaudio_log_name = os.path.join(self.log_path, "pulseaudio.log")
        subprocess.run("pkill -f pulseaudio", shell=True)


        pulseaudio_command = '/usr/local/bluez/pulseaudio-13.0_for_bluez-5.65/bin/pulseaudio -vvv'
        print(f"[INFO] Starting pulseaudio logs...{pulseaudio_command}")
        self.pulseaudio_process = subprocess.Popen(
            pulseaudio_command.split(),
            stdout=open(self.pulseaudio_log_name, 'a+'),
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )


        if log_text_browser is not None:
            self.pulseaudio_watcher = FileWatcher(self.pulseaudio_log_name, log_text_browser)

        print(f"[INFO] Pulseaudio logs started: {self.pulseaudio_log_name}")
        return True

    def stop_bluetoothd_logs(self):
        """
        Stops the bluetoothd process.
        """
        print("[INFO] Stopping bluetoothd logs...")
        if self.bluetoothd_process:
            try:
                self.bluetoothd_process.terminate()
                self.bluetoothd_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.bluetoothd_process.kill()
                self.bluetoothd_process.wait()
            self.bluetoothd_process = None

    def stop_pulseaudio_logs(self):
        """
        Stops the pulseaudio process.
        """
        print("[INFO] Stopping pulseaudio logs...")
        if self.pulseaudio_process:
            try:
                self.pulseaudio_process.terminate()
                self.pulseaudio_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.pulseaudio_process.kill()
                self.pulseaudio_process.wait()
            self.pulseaudio_process = None

    def start_dump_logs(self, interface, log_text_browser=None):
        """
        Starts hcidump logs for a specific Bluetooth interface.

        Args:
            interface (str): HCI interface name (e.g., hci0).
            log_text_browser: Optional QTextBrowser to stream logs to.

        Returns:
            bool: True if started successfully, False otherwise.
        """
        try:
            if not interface:
                print("[ERROR] Interface is not provided for hcidump")
                return False

            subprocess.run(f"hciconfig {interface} up".split(), capture_output=True)


            self.hcidump_log_name = os.path.join(self.log_path, f"{interface}_hcidump.log")
            hcidump_command = f"/usr/local/bluez/bluez-tools/bin/hcidump -i {interface} -Xt"
            print(f"[INFO] Starting hcidump: {hcidump_command}")

            self.hcidump_process = subprocess.Popen(
                hcidump_command.split(),
                stdout=open(self.hcidump_log_name, 'a+'),
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True
            )


            if log_text_browser is not None:
                self.hci_watcher = FileWatcher(self.hcidump_log_name, log_text_browser)

            print(f"[INFO] hcidump process started: {self.hcidump_log_name}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to start hcidump: {e}")
            return False

    def stop_dump_logs(self):
        """
        Stops the running hcidump process and log monitoring.
        """
        print("[INFO] Stopping HCI dump logs")
        if self.hcidump_process:
            try:
                self.hcidump_process.terminate()
                self.hcidump_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.hcidump_process.kill()
                self.hcidump_process.wait()
            self.hcidump_process = None

        if self.interface:
            try:
                result = subprocess.run(['pgrep', '-f', f'hcidump.*{self.interface}'], capture_output=True, text=True)
                if result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        subprocess.run(['kill', '-TERM', pid])
                    time.sleep(1)
                    for pid in pids:
                        subprocess.run(['kill', '-KILL', pid])
            except Exception as e:
                print(f"[ERROR] Error killing hcidump: {e}")

        print("[INFO] HCI dump logs stopped successfully")


    def get_controller_details(self, interface=None):
        """
        Retrieves detailed information about the Bluetooth controller.

        Args:
            interface (str): HCI interface name (e.g., hci0).

        Returns:
            dict: Parsed controller details.
        """
        self.interface = interface
        details = {}
        run_command(self.log_path, f'hciconfig -a {self.interface} up')
        result = run_command(self.log_path, f'hciconfig -a {self.interface}')

        for line in result.stdout.split('\n'):
            line = line.strip()
            if match := re.match('BD Address: (.*) ACL(.*)', line):
                details['BD_ADDR'] = match[1]
            elif match := re.match('Link policy: (.*)', line):
                details['Link policy'] = match[1]
            elif match := re.match('Link mode: (.*)', line):
                details['Link mode'] = match[1]
            elif match := re.match('Name: (.*)', line):
                details['Name'] = match[1]
            elif match := re.match('Class: (.*)', line):
                details['Class'] = match[1]
            elif match := re.match('HCI Version: (.*) .+', line):
                details['HCI Version'] = match[1]
            elif match := re.match('LMP Version: (.*) .+', line):
                details['LMP Version'] = match[1]
            elif match := re.match('Manufacturer: (.*)', line):
                details['Manufacturer'] = match[1]

        self.name = details.get('Name')
        self.bd_address = details.get('BD_ADDR')
        self.link_policy = details.get('Link policy')
        self.link_mode = details.get('Link mode')
        self.hci_version = details.get('HCI Version')
        self.lmp_version = details.get('LMP Version')
        self.manufacturer = details.get('Manufacturer')

        return details