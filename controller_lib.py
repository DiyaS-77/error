import re

from Backend_lib.Linux import hci_commands as hci
from utils import run


class Controller:
    """
    Controller class for managing Bluetooth HCI interfaces, running commands, parsing logs,
    and handling controller-related utilities.
    """

    def __init__(self, log):
        """
        Initializes the Controller object with log and default attributes.

        Args:
            log: Logger object used to capture logging information.
        returns:
            None
        """
        self.pulseaudio_log_name = None
        self.pulseaudio_file_position = None
        self.pulseaudio_logfile_fd = None
        self.bluetoothd_file_position = None
        self.bluetoothd_logfile_fd = None
        self.bluetoothd_log_name = None
        self.bd_address = None
        self.controllers_list = {}
        self.handles = None
        self.log = log
        self.interface = None
        self.logfile_fd = None
        self.file_position = None
        self.hcidump_log_name = None
        self.hci_dump_started = False
        self.log_path = None

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

    def get_controller_details(self):
        """
        Returns details of the selected controller, including name, address, version, etc.

        args : None
        Returns:
            str: Multi-line string of controller details.
        """
        run(self.log, f"hciconfig -a {self.interface} up")
        result = run(self.log, f"hciconfig -a {self.interface}")
        details = ""
        result = result.stdout.split('\n')
        for line in result:
            line = line.strip()
            if match := re.match('BD Address: (.*)  ACL(.*)', line):
                details = '\n'.join([details, f"BD_ADDR: {match[1]}"])
            if match := re.match('Link policy: (.*)', line):
                details = '\n'.join([details, f"Link policy: {match[1]}"])
            if match := re.match('Link mode: (.*)', line):
                details = '\n'.join([details, f"Link mode: {match[1]}"])
            if match := re.match('Name: (.*)', line):
                details = '\n'.join([details, f"Name: {match[1]}"])
            if match := re.match('Class: (.*)', line):
                details = '\n'.join([details, f"Class: {match[1]}"])
            if match := re.match('HCI Version: (.*)  .+', line):
                details = '\n'.join([details, f"HCI Version: {match[1]}"])
            if match := re.match('LMP Version: (.*)  .+', line):
                details = '\n'.join([details, f"LMP Version: {match[1]}"])
            if match := re.match('Manufacturer: (.*)', line):
                details = '\n'.join([details, f"Manufacturer: {match[1]}"])
        return details

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
