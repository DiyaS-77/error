import dbus
import dbus.service
import dbus.mainloop.glib
import os
import re
import subprocess
import time
import logging

from PyQt6 import sip
from logger import Logger

from PyQt6.QtCore import QFileSystemWatcher
from PyQt6.QtWidgets import QTextBrowser
from Backend_lib.Linux import hci_commands as hci
from utils import run

from gi.repository import GObject

# Set the D-Bus main loop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class BluetoothDeviceManager:
    """
    A class for managing Bluetooth devices using the BlueZ D-Bus API.

    This manager provides capabilities for discovering, pairing, connecting,
    streaming audio (A2DP), media control (AVRCP), and removing Bluetooth devices.
    """

    def __init__(self,interface=None,log=None,log_path=None):
        """
        Initialize the BluetoothDeviceManager by setting up the system bus and adapter.
        """
        self.interface = interface
        if self.interface:
            self.bus = dbus.SystemBus()
            self.adapter_path = f'/org/bluez/{self.interface}'
            self.adapter_proxy = self.bus.get_object('org.bluez', self.adapter_path)
            self.adapter = dbus.Interface(self.adapter_proxy, 'org.bluez.Adapter1')
            self.device_address=None
            self.stream_process = None
            self.device_path = None
            self.device_address = None
            self.device_sink = None
            self.devices = {}
            self.last_session_path = None
            self.opp_process = None

        self.log=log
        if self.log:
            self.bd_address = None
            self.controllers_list = {}
            self.handles = None
            self.interface = None
            self.log_path = None

        self.log_path = log_path
        if self.log_path:
            self.log = Logger("UI")

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

            self._watchers = {}  # Track QFileSystemWatcher per file
            self._last_positions = {}  # Track last read position per file


#---------CONTROLLER DETAILS----------------------#
    def get_controllers_connected(self):
        """
        Returns the list of controllers connected to the host.

        args : None
        Returns:
            dict: Dictionary with BD address as key and interface as value.
        """
        result = run(self.log, 'hciconfig -a | grep -B 2 \"BD A\"')
        result = result.stdout.split("--")
        if result[0]:
            for res in result:
                res = res.strip("\n").replace('\n', '')
                if match := re.match('(.*):	Type:.+BD Address: (.*)  ACL(.*)', res):
                    self.controllers_list[match[2]] = match[1]
        self.log.info("Controllers {} found on host".format(self.controllers_list))
        return self.controllers_list

    def get_controller_interface_details(self):
        """
        Gets the controller's interface and bus details.

        args: None
        Returns:
            str: Interface and Bus information.
        """
        self.interface = self.controllers_list[self.bd_address]
        result = run(self.log, f"hciconfig -a {self.interface} | grep Bus")
        return f"Interface: {self.interface} \t Bus: {result.stdout.split('Bus:')[1].strip()}"

    def convert_mac_little_endian(self, address):
        """
        Converts MAC (BD) address to little-endian format.

        Args:
            address (str): BD address in normal format (e.g., 'AA:BB:CC:DD:EE:FF').

        Returns:
            str: BD address in little-endian format (e.g., 'FF EE DD CC BB AA').
        """
        addr = address.split(':')
        addr.reverse()
        return ' '.join(addr)

    def convert_to_little_endian(self, num, num_of_octets):
        """
        Converts a number to little-endian hexadecimal representation.

        Args:
            num (int or str): Number to be converted.
            num_of_octets (int): Number of octets to format the result.

        Returns:
            str: Little-endian formatted hex string.
        """
        data = None
        if isinstance(num, str) and '0x' in num:
            data = num.replace("0x", "")
        elif isinstance(num, str) and '0x' not in num:
            data = int(num)
            data = str(hex(data)).replace("0x", "")
        elif isinstance(num, int):
            data = str(hex(num)).replace("0x", "")
        while True:
            if len(data) == (num_of_octets * 2):
                break
            data = "0" + data
        out = [(data[i:i + 2]) for i in range(0, len(data), 2)]
        out.reverse()
        return ' '.join(out)

    def run_hci_cmd(self, ogf, command, parameters=None):
        """
        Executes an HCI command with provided parameters.

        Args:
            ogf (str): Opcode Group Field (e.g., '0x03').
            command (str): Specific HCI command name.
            parameters (list): List of parameters for the command.

        Returns:
            subprocess.CompletedProcess: Result of command execution.
        """
        _ogf = ogf.lower().replace(' ', '_')
        _ocf_info = getattr(hci, _ogf)[command]
        hci_command = 'hcitool -i {} cmd {} {}'.format(self.interface, hci.hci_commands[ogf], _ocf_info[0])
        for index in range(len(parameters)):
            param_len = list(_ocf_info[1][index].values())[1] if len(
                _ocf_info[1][index].values()) > 1 else None
            if param_len:
                parameter = self.convert_to_little_endian(parameters[index], param_len)
            else:
                parameter = parameters[index].replace('0x', '')
            hci_command = ' '.join([hci_command, parameter])
        self.log.info(f"Executing command: {hci_command}")
        return run(self.log, hci_command)

    def get_connection_handles(self):
        """
        Retrieves active Bluetooth connection handles for the current interface.

        args: None
        Returns:
            dict: Dictionary of connection handles with hex values.
        """
        hcitool_con_cmd = f"hcitool -i {self.interface} con"
        self.handles = {}
        result = run(self.log, hcitool_con_cmd)
        results = result.stdout.split('\n')
        for line in results:
            if 'handle' in line:
                handle = (line.strip().split('state')[0]).replace('< ', '').strip()
                self.handles[handle] = hex(int(handle.split(' ')[-1]))
        return self.handles


    def run_command(self, command, log_file=None):
        output = subprocess.run(command, shell=True, capture_output=True, text=True)
        logging.info(f"Command: {command}\nOutput: {output.stdout}")
        return output

