"""Host driver for the USB MIDI footswitch.

A port of the Rust ``footswitch`` crate (``driver/src/lib.rs``) and the parts of
``footswitch-core`` it uses (``core/src/protocol.rs``, ``core/src/config.rs``).

The device shows up as a USB MIDI port called "Footswitch". It sends its pedal messages on that
port, and the same port takes configuration as SysEx. No OS driver is needed.

.. code-block:: python

    from footswitch import Color, ControlChange, Footswitch, Mode

    with Footswitch.open() as fs:
        print(f"{fs.info().connected_pedals} pedals connected")

        # Pedal 0 (the module with the Pico): latching, green, sends CC 64 on channel 1.
        fs.set_mode(0, Mode.LATCH)
        fs.set_color(0, Color.GREEN)
        fs.set_message(0, ControlChange(channel=0, controller=64, on_value=127, off_value=0))
        fs.save()  # keep it after power-off

Pedal indices start at 0 (the module with the Pico) and MIDI channels are 0-15 (channel 1 is
0). Changes apply at once; call :meth:`Footswitch.save` to keep them in flash.

On Windows a MIDI port can only be open in one program at a time, so close the DAW (or disable
the port in it) while configuring.
"""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Callable, Union

import rtmidi

__all__ = [
    "PORT_NAME", "DEFAULT_TIMEOUT", "MAX_PEDALS", "PROTOCOL_VERSION",
    "Color", "Mode", "NoMessage", "Note", "ControlChange", "ProgramChange", "Message",
    "PedalConfig", "Settings", "Command", "Status", "Request", "Reply", "DeviceInfo",
    "PedalStates", "Done", "decode_response", "FootswitchError", "NotFound", "MidiError", "Timeout",
    "Rejected", "UnexpectedReply", "BadIndex", "InvalidConfig", "list_ports",
    "all_port_names", "Footswitch",
]

#: Substring of the USB product name that :meth:`Footswitch.open` looks for in port names.
PORT_NAME = "Footswitch"

#: How long to wait for a reply, in seconds. Saving to flash takes about 50 ms.
DEFAULT_TIMEOUT = 1.0

#: The most pedals (modules) the firmware scans.
MAX_PEDALS = 16

HEADER = bytes([0xF0, 0x7D, 0x46, 0x53])
SYSEX_END = 0xF7
PROTOCOL_VERSION = 1
_RESPONSE_FLAG = 0x40

_CLIENT_NAME = "footswitch-driver"


# ---- config types (core/src/config.rs) ----


class Color(IntEnum):
    """LED colour. The value is the 74HC595 bit pattern: bit 0 red, bit 1 green, bit 2 blue."""

    OFF = 0b000  #: The LED never lights.
    RED = 0b001
    GREEN = 0b010
    YELLOW = 0b011
    BLUE = 0b100
    MAGENTA = 0b101
    CYAN = 0b110
    WHITE = 0b111

    @property
    def label(self) -> str:
        """Lower-case name, e.g. "red"."""
        return self.name.lower()


class Mode(IntEnum):
    """How the pedal reacts to the (momentary) footswitch."""

    #: Active while held down: "on" message on press, "off" message on release.
    MOMENTARY = 0
    #: Each press toggles: "on" when it turns on, "off" when it turns off.
    LATCH = 1


def _b7(v: int) -> bool:
    return 0 <= v < 128


def _ch(v: int) -> bool:
    return 0 <= v < 16


@dataclass(frozen=True)
class NoMessage:
    """Send nothing. The LED still follows the pedal state."""

    def is_valid(self) -> bool:
        return True


@dataclass(frozen=True)
class Note:
    """Note On (velocity ``velocity``) when the pedal turns on, Note Off when it turns off."""

    channel: int
    note: int
    velocity: int

    def is_valid(self) -> bool:
        return _ch(self.channel) and _b7(self.note) and 1 <= self.velocity < 128


@dataclass(frozen=True)
class ControlChange:
    """Control Change with ``on_value`` when the pedal turns on, ``off_value`` when it turns off."""

    channel: int
    controller: int
    on_value: int
    off_value: int

    def is_valid(self) -> bool:
        return (
            _ch(self.channel) and _b7(self.controller)
            and _b7(self.on_value) and _b7(self.off_value)
        )


