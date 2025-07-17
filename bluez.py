import dbus
import dbus.service
import dbus.mainloop.glib
import os
import subprocess
import time
from gi.repository import GObject
import mimetypes
from dbus.mainloop.glib import DBusGMainLoop

# Set the D-Bus main loop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)


class BluetoothDeviceManager:
    """
    A class for managing Bluetooth devices using the BlueZ D-Bus API.

    This manager provides capabilities for discovering, pairing, connecting,
    streaming audio (A2DP), media control (AVRCP), and removing Bluetooth devices.
    """

    def __init__(self,interface=None):
        """
        Initialize the BluetoothDeviceManager by setting up the system bus and adapter.
        """
        self.interface = interface
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
        Power on the local Bluetooth adapter using the Properties interface.
        """
        try:
            obj = self.bus.get_object("org.bluez", self.adapter_path)
            props_iface = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            props_iface.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            print("Adapter powered on successfully.")

        except dbus.exceptions.DBusException as e:
            if "Method \"Set\" with signature \"ssb\" on interface \"org.freedesktop.DBus.Properties\" doesn't exist" in str(
                    e):
                print(f"Error: BlueZ D-Bus 'Set' method for Adapter1.Powered not found.")

    '''
    def power_on_adapter(self):
        """
        Power on the local Bluetooth adapter.
        """
        adapter = dbus.Interface(
            self.bus.get_object("org.bluez", self.adapter_path),
            "org.freedesktop.DBus.Properties"
        )
        adapter.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))'''

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
        adapter_path = f"/org/bluez/{interface}"
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

    def unpair_device(self, address, interface):
        """
        Remove the bonded device from the system using the specified controller.

        :param address: Bluetooth device MAC address.
        :param interface: Controller interface (e.g., 'hci0', 'hci1')
        :return: True if removed or already gone, False otherwise.
        """
        adapter_path = f"/org/bluez/{interface}"
        print(adapter_path)
        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()

        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                props = interfaces["org.bluez.Device1"]
                if props.get("Address") == address and props.get("Adapter") == adapter_path:
                    try:
                        adapter = dbus.Interface(
                            self.bus.get_object("org.bluez", adapter_path),
                            "org.bluez.Adapter1"
                        )
                        adapter.RemoveDevice(path)
                        print(f"[Bluetooth] Removed device {address} on {interface}")
                        return True
                    except dbus.exceptions.DBusException as e:
                        print(f"[Bluetooth] Failed to remove {address} on {interface}: {e}")
                        return False

        print(f"[Bluetooth] Device {address} not found on {interface}")
        return True  # Considered success if already removed

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
                device.ConnectProfile('0000110e-0000-1000-8000-00805f9b34fb')  # A2DP
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

    '''
    def br_edr_connect(self, address):
        """
        Establish a BR/EDR connection to the specified Bluetooth device.

        :param address: Bluetooth device MAC address.
        :return: True if connected, False otherwise.
        """
        device_path = self.find_device_path(address)
        if device_path:
            try:
                device = dbus.Interface(self.bus.get_object("org.bluez", device_path),
                                        dbus_interface="org.bluez.Device1")
                device.Connect()

                props = dbus.Interface(self.bus.get_object("org.bluez", device_path),
                                       "org.freedesktop.DBus.Properties")
                connected = props.Get("org.bluez.Device1", "Connected")
                if connected:
                    print("Connection is successful")
                    return True
                else:
                    print("Connection attempted but not confirmed")
                    return False
            except Exception as e:
                print(f"Connection failed: {e}")
                return False
        else:
            print("Device path not found for connection")
            return False


    def disconnect_le_device(self, address):
        """
        Disconnect a Bluetooth LE device using BlueZ D-Bus interface.

        :param address: Bluetooth MAC address (e.g., 'C0:26:DA:00:12:34')
        :return: True if disconnect successful or not connected, False otherwise.
        """
        try:
            device_path = self._get_device_path(address)

            # Access device and its properties
            device = dbus.Interface(self.bus.get_object("org.bluez", device_path), "org.bluez.Device1")
            props = dbus.Interface(self.bus.get_object("org.bluez", device_path), "org.freedesktop.DBus.Properties")

            # Check if already disconnected
            connected = props.Get("org.bluez.Device1", "Connected")
            if not connected:
                print(f"[BluetoothDeviceManager] Device {address} is already disconnected.")
                return True

            # Perform disconnect
            print(f"[BluetoothDeviceManager] Disconnecting device {address}...")
            device.Disconnect()
            #time.sleep(1)  # Optional: allow async operations to complete

            print(f"[BluetoothDeviceManager] Device {address} disconnected successfully.")
            return True

        except dbus.exceptions.DBusException as e:
            print(f"[BluetoothDeviceManager] Error disconnecting device {address}: {e}")
            return False

    def remove_device(self, address):
        """
        Remove the bonded device from the system.

        :param address: Bluetooth device MAC address.
        :return: True if removed or already gone, False otherwise.
        """
        obj = self.bus.get_object("org.bluez", "/")
        manager = dbus.Interface(obj, "org.freedesktop.DBus.ObjectManager")
        objects = manager.GetManagedObjects()

        for path, interfaces in objects.items():
            if "org.bluez.Device1" in interfaces:
                if interfaces["org.bluez.Device1"].get("Address") == address:
                    print(f"[BluetoothDeviceManager] Removing device {path}")
                    try:
                        adapter = dbus.Interface(
                            self.bus.get_object("org.bluez", self.adapter_path),
                            "org.bluez.Adapter1"
                        )
                        adapter.RemoveDevice(path)
                        return True
                    except dbus.exceptions.DBusException as e:
                        if "org.freedesktop.DBus.Error.UnknownObject" in str(e):
                            print(f"[BluetoothDeviceManager] Device {address} already removed")
                            return True  # Still a success
                        else:
                            print(f"[BluetoothDeviceManager] Failed to remove {address}: {e}")
                            return False

        print(f"[BluetoothDeviceManager] Device with address {address} not found")
        return True  # Treat as success since it's already not present


    def le_connect(self, address):
        """
        Initiates Low Energy (LE) connection using a specific profile.

        Args:
            address (str): Bluetooth MAC address.
        returns:
            None
        """
        device_path = self.find_device_path(address)
        if device_path:
            try:
                device = dbus.Interface(
                    self.bus.get_object("org.bluez", device_path),
                    dbus_interface="org.bluez.Device1"
                )
                device.ConnectProfile('0000110e-0000-1000-8000-00805f9b34fb')  # HID Profile
            except Exception as e:
                print("LE Connection has failed:", e)
    '''
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
        device_path = self.find_device_path(device_address,interface=self.interface)
        if not device_path:
            return False

        props = dbus.Interface(
            self.bus.get_object("org.bluez", device_path),
            "org.freedesktop.DBus.Properties"
        )
        try:
            return props.Get("org.bluez.Device1", "Connected")
        except dbus.exceptions.DBusException:
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
            props = dbus.Interface(self.bus.get_object("org.bluez", device_path), "org.freedesktop.DBus.Properties")
            connected = props.Get("org.bluez.Device1", "Connected")
            if not connected:
                device.Connect()
                time.sleep(1.5)
            print(f"[A2DP] Connected to {address}")
            if not filepath:
                return "No audio file specified for streaming"
            self.stream_process = subprocess.Popen(
                ["aplay", filepath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            return f"Streaming started with {filepath}"
        except Exception as e:
            return f"A2DP stream error: {str(e)}"

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

    def media_control(self, command):
        """
        Send an AVRCP media control command to a connected A2DP device using the correct controller.

        Supported commands: play, pause, next, previous, rewind.

        :param command: The command to send as a string.
        :return: Result message.
        """
        valid = {
            "play": "Play",
            "pause": "Pause",
            "next": "Next",
            "previous": "Previous",
            "rewind": "Rewind"
        }

        if command not in valid:
            return f"Invalid command: {command}"

        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()

        # Filter MediaControl1 interfaces under the current adapter (e.g., hci0)
        for path, interfaces in objects.items():
            if "org.bluez.MediaControl1" in interfaces and f"/{self.interface}/" in path:
                try:
                    control_iface = dbus.Interface(self.bus.get_object("org.bluez", path), "org.bluez.MediaControl1")
                    getattr(control_iface, valid[command])()
                    return f"AVRCP {command} sent to {path}"
                except Exception as e:
                    return f"Error sending AVRCP {command}: {str(e)}"

        return f"No MediaControl1 interface found under {self.interface} (is device connected via A2DP with AVRCP?)"

    '''def get_connected_a2dp_sink_devices(self):
        """
        Get a list of currently connected A2DP sink devices.

        args: None
        Returns:
            dict: Dictionary of connected device MAC addresses and their names.
        """
        self.refresh_device_list()
        return {
            addr: dev["Name"]
            for addr, dev in self.devices.items()
            if dev["Connected"] and any("110b" in uuid.lower() for uuid in dev["UUIDs"])
        }

    def get_connected_a2dp_source_devices(self):
        """
        Get a list of currently connected A2DP source devices.

        args: None
        Returns:
            dict: Dictionary of connected device MAC addresses and their names.
        """
        self.refresh_device_list()
        return {
            addr: dev["Name"]
            for addr, dev in self.devices.items()
            if dev["Connected"] and any("110a" in uuid.lower() for uuid in dev["UUIDs"])
        }


    def media_control(self, command):
        """
        Send an AVRCP media control command to a connected A2DP device.

        Supported commands: play, pause, next, previous, rewind.

        :param command: The command to send as a string.
        :return: Result message.
        """
        valid = {
            "play": "Play",
            "pause": "Pause",
            "next": "Next",
            "previous": "Previous",
            "rewind": "FastRewind"
        }

        if command not in valid:
            return f"Invalid command: {command}"

        om = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        objects = om.GetManagedObjects()

        for path, interfaces in objects.items():
            if "org.bluez.MediaControl1" in interfaces:
                try:
                    control_iface = dbus.Interface(self.bus.get_object("org.bluez", path), "org.bluez.MediaControl1")
                    getattr(control_iface, valid[command])()
                    return f"AVRCP {command} sent to {path}"
                except Exception as e:
                    return f"Error sending AVRCP {command}: {str(e)}"
        return "No MediaControl1 interface found (is device connected as A2DP Source with AVRCP?)" '''