#-------------LOGGING------------------------#
    def _watch_log_file(self, log_file, text_browser: QTextBrowser):
        if not log_file or not os.path.exists(log_file) or not text_browser:
            return

        if log_file in self._watchers:
            return

        watcher = QFileSystemWatcher()
        watcher.addPath(log_file)
        watcher.fileChanged.connect(lambda: self._read_new_logs(log_file, text_browser))
        self._watchers[log_file] = watcher
        self._last_positions[log_file] = 0

    def _read_new_logs(self, log_file, text_browser):
        try:
            if text_browser is None or sip.isdeleted(text_browser):
                return

            last_pos = self._last_positions.get(log_file, 0)

            with open(log_file, 'r') as f:
                f.seek(last_pos)
                new_logs = f.read()
                if new_logs:
                    text_browser.append(new_logs)
                    text_browser.verticalScrollBar().setValue(
                        text_browser.verticalScrollBar().maximum()
                    )
                self._last_positions[log_file] = f.tell()

        except Exception as e:
            print(f"[ERROR] Failed to read log file: {e}")

    def start_dbus_service(self):
        print("Starting D-Bus service...")
        dbus_command = "/usr/local/bluez/dbus-1.12.20/bin/dbus-daemon --system --nopidfile"
        self.dbus_process = subprocess.Popen(dbus_command, shell=True)
        print("D-Bus service started successfully.")

    def start_bluetoothd_logs(self, log_text_browser=None):
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

        if log_text_browser:
            self._watch_log_file(self.bluetoothd_log_name, log_text_browser)

        print(f"[INFO] Bluetoothd logs started: {self.bluetoothd_log_name}")
        return True

    def start_pulseaudio_logs(self, log_text_browser=None):
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

        if log_text_browser:
            self._watch_log_file(self.pulseaudio_log_name, log_text_browser)

        print(f"[INFO] Pulseaudio logs started: {self.pulseaudio_log_name}")
        return True

    def stop_bluetoothd_logs(self):
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

            #if log_text_browser:
             #   self._watch_log_file(self.hcidump_log_name, log_text_browser)

            print(f"[INFO] hcidump process started: {self.hcidump_log_name}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to start hcidump: {e}")
            return False

    def stop_dump_logs(self):
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
        self.interface = interface
        details = {}
        self.run_command(f'hciconfig -a {self.interface} up')
        result = self.run_command(f'hciconfig -a {self.interface}')

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
            elif match := re.match(r'HCI Version: ([^ ]+ \([^)]+\))', line):
                details['HCI Version'] = match[1]
            elif match := re.match(r'LMP Version: ([^ ]+ \([^)]+\))', line):
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


    def start_discovery(self):
        """
        Start scanning for nearby Bluetooth devices.
        """
        self.adapter.StartDiscovery()

    def stop_discovery(self):
        """
        Stop Bluetooth device discovery.
        """
        self.adapter.StopDiscovery()

    def power_on_adapter(self):
        """
        Power on the local Bluetooth adapter.
        """
        adapter = dbus.Interface(
            self.bus.get_object("org.bluez", self.adapter_path),
            "org.freedesktop.DBus.Properties"
        )
        adapter.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))

    def inquiry(self, timeout):
        """
        Scan for nearby Bluetooth devices for a specified duration.

        :param timeout: Duration in seconds to scan for devices.
        :return: List of discovered devices in the format "Alias (Address)".
        """
        self.start_discovery()
        time.sleep(timeout)
        self.stop_discovery()

        discovered = []
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                device_props = dbus.Interface(self.bus.get_object("org.bluez", path),
                                              dbus_interface="org.freedesktop.DBus.Properties")
                try:
                    address = device_props.Get("org.bluez.Device1", "Address")
                    alias = device_props.Get("org.bluez.Device1", "Alias")
                    discovered.append(f"{alias} ({address})")
                except:
                    continue
        return discovered

    def _get_device_path(self, address):
        """
        Format the Bluetooth address to get the BlueZ D-Bus object path.

        :param address: Bluetooth device MAC address.
        :return: D-Bus object path.
        """
        formatted_address = address.replace(":", "_")
        return f"/org/bluez/{self.interface}/dev_{formatted_address}"


    def find_device_path(self, address, interface):
        #adapter_path = f"/org/bluez/{interface}"
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()
        formatted_address = address.replace(":", "_").upper()

        for path, interfaces in objects.items():
            if f"/{interface}/dev_{formatted_address}" in path:
                if "org.bluez.Device1" in interfaces:
                    return path

        return None

    def br_edr_connect(self, address, interface):
        device_path = self.find_device_path(address, interface)
        if device_path:
            try:
                device = dbus.Interface(self.bus.get_object("org.bluez", device_path),
                                        dbus_interface="org.bluez.Device1")
                device.Connect()

                props = dbus.Interface(self.bus.get_object("org.bluez", device_path),
                                       "org.freedesktop.DBus.Properties")
                connected = props.Get("org.bluez.Device1", "Connected")
                return connected
            except Exception as e:
                print(f"Connection failed: {e}")
        else:
            print("Device path not found for connection")
        return False

    def disconnect_le_device(self, address, interface):
        device_path = self.find_device_path(address, interface)
        if device_path:
            try:
                device = dbus.Interface(self.bus.get_object("org.bluez", device_path), "org.bluez.Device1")
                props = dbus.Interface(self.bus.get_object("org.bluez", device_path), "org.freedesktop.DBus.Properties")
                connected = props.Get("org.bluez.Device1", "Connected")
                if not connected:
                    print(f"Device {address} is already disconnected.")
                    return True
                device.Disconnect()
                return True
            except dbus.exceptions.DBusException as e:
                print(f"Error disconnecting device {address}: {e}")
        return False

    def remove_device(self, address, interface):
        adapter_path = f"/org/bluez/{interface}"
        obj = self.bus.get_object("org.bluez", "/")
        manager = dbus.Interface(obj, "org.freedesktop.DBus.ObjectManager")
        objects = manager.GetManagedObjects()


        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                if interfaces["org.bluez.Device1"].get("Address") == address and path.startswith(adapter_path):
                    try:
                        adapter = dbus.Interface(
                            self.bus.get_object("org.bluez", self.adapter_path),
                            "org.bluez.Adapter1"
                        )
                        adapter.RemoveDevice(path)
                        return True
                    except dbus.exceptions.DBusException as e:
                        print(f"Error removing device {address}: {e}")
                        return False
        print(f"Device with address {address} not found on {interface}")
        return True  # already removed


    def le_connect(self, address, interface):
        device_path = self.find_device_path(address, interface)
        if device_path:
            try:
                device = dbus.Interface(
                    self.bus.get_object("org.bluez", device_path),
                    dbus_interface="org.bluez.Device1"
                )
                device.ConnectProfile('0000110e-0000-1000-8000-00805f9b34fb')
            except Exception as e:
                print("LE Connection failed:", e)

    def _get_device_interface(self, device_path):
        """
        Get the org.bluez.Device1 interface for the specified device path.

        :param device_path: D-Bus object path of the device.
        :return: DBus Interface for the device.
        """
        return dbus.Interface(
            self.bus.get_object("org.bluez", device_path),
            "org.bluez.Device1"
        )

    def pair(self, address, interface=None):
        """
        Pairs with a Bluetooth device using the given controller interface.

        :param address: Bluetooth MAC address.
        :param interface: e.g., 'hci0', 'hci1'
        :return: True if successfully paired, False otherwise.
        """
        device_path = self.find_device_path(address, interface)
        if device_path:
            try:
                device = dbus.Interface(self.bus.get_object("org.bluez", device_path),
                                        dbus_interface="org.bluez.Device1")
                device.Pair()

                # Wait until pairing is confirmed (optional)
                props = dbus.Interface(self.bus.get_object("org.bluez", device_path),
                                       "org.freedesktop.DBus.Properties")
                paired = props.Get("org.bluez.Device1", "Paired")
                if paired:
                    print(f"[Bluetooth] Successfully paired with {address} on {interface}")
                    return True
                else:
                    print(f"[Bluetooth] Pairing not confirmed with {address}")
                    return False

            except dbus.exceptions.DBusException as e:
                print(f"[Bluetooth] Pairing failed with {address} on {interface}: {e}")
                return False
        else:
            print(f"[Bluetooth] Device path not found for {address} on {interface}")
            return False

    def set_discoverable_on(self):
        """
        Makes the Bluetooth device discoverable.

        args: None
        return: None
        """
        print("Setting Bluetooth device to be discoverable...")
        command = f"hciconfig {self.interface} piscan"
        subprocess.run(command, shell=True)
        print("Bluetooth device is now discoverable.")

    def set_discoverable_off(self):
        """
        Makes the Bluetooth device non-discoverable.

        args: None
        return: None
        """
        print("Setting Bluetooth device to be non-discoverable...")
        command = f"hciconfig {self.interface} noscan"
        subprocess.run(command, shell=True)
        print("Bluetooth device is now non-discoverable.")

    def is_device_paired(self, device_address):
        """
        Checks if the specified device is paired.

        Args:
            device_address (str): Bluetooth MAC address.

        Returns:
            bool: True if paired, False otherwise.
        """
        device_path = self.find_device_path(device_address,interface=self.interface)
        if not device_path:
            return False

        props = dbus.Interface(
            self.bus.get_object("org.bluez", device_path),
            "org.freedesktop.DBus.Properties"
        )
        try:
            return props.Get("org.bluez.Device1", "Paired")
        except dbus.exceptions.DBusException:
            return False

    def is_device_connected(self, device_address):
        """
        Checks if the specified device is connected.

        Args:
            device_address (str): Bluetooth MAC address.

        Returns:
            bool: True if connected, False otherwise.
        """
        device_path = self.find_device_path(device_address, interface=self.interface)
        if not device_path:
            print(f"[DEBUG] Device path not found for {device_address} on {self.interface}")
            return False

        try:
            props = dbus.Interface(
                self.bus.get_object("org.bluez", device_path),
                "org.freedesktop.DBus.Properties"
            )
            connected = props.Get("org.bluez.Device1", "Connected")

            # Extra validation: make sure device is under the correct adapter/interface
            if self.interface not in device_path:
                print(f"[DEBUG] Device path {device_path} does not match interface {self.interface}")
                return False

            return connected

        except dbus.exceptions.DBusException as e:
            print(f"[DEBUG] DBusException while checking connection: {e}")
            return False
    def refresh_device_list(self):
        """
        Updates the internal device list with currently available devices.

        args: None
        returns: None
        """
        self.devices.clear()
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                props = interfaces["org.bluez.Device1"]
                address = props.get("Address")
                name = props.get("Name", "Unknown")
                uuids = props.get("UUIDs", [])
                connected = props.get("Connected", False)
                if address:
                    self.devices[address] = {
                        "Name": name,
                        "UUIDs": uuids,
                        "Connected": connected,
                    }

    def get_paired_devices(self, interface=None):
        paired = {}
        adapter_path = f"/org/bluez/{interface}"
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                props = interfaces["org.bluez.Device1"]
                if props.get("Paired", False) and props.get("Adapter") == adapter_path:
                    address = props.get("Address")
                    name = props.get("Name", "Unknown")
                    paired[address] = name
        return paired

    def get_connected_devices(self, interface=None):
        connected = {}
        adapter_path = f"/org/bluez/{interface}"
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                props = interfaces["org.bluez.Device1"]
                if props.get("Connected", False) and props.get("Adapter") == adapter_path:
                    address = props.get("Address")
                    name = props.get("Name", "Unknown")
                    connected[address] = name
        return connected


