import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from threading import Thread
from Backend_lib.Linux.agent import Agent


class AgentRunner:
    """
    A class to manage the lifecycle of a Bluetooth pairing agent using BlueZ D-Bus APIs.

    This class registers a custom Bluetooth agent with the BlueZ AgentManager and runs the D-Bus
    main loop in a separate background thread.
    """

    def __init__(self, capability="NoInputNoOutput", agent_path="/test/agent"):
        """
        Initializes the AgentRunner.

        Args:
            capability (str): The input/output capability of the agent. Defaults to "NoInputNoOutput".
                              Common values include: "DisplayOnly", "DisplayYesNo", "KeyboardOnly",
                              "NoInputNoOutput", "KeyboardDisplay".
            agent_path (str): The D-Bus object path where the agent will be registered.
                              Defaults to "/test/agent".
        returns: None
        """
        self.capability = capability
        self.agent_path = agent_path
        self.mainloop = None
        self.bus = None
        self.agent = None

    def start(self):
        """
        Starts the D-Bus main loop and registers the custom Bluetooth agent with BlueZ.

        This sets up the D-Bus connection, registers the agent with the AgentManager1 interface,
        and runs the GLib main loop in a background thread.

        args: None
        returns: None
        """
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        # Create and register your existing Agent
        self.agent = Agent(self.bus, self.agent_path)
        self.mainloop = GLib.MainLoop()

        # Register the agent with BlueZ
        manager = dbus.Interface(
            self.bus.get_object("org.bluez", "/org/bluez"),
            "org.bluez.AgentManager1"
        )
        manager.RegisterAgent(self.agent_path, self.capability)
        manager.RequestDefaultAgent(self.agent_path)
        print(f"[Agent] Registered with capability: {self.capability}")

        # Run the GLib main loop in a background thread
        thread = Thread(target=self.mainloop.run, daemon=True)
        thread.start()

    def stop(self):
        """
        Stops the D-Bus main loop if it is running.

        This effectively unregisters the agent and ends the background thread handling the loop.

        args: None
        returns: None
        """
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()