@dataclass(frozen=True)
class ProgramChange:
    """Program Change when the pedal turns on. Nothing when it turns off."""

    channel: int
    program: int

    def is_valid(self) -> bool:
        return _ch(self.channel) and _b7(self.program)


#: The MIDI message a pedal sends. Channels are 0-15 (MIDI channel 1 is 0).
Message = Union[NoMessage, Note, ControlChange, ProgramChange]


@dataclass(frozen=True)
class PedalConfig:
    """Everything about one pedal."""

    mode: Mode
    #: The LED colour while the pedal is on. The LED is off while the pedal is off.
    color: Color
    message: Message

    #: Encoded size in bytes. Every byte is 0-127, so it can go into a SysEx message as-is.
    ENCODED_LEN = 7

    @staticmethod
    def default_for(index: int) -> PedalConfig:
        """The factory default for pedal ``index``: momentary, red, and CC 102 + index on
        channel 1, value 127 on / 0 off."""
        return PedalConfig(Mode.MOMENTARY, Color.RED, ControlChange(0, 102 + index, 127, 0))

    def is_valid(self) -> bool:
        return self.message.is_valid()

    def encode(self) -> bytes:
        """Layout: ``[mode, color, kind, channel, a, b, c]``, where kind is 0 none, 1 note,
        2 CC, 3 program change, and a/b/c are note/velocity/0, controller/on/off or
        program/0/0."""
        m = self.message
        if isinstance(m, Note):
            fields = (1, m.channel, m.note, m.velocity, 0)
        elif isinstance(m, ControlChange):
            fields = (2, m.channel, m.controller, m.on_value, m.off_value)
        elif isinstance(m, ProgramChange):
            fields = (3, m.channel, m.program, 0, 0)
        else:
            fields = (0, 0, 0, 0, 0)
        return bytes(v & 0x7F for v in (int(self.mode), int(self.color), *fields))

    @staticmethod
    def decode(data: bytes) -> PedalConfig | None:
        """Decodes :meth:`encode`'s output. Returns ``None`` if anything is out of range."""
        if len(data) < PedalConfig.ENCODED_LEN:
            return None
        mode, color, kind, channel, a, b, c = data[: PedalConfig.ENCODED_LEN]
        if kind == 0:
            message: Message = NoMessage()
        elif kind == 1:
            message = Note(channel, a, b)
        elif kind == 2:
            message = ControlChange(channel, a, b, c)
        elif kind == 3:
            message = ProgramChange(channel, a)
        else:
            return None
        if mode not in (0, 1) or color >= 8:
            return None
        cfg = PedalConfig(Mode(mode), Color(color), message)
        return cfg if cfg.is_valid() else None


@dataclass(frozen=True)
class Settings:
    """Settings that apply to the whole device."""

    #: Read the footswitches the other way round. Use this if the switch's NO and NC pins turn
    #: out to be swapped, so the pedal reads as pressed while it is up.
    invert_switches: bool = False

    ENCODED_LEN = 1

    def encode(self) -> bytes:
        return bytes([int(self.invert_switches)])

    @staticmethod
    def decode(data: bytes) -> Settings | None:
        if not data or data[0] not in (0, 1):
            return None
        return Settings(invert_switches=data[0] == 1)


# ---- protocol (core/src/protocol.rs) ----
#
# Request (host -> device):  F0 7D 46 53 <command> <payload...> F7
# Response (device -> host): F0 7D 46 53 <command | 0x40> <status> <payload...> F7


class Command(IntEnum):
    GET_INFO = 0x01
    GET_PEDAL = 0x02
    SET_PEDAL = 0x03
    GET_SETTINGS = 0x04
    SET_SETTINGS = 0x05
    GET_STATE = 0x06
    SAVE = 0x07
    RESET_DEFAULTS = 0x08
    ENTER_BOOTLOADER = 0x09


class Status(IntEnum):
    """Result code in every response."""

    OK = 0
    UNKNOWN_COMMAND = 1
    #: Payload too short, too long or with out-of-range values.
    MALFORMED = 2
    #: Pedal index not below the device's maximum.
    BAD_INDEX = 3
    #: Writing the flash failed or read back wrong.
    FLASH_ERROR = 4


@dataclass(frozen=True)
class Request:
    """One request. ``index`` is for GET_PEDAL and SET_PEDAL, ``config`` for SET_PEDAL and
    ``settings`` for SET_SETTINGS."""

    command: Command
    index: int = 0
    config: PedalConfig | None = None
    settings: Settings | None = None

    def encode(self) -> bytes:
        """The complete SysEx message, F0 to F7."""
        out = bytearray(HEADER)
        out.append(int(self.command))
        if self.command == Command.GET_PEDAL:
            out.append(self.index & 0x7F)
        elif self.command == Command.SET_PEDAL:
            assert self.config is not None
            out.append(self.index & 0x7F)
            out += self.config.encode()
        elif self.command == Command.SET_SETTINGS:
            assert self.settings is not None
            out += self.settings.encode()
        out.append(SYSEX_END)
        return bytes(out)


@dataclass(frozen=True)
class DeviceInfo:
    protocol_version: int
    #: Major, minor, patch. Each 0-127.
    firmware_version: tuple[int, int, int]
    #: How many pedals the firmware can handle.
    max_pedals: int
    #: How many modules the last scan of the chain found.
    connected_pedals: int


@dataclass(frozen=True)
class PedalStates:
    """Live pedal state. Bit ``i`` is pedal ``i``."""

    connected: int
    #: Pedal is on: held down (momentary) or latched on (latch). Its LED is lit.
    active: int
    #: The footswitch is physically held down (after debouncing).
    pressed: int


@dataclass(frozen=True)
class Done:
    """Reply to a command that returns no data."""


@dataclass(frozen=True)
class Reply:
    """A decoded response: which command it answers, the status, and (if OK) the payload.

    ``response`` is a :class:`DeviceInfo`, an ``(index, PedalConfig)`` tuple, a
    :class:`Settings`, a :class:`PedalStates` or :class:`Done`, or ``None`` on error."""

    command: int
    status: Status
    response: object | None


def _u16_from_7bit(b: bytes) -> int:
    return b[0] | (b[1] << 7) | (b[2] << 14)


def decode_response(msg: bytes) -> Reply | None:
    """Decodes a complete SysEx response. Returns ``None`` if it isn't a well-formed response in
    this protocol."""
    msg = bytes(msg)
    if not msg.startswith(HEADER) or len(msg) < len(HEADER) + 3 or msg[-1] != SYSEX_END:
        return None
    body = msg[len(HEADER) : -1]
    if any(b >= 0x80 for b in body):
        return None
    cmd, status, p = body[0], body[1], body[2:]
    if not cmd & _RESPONSE_FLAG:
        return None
    command = cmd & ~_RESPONSE_FLAG
    try:
        status = Status(status)
    except ValueError:
        return None
    if status != Status.OK:
        return Reply(command, status, None) if not p else None

    resp: object
    if command == Command.GET_INFO and len(p) == 6:
        resp = DeviceInfo(p[0], (p[1], p[2], p[3]), p[4], p[5])
    elif command == Command.GET_PEDAL and len(p) == 1 + PedalConfig.ENCODED_LEN:
        cfg = PedalConfig.decode(p[1:])
        if cfg is None:
            return None
        resp = (p[0], cfg)
    elif command == Command.GET_SETTINGS and len(p) == Settings.ENCODED_LEN:
        s = Settings.decode(p)
        if s is None:
            return None
        resp = s
    elif command == Command.GET_STATE and len(p) == 7:
        resp = PedalStates(p[0], _u16_from_7bit(p[1:4]), _u16_from_7bit(p[4:7]))
    elif command in (
        Command.SET_PEDAL, Command.SET_SETTINGS, Command.SAVE,
        Command.RESET_DEFAULTS, Command.ENTER_BOOTLOADER,
    ) and not p:
        resp = Done()
    else:
        return None
    return Reply(command, status, resp)


# ---- errors ----


class FootswitchError(Exception):
    """Base class of every error this module raises."""


class NotFound(FootswitchError):
    def __init__(self, pattern: str):
        super().__init__(f"no MIDI port matching {pattern!r} found (is the footswitch plugged in?)")
        self.pattern = pattern


class MidiError(FootswitchError):
    """MIDI system error."""


class Timeout(FootswitchError):
    def __init__(self, command: Command):
        super().__init__(f"no reply from the device to {command.name}")
        self.command = command


class Rejected(FootswitchError):
    def __init__(self, command: Command, status: Status):
        super().__init__(f"the device rejected {command.name}: {status.name}")
        self.command = command
        self.status = status


class UnexpectedReply(FootswitchError):
    def __init__(self, command: Command):
        super().__init__(f"unexpected reply to {command.name}")
        self.command = command


class BadIndex(FootswitchError):
    def __init__(self, index: int):
        super().__init__(f"pedal index {index} out of range (max {MAX_PEDALS - 1})")
        self.index = index


class InvalidConfig(FootswitchError):
    def __init__(self, config: PedalConfig):
        super().__init__(f"invalid pedal config: {config!r}")
        self.config = config


# ---- the driver ----


def list_ports() -> list[str]:
    """Lists the MIDI input port names that contain :data:`PORT_NAME`."""
    return [n for n in all_port_names() if PORT_NAME in n]


def all_port_names() -> list[str]:
    """Lists every MIDI input port name, footswitch or not. Useful when the device's port has an
    unexpected name."""
    try:
        midi_in = rtmidi.MidiIn(name=_CLIENT_NAME)
    except rtmidi.RtMidiError as e:
        raise MidiError(str(e)) from e
    try:
        return midi_in.get_ports()
    finally:
        midi_in.delete()


def _check_index(index: int) -> int:
    if 0 <= index < MAX_PEDALS:
        return index
    raise BadIndex(index)


class Footswitch:
    """An open connection to a footswitch. Use :meth:`open` or :meth:`open_matching`, and
    :meth:`close` it when done (or use it as a context manager)."""

    def __init__(self, midi_in, midi_out, port_name: str):
        self._in = midi_in
        self._out = midi_out
        self._rx: queue.Queue[bytes] = queue.Queue()
        self._port_name = port_name
        #: Reply timeout in seconds.
        self.timeout = DEFAULT_TIMEOUT
        self._in.set_callback(self._on_message)

    @classmethod
    def open(cls) -> Footswitch:
        """Opens the first port whose name contains :data:`PORT_NAME`."""
        return cls.open_matching(PORT_NAME)

    @classmethod
    def open_matching(cls, pattern: str) -> Footswitch:
        """Opens the first port whose name contains ``pattern``. Use this to pick one of several
        footswitches, or a port with an unexpected name."""
        try:
            midi_in = rtmidi.MidiIn(name=_CLIENT_NAME)
            midi_out = rtmidi.MidiOut(name=_CLIENT_NAME)
        except rtmidi.RtMidiError as e:
            raise MidiError(str(e)) from e
        try:
            midi_in.ignore_types(sysex=False, timing=True, active_sense=True)  # we need SysEx
            in_idx = next((i for i, n in enumerate(midi_in.get_ports()) if pattern in n), None)
            out_names = midi_out.get_ports()
            out_idx = next((i for i, n in enumerate(out_names) if pattern in n), None)
            if in_idx is None or out_idx is None:
                raise NotFound(pattern)
            midi_in.open_port(in_idx, "footswitch-in")
            midi_out.open_port(out_idx, "footswitch-out")
        except rtmidi.RtMidiError as e:
            midi_in.delete()
            midi_out.delete()
            raise MidiError(str(e)) from e
        except NotFound:
            midi_in.delete()
            midi_out.delete()
            raise
        return cls(midi_in, midi_out, out_names[out_idx])

    def _on_message(self, event, _data=None) -> None:
        msg, _delta = event
        if msg and msg[0] == 0xF0:
            self._rx.put(bytes(msg))

    def close(self) -> None:
        """Closes the ports."""
        if self._in is not None:
            self._in.cancel_callback()
            self._in.close_port()
            self._out.close_port()
            self._in.delete()
            self._out.delete()
            self._in = self._out = None

    def __enter__(self) -> Footswitch:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def port_name(self) -> str:
        """The name of the MIDI output port in use."""
        return self._port_name

    def info(self) -> DeviceInfo:
        """Firmware version, and how many pedals are connected."""
        r = self.request(Request(Command.GET_INFO))
        if not isinstance(r, DeviceInfo):
            raise UnexpectedReply(Command.GET_INFO)
        return r

    def pedal(self, index: int) -> PedalConfig:
        """The config of pedal ``index``."""
        index = _check_index(index)
        r = self.request(Request(Command.GET_PEDAL, index=index))
        if not (isinstance(r, tuple) and r[0] == index):
            raise UnexpectedReply(Command.GET_PEDAL)
        return r[1]

    def pedals(self) -> list[PedalConfig]:
        """The configs of the connected pedals, in order."""
        return [self.pedal(i) for i in range(self.info().connected_pedals)]

    def set_pedal(self, index: int, config: PedalConfig) -> None:
        """Replaces pedal ``index``'s config. If the pedal is on, the device first sends its old
        "off" message and turns it off."""
        index = _check_index(index)
        if not config.is_valid():
            raise InvalidConfig(config)
        self.request(Request(Command.SET_PEDAL, index=index, config=config))

    def set_mode(self, index: int, mode: Mode) -> None:
        """Changes one pedal's mode, keeping its other settings."""
        self.update_pedal(index, lambda p: replace(p, mode=mode))

    def set_color(self, index: int, color: Color) -> None:
        """Changes one pedal's LED colour (shown while the pedal is on)."""
        self.update_pedal(index, lambda p: replace(p, color=color))

    def set_message(self, index: int, message: Message) -> None:
        """Changes the MIDI message one pedal sends."""
        self.update_pedal(index, lambda p: replace(p, message=message))

    def update_pedal(self, index: int, f: Callable[[PedalConfig], PedalConfig]) -> None:
        """Reads pedal ``index``, passes it to ``f`` and writes back what ``f`` returns."""
        self.set_pedal(index, f(self.pedal(index)))

    def set_all_colors(self, color: Color) -> None:
        """Sets the LED colour of every pedal."""
        for i in range(MAX_PEDALS):
            self.set_color(i, color)

    def settings(self) -> Settings:
        r = self.request(Request(Command.GET_SETTINGS))
        if not isinstance(r, Settings):
            raise UnexpectedReply(Command.GET_SETTINGS)
        return r

    def set_settings(self, settings: Settings) -> None:
        self.request(Request(Command.SET_SETTINGS, settings=settings))

    def states(self) -> PedalStates:
        """Which pedals are on and which switches are held down right now."""
        r = self.request(Request(Command.GET_STATE))
        if not isinstance(r, PedalStates):
            raise UnexpectedReply(Command.GET_STATE)
        return r

    def save(self) -> None:
        """Writes the current config to flash, so it survives a power cycle."""
        self.request(Request(Command.SAVE))

    def reset_defaults(self) -> None:
        """Restores the factory defaults (every pedal momentary, red, CC 102 + index on channel
        1). Only in RAM: call :meth:`save` to make it permanent."""
        self.request(Request(Command.RESET_DEFAULTS))

    def enter_bootloader(self) -> None:
        """Reboots the Pico into its USB bootloader (the RPI-RP2 drive) for a firmware update,
        without pressing BOOTSEL. Closes the connection."""
        try:
            self.request(Request(Command.ENTER_BOOTLOADER))
        except Timeout:
            pass  # The reply can be lost when USB goes down; that is fine here.
        finally:
            self.close()

    def request(self, req: Request) -> object:
        """Sends one request and waits for its reply. Returns the reply's payload (see
        :class:`Reply`)."""
        # Drop stale replies (e.g. from an earlier request that timed out).
        while True:
            try:
                self._rx.get_nowait()
            except queue.Empty:
                break
        try:
            self._out.send_message(req.encode())
        except rtmidi.RtMidiError as e:
            raise MidiError(f"sending to the device failed: {e}") from e

        deadline = time.monotonic() + self.timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise Timeout(req.command)
            try:
                msg = self._rx.get(timeout=left)
            except queue.Empty:
                raise Timeout(req.command) from None
            reply = decode_response(msg)
            if reply is None or reply.command != req.command:
                continue
            if reply.status != Status.OK:
                raise Rejected(req.command, reply.status)
            return reply.response