#--------------------OPP FUNCTIONS---------------------#
    def send_file_via_obex(self, device_address, file_path):
        """
        Send a file to a Bluetooth device via OBEX (Object Push Profile).

        args:
            device_address (str): Bluetooth address of the target device (e.g., 'XX:XX:XX:XX:XX:XX').
            file_path (str): Absolute path to the file to send.

        Returns:
            tuple: A tuple of (status, message). Status can be 'complete', 'error', or 'unknown'.
        """
        if not os.path.exists(file_path):
            msg = f"File does not exist: {file_path}"
            print(msg)
            return "error", msg

        try:
            session_bus = dbus.SessionBus()
            obex_service = "org.bluez.obex"
            manager_obj = session_bus.get_object(obex_service, "/org/bluez/obex")
            manager = dbus.Interface(manager_obj, "org.bluez.obex.Client1")

            # Clean up old session if it exists
            if self.last_session_path:
                try:
                    manager.RemoveSession(self.last_session_path)
                    print(f"Removed previous session: {self.last_session_path}")
                    time.sleep(1.0)
                except Exception as e:
                    print(f"Previous session cleanup failed: {e}")

            # Create a new OBEX session
            session_path = manager.CreateSession(device_address, {"Target": dbus.String("opp")})
            session_path = str(session_path)
            self.last_session_path = session_path
            print(f"Created OBEX session: {session_path}")

            # Push the file
            opp_obj = session_bus.get_object(obex_service, session_path)
            opp = dbus.Interface(opp_obj, "org.bluez.obex.ObjectPush1")
            transfer_path = opp.SendFile(file_path)
            transfer_path = str(transfer_path)
            print(f"Transfer started: {transfer_path}")

            # Monitor transfer status
            transfer_obj = session_bus.get_object(obex_service, transfer_path)
            transfer_props = dbus.Interface(transfer_obj, "org.freedesktop.DBus.Properties")

            status = "unknown"
            for _ in range(40):
                status = str(transfer_props.Get("org.bluez.obex.Transfer1", "Status"))
                print(f"Transfer status: {status}")
                if status in ["complete", "error"]:
                    break
                time.sleep(0.5)

            # Always remove session
            try:
                manager.RemoveSession(session_path)
                self.last_session_path = None
                print("Session removed after transfer.")
            except Exception as e:
                print(f"Error removing session: {e}")

            return status, f"Transfer finished with status: {status}"

        except Exception as e:
            msg = f"OBEX file send failed: {e}"
            print(msg)
            return "error", msg

    def start_opp_receiver(self, save_directory="/tmp"):
        """
        Start an OBEX Object Push server to receive files over Bluetooth.

        args:
            save_directory (str): Directory where received files will be stored.

        Returns:
            bool: True if server started successfully, False otherwise.
        """
        try:
            if not os.path.exists(save_directory):
                os.makedirs(save_directory)

            if self.opp_process and self.opp_process.poll() is None:
                self.opp_process.terminate()
                self.opp_process.wait()
                print("Previous OPP server stopped.")

            self.opp_process = subprocess.Popen([
                "obexpushd",
                "-B",  # Bluetooth
                "-o", save_directory,
                "-n"  # No confirmation prompt
            ])

            print(f"OPP server started. Receiving files to {save_directory}")
            return True
        except Exception as e:
            print(f"Error starting OPP server: {e}")
            return False

    def stop_opp_receiver(self):
        """
        Stop the OBEX Object Push server if it's currently running.

        args: None
        returns: None
        """
        if self.opp_process and self.opp_process.poll() is None:
            self.opp_process.terminate()
            self.opp_process.wait()
            print("OPP server stopped.")

# -----------A2DP FUNCTIONS----------------------------#
    def set_device_address(self, address):
        """
        Sets the current Bluetooth device for media streaming/control.

        Args:
            address (str): Bluetooth MAC address.
        returns:
            None
        """
        self.device_address = address
        self.device_path = self.find_device_path(address,interface=self.interface)
        self.device_sink = self.get_sink_for_device(address)

    def get_sink_for_device(self, address):
        """
        Finds the PulseAudio sink associated with a Bluetooth device.

        Args:
            address (str): Bluetooth MAC address.

        Returns:
            str | None: Sink name if found, else None.
        """
        try:
            sinks_output = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True)
            address_formatted = address.replace(":", "_").lower()
            for line in sinks_output.splitlines():
                if address_formatted in line.lower():
                    return line.split()[1]
        except Exception as e:
            print(f"Error getting sink for device: {e}")
        return None

    def is_a2dp_streaming(self) -> bool:
        """
        Check if an A2DP stream is currently active using PulseAudio.

        Returns:
            bool: True if audio is streaming to a Bluetooth A2DP sink, False otherwise.
        """

        try:
            # Get all active sink inputs (audio streams)
            output = subprocess.check_output("pactl list sink-inputs", shell=True, text=True)

            # Check if any sink input is directed to a Bluetooth A2DP sink
            if "bluez_sink" in output:
                return True

            return False

        except subprocess.CalledProcessError:
            # pactl command failed
            return False


    def start_a2dp_stream(self, address, filepath=None):
        device_path = self.find_device_path(address,interface=self.interface)
        print(device_path)
        if not device_path:
            return "Device not found"
        try:
            # Ensure device_address is stored for stop_a2dp_stream
            self.device_address = address # Store the address of the device being streamed to
            device = dbus.Interface(self.bus.get_object("org.bluez", device_path), "org.bluez.Device1")
            print(device)
            props = dbus.Interface(self.bus.get_object("org.bluez", device_path), "org.freedesktop.DBus.Properties")
            connected = props.Get("org.bluez.Device1", "Connected")
            if not connected:
                device.Connect()
                time.sleep(1.5)
            print(f"[A2DP] Connected to {address}")
            if not filepath:
                return "No audio file specified for streaming"

            # Convert MP3 to WAV if needed
            if filepath.endswith(".mp3"):
                wav_file = "/tmp/temp_audio.wav"
                if not self.convert_mp3_to_wav(filepath, wav_file):
                    return False
                filepath = wav_file

            self.stream_process = subprocess.Popen(
                ["aplay", filepath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            return f"Streaming started with {filepath}"
        except Exception as e:
            return f"A2DP stream error: {str(e)}"


    def convert_mp3_to_wav(self, audio_path, wav_path):
        """
        Convert an MP3 file to WAV format using ffmpeg.

        Args:
            audio_path (str): Path to the MP3 file.
            wav_path (str): Output path for the converted WAV file.

        Returns:
            bool: True if conversion succeeds, False otherwise.
        """
        try:
            subprocess.run(['ffmpeg', '-y', '-i', audio_path, wav_path], check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Conversion failed [mp3 to wav]: {e}")
            return False

    def stop_a2dp_stream(self):
        """
        Stop the current A2DP audio stream.

        :return: Status message.
        """
        if self.stream_process:
            self.stream_process.terminate()
            self.stream_process = None
            return "A2DP stream stopped"
        return "No active A2DP stream"

    def get_connected_a2dp_source_devices(self, interface):
        """
        Get a list of currently connected A2DP source devices on the given interface.

        Args:
            interface (str): Controller interface like 'hci0' or 'hci1'

        Returns:
            dict: Dictionary of connected A2DP source devices (MAC -> Name)
        """
        connected = {}
        adapter_path = f"/org/bluez/{interface}"
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()

        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                props = interfaces["org.bluez.Device1"]
                if props.get("Connected", False) and props.get("Adapter") == adapter_path:
                    uuids = props.get("UUIDs", [])
                    if any("110a" in uuid.lower() for uuid in uuids):  # A2DP Source UUID
                        address = props.get("Address")
                        name = props.get("Name", "Unknown")
                        connected[address] = name
        return connected

    def get_connected_a2dp_sink_devices(self, interface):
        """
        Get a list of currently connected A2DP sink devices on the given interface.

        Args:
            interface (str): Controller interface like 'hci0' or 'hci1'

        Returns:
            dict: Dictionary of connected A2DP sink devices (MAC -> Name)
        """
        connected = {}
        adapter_path = f"/org/bluez/{interface}"
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()

        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                props = interfaces["org.bluez.Device1"]
                if props.get("Connected", False) and props.get("Adapter") == adapter_path:
                    uuids = props.get("UUIDs", [])
                    if any("110b" in uuid.lower() for uuid in uuids):  # A2DP Sink UUID
                        address = props.get("Address")
                        name = props.get("Name", "Unknown")
                        connected[address] = name
        return connected


    def _get_media_control_interface(self, address, controller=None):
        """
        Retrieve the MediaControl1 interface for a given device.

        Args:
            address (str): The MAC address of the Bluetooth device.
            controller (str, optional): The controller interface (e.g., 'hci0', 'hci1').
                                        If None, will match any controller.

        Returns:
            dbus.Interface: The MediaControl1 D-Bus interface or None if not found.
        """
        try:
            om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()
            formatted_addr = address.replace(":", "_").upper()

            print("Searching for MediaControl1 interface...")
            for path, interfaces in objects.items():
                if "org.bluez.MediaControl1" in interfaces and formatted_addr in path:
                    if controller:
                        if f"/{controller}/dev_{formatted_addr}" in path:
                            print(f"Found MediaControl1 interface at: {path}")
                            return dbus.Interface(
                                self.bus.get_object("org.bluez", path),
                                "org.bluez.MediaControl1"
                            )
                    else:
                        print(f"Found MediaControl1 interface at: {path}")
                        return dbus.Interface(
                            self.bus.get_object("org.bluez", path),
                            "org.bluez.MediaControl1"
                        )

            print(f"No MediaControl1 interface found for device: {address} on controller: {controller or 'any'}")
        except Exception as e:
            print(f"Failed to get MediaControl1 interface: {e}")
        return None

    def media_control(self, command,address):
        """
        Send an AVRCP media control command to a connected A2DP device using the correct controller.

        Supported commands: play, pause, next, previous, rewind.

        :param command: The command to send as a string.
        :return: Result message.
        """
        self.address=address
        valid = {
            "play": "Play",
            "pause": "Pause",
            "next": "Next",
            "previous": "Previous",
            "rewind": "Rewind"
        }

        if command not in valid:
            return f"Invalid command: {command}"

        #om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        #objects = om.GetManagedObjects()

        # Filter MediaControl1 interfaces under the current adapter (e.g., hci0)

        try:
            control_iface =self._get_media_control_interface(address,self.interface)
            getattr(control_iface, valid[command])()
            return f"AVRCP {command} sent to {address}"
        except Exception as e:
            return f"Error sending AVRCP {command}: {str(e)}"

        return f"No MediaControl1 interface found under {self.interface} (is device connected via A2DP with AVRCP?)"