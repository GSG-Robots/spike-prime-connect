import base64
import enum
import json
import math
import random
import string
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal, Optional

import serial
import serial.serialutil
import serial.tools.list_ports_windows as serial_tool_search
from dataclasses_json import DataClassJsonMixin

letters = string.ascii_letters + string.digits + "_"


def get_arrow(done, todo, blocksize):
    blocks = math.ceil(todo / blocksize)
    done_blocks = math.ceil(done / blocksize)
    done_perquartercent = done_blocks / blocks * 25

    def h(x):
        return 9 if done_perquartercent > x else 6

    def l(x):
        return 4 if done_perquartercent > x else 0

    img = (
        (l, l, h, l, l),
        (l, l, h, l, l),
        (h, h, h, h, h),
        (l, h, h, h, l),
        (l, l, h, l, l),
    )
    result = tuple(
        tuple(pixel(y * 5 + x) for x, pixel in enumerate(row))
        for y, row in enumerate(img)
    )
    return ":".join(["".join([str(pixel) for pixel in row]) for row in result])


def random_id(len=4):
    return "".join(random.choice(letters) for _ in range(len))


class Gesture(enum.Enum):
    TAPPED = 0
    DOUBLETAPPED = 1
    SHAKEN = 2
    FALLING = 3

    def __json__(self):
        return [self.value, self.name]


class Orientation(enum.Enum):
    BATTERY_DOWN = 0
    SPEAKER_DOWN = 1
    LEFT_DOWN = 2
    SCREEN_DOWN = 3
    PORT_DOWN = 4
    RIGHT_DOWN = 5

    def __json__(self):
        return [self.value, self.name]


@dataclass
class JsonMessage(DataClassJsonMixin):
    m: Optional[int | str] = None
    "The message type. Not there if response."
    i: Optional[str] = None
    "A four letter ID to make the massage unique and answerable"
    p: Optional[Any] = None
    "Additional information. Depending on message type"
    r: Optional[Any] = None
    "Result. Only if message is a response. Depending on message type"
    e: Optional[Any] = None
    "Error. Only if message is a response. Depending on message type"


@dataclass
class JsonFirmwareInfoRuntime(DataClassJsonMixin):
    version: list[int]


@dataclass
class JsonFirmwareInfoFirmware(DataClassJsonMixin):
    checksum: str
    version: list[int]


@dataclass
class JsonFirmwareInfo(DataClassJsonMixin):
    runtime: JsonFirmwareInfoRuntime
    capabilities: list[str]
    firmware: JsonFirmwareInfoFirmware
    usb_pid: str
    variant: str
    device_uuid: str


@dataclass
class JsonStorageInfoSlot(DataClassJsonMixin):
    id: int
    size: int
    "size in kb"
    name: str
    "Project name, set on upload"
    project_id: str
    "Project ID, set on upload"
    modified: int
    "Modified unix timestamp"
    created: int
    "Created unix timestamp"
    type: Literal["python"] | Literal["scratch"]
    "Projects with python have the normal python API, while projects with scratch have a more advanced API and are async"


@dataclass
class JsonStorageInfoStorage(DataClassJsonMixin):
    available: int
    "Available storage in given .unit"
    total: int
    "Total storage in given .unit"
    pct: float
    "percentage free"
    unit: str
    "unit for storage, seems to be kb always"
    free: int
    "Free storage in given .unit"


@dataclass
class JsonStorageInfo(DataClassJsonMixin):
    storage: JsonStorageInfoStorage
    slots: dict[str, JsonStorageInfoSlot]
    "Dict of str-ints and slots. str-int: '9' instead of 9. why? idk"


class Message[T]:
    there: bool
    id: str
    result: Optional[T]
    error: Optional[str]

    def __init__(
        self, device: "Device", id: int, response_parser: DataClassJsonMixin = None
    ):
        self.device = device
        self.id = id

        self._response_parser = response_parser

        self.device._sent_messages[self.id] = self

        self.there = False
        self.result = None
        self.error = None

    def wait_for_response(self) -> T:
        while not self.there:
            if not self.device.active:
                raise ConnectionAbortedError("Device disconnected.")
        if self.error:
            error = self.error
            try:
                error = base64.b64decode(error)
            except:
                pass
            try:
                error = json.loads(error)
            except:
                pass
            raise ConnectionError(error)
        return (
            self._response_parser(self.result) if self._response_parser else self.result
        )


class LogType(enum.Enum):
    USER_PROGRAM_PRINT = enum.auto()
    USER_PROGRAM_ERROR = enum.auto()
    RUNTIME_ERROR = enum.auto()
    PRINT = enum.auto()


class LogEntry:
    def __init__(self, type: LogType, entry: str):
        self.type = type
        self.entry = entry

    def __str__(self):
        return f"{self.type}: {self.entry}"

    def __repr__(self):
        return f"<LogEntry {str(self)}>"


class Device:
    def __init__(self, port: str):
        self.port = port
        self._ser = serial.Serial(port, 115200)
        self._sent_messages: dict[str, Message] = {}
        self.logs: deque[LogEntry] = deque()
        self._current_image = None
        self._buffer = bytearray()
        self._ran_first = False
        self._repl_prompt = False
        self._repl_paste = False
        self._repl_in = []
        self._repl_out = []
        self.active = True

        self._tickloop_thread = threading.Thread(target=self.tickloop, daemon=True)
        self._tickloop_thread.start()

        self.running_program: bool = False
        self.orientation: Optional[Orientation] = None
        self.last_gesture: Optional[Gesture] = None

    def ensure_connected(self):
        if not self.active:
            raise ConnectionError("Device not connected anymore.")

    def send_message(self, name, params=None, response_parser=None) -> Message:
        self.ensure_connected()
        while not self._ran_first:
            ...
        id = random_id()
        message = Message(self, id, response_parser)
        msg = {"m": name, "p": params, "i": id}
        msg_string = json.dumps(msg)
        self._ser.write(msg_string.encode("utf-8"))
        self._ser.write(b"\x0d")
        return message

    def handle_message(self, rmsg: bytes):
        if not rmsg:
            return
        self._ran_first = True
        if rmsg.startswith(b"\n<<< "):
            self._repl_out.append(rmsg.decode("utf-8")[5:])
        elif rmsg.startswith(b"\n>>> ") or rmsg.startswith(b"\n=== "):
            self._repl_in.append(rmsg.decode("utf-8")[5:])
        try:
            msg = JsonMessage.from_json(rmsg.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            try:
                self.logs.append(LogEntry(LogType.PRINT, rmsg.decode("utf-8")))
            except UnicodeDecodeError:
                self.logs.append(LogEntry(LogType.PRINT, "?"))
            return
        mid = msg.i
        message = msg.m

        if mid and mid in self._sent_messages:
            pending_message = self._sent_messages.pop(mid)
            pending_message.result = msg.r
            pending_message.error = msg.e
            pending_message.there = True
        else:
            if message == "userProgram.print":
                self.logs.append(
                    LogEntry(LogType.USER_PROGRAM_PRINT, msg.p.get("value"))
                )
            elif message == "user_program_error":
                try:
                    decoded_line_1 = base64.b64decode(msg.p[3].encode("utf-8")).decode(
                        "utf-8"
                    )
                except (UnicodeDecodeError, UnicodeEncodeError):
                    decoded_line_1 = msg.p[3]
                try:
                    decoded_line_2 = base64.b64decode(msg.p[4].encode("utf-8")).decode(
                        "utf-8"
                    )
                except (UnicodeDecodeError, UnicodeEncodeError):
                    decoded_line_2 = msg.p[4]
                self.logs.append(
                    LogEntry(
                        LogType.USER_PROGRAM_ERROR,
                        decoded_line_1 + "\n" + decoded_line_2,
                    )
                )
            elif message == "runtime_error":
                self.logs.append(
                    LogEntry(
                        LogType.RUNTIME_ERROR,
                        base64.b64decode(msg.p[3].encode("utf-8")).decode("utf-8"),
                    )
                )
            elif message == 3:
                ...  # Button press button = p[0], time = p[1]. if time == 0, button down, else up.
            elif message == 4:
                self.last_gesture = Gesture(msg.p)
            elif message == 12:
                self.running_program = msg.p[1]
            elif message == 14:
                self.orientation = Orientation(msg.p)
            elif message in (0, 1, 2):
                ...  # print("?", msg)
            else:
                ...  # print("?", msg)

    def tick(self):
        self._buffer += self._ser.read_all()
        if self._buffer[-7:].strip(b"\r\n") == b">>> ":
            self._repl_prompt = True
            self._repl_paste = False
        elif self._buffer[-7:].strip(b"\r\n") == b"=== ":
            self._repl_prompt = True
            self._repl_paste = True
        else:
            self._repl_prompt = False
            self._repl_paste = False
        pos = self._buffer.find(b"\x0d")
        if pos != -1:
            part = self._buffer[:pos]
            self.handle_message(part)
            self._buffer = self._buffer[pos + 1 :]

    def tickloop(self):
        while self.active:
            try:
                self.tick()
            except serial.serialutil.SerialException:
                self.active = False

    def display_set_pixel(self, x, y, brightness=9) -> Message[None]:
        self.ensure_connected()
        return self.send_message(
            "scratch.display_set_pixel", {"x": x, "y": y, "brightness": brightness}
        )

    def display_clear(self) -> Message[None]:
        self.ensure_connected()
        return self.send_message("scratch.display_clear")

    def _wait_for_prompt(self, timeout=3):
        start = time.time()
        while (time.time() - start) < timeout:
            if self._repl_prompt:
                return True
        return False

    def exec_in_repl(self, cmd: str):
        self._ser.write(cmd.encode("utf-8") + b"\r\n")
        self._repl_prompt = False
        time.sleep(0.5)
        if not self._wait_for_prompt():
            raise TimeoutError("hub takes too long to respond")

    def start_repl(self):
        self.ensure_connected()
        for _ in range(3):
            self._ser.write(b"\x03")
            self._ser.write(b"\x02")
            time.sleep(0.5)
            if self._wait_for_prompt():
                return
            time.sleep(2)
        raise TimeoutError("hub takes too long to respond")

    def soft_reboot(self):
        self._ser.write(b"\x04")
        time.sleep(0.5)

    def eval_in_repl(self, code: str):
        pos = len(self._repl_out)
        self.exec_in_repl("print('<<<', %s)" % code)
        while not len(self._repl_out) - pos:
            ...
        return self._repl_out[-1]

    def wipe_slot(self, slot: int) -> Message[None]:
        return self.send_message("remove_project", {"slotid": slot})

    def move_slot(self, from_slot: int, to_slot: int) -> Message[None]:
        return self.send_message(
            "move_project", {"old_slotid": from_slot, "new_slotid": to_slot}
        )

    def display_image(self, image: str) -> Message[None]:
        self.ensure_connected()
        return self.send_message("scratch.display_image", {"image": image})

    def display_image_for(self, image: str, duration_ms: int) -> Message[None]:
        self.ensure_connected()
        return self.send_message(
            "scratch.display_image_for", {"image": image, "duration": duration_ms}
        )

    def display_text(self, text: str | int) -> Message[None]:
        self.ensure_connected()
        return self.send_message("scratch.display_text", {"text": text})

    def upload_file(
        self,
        data: bytes,
        to_slot: int,
        name=None,
        mode="python",
        callback=None,
        filename=None,
    ):
        self.ensure_connected()

        now = int(time.time() * 1000)
        size = len(data)

        # self.display_image("00000:00000:90909:00000:00000").wait_for_response()
        # self.update_display(get_arrow(0), refresh=True)

        start = self.send_message(
            "start_write_program",
            {
                "slotid": to_slot,
                "size": size,
                "filename": filename,
                "meta": {
                    "created": now,
                    "modified": now,
                    "name": base64.b64encode(
                        (name or random_id(10)).encode("utf-8")
                    ).decode("utf-8"),
                    "type": mode,
                    "project_id": random_id(12),
                },
            },
        ).wait_for_response()

        bs = start["blocksize"]
        tid = start["transferid"]
        transferred = 0

        # self.display_image(get_arrow(transferred, size, bs)).wait_for_response()

        b = data[:bs]
        data = data[bs:]
        while b:
            self.send_message(
                "write_package",
                {"data": str(base64.b64encode(b), "utf-8"), "transferid": tid},
            ).wait_for_response()
            transferred += len(b)
            callback(transferred, size, bs)
            # self.display_image(get_arrow(transferred, size, bs)).wait_for_response()
            b = data[:bs]
            data = data[bs:]
        # time.sleep(0.1)

    def run_program(self, slot: int) -> Message[None]:
        self.ensure_connected()
        return self.send_message("program_execute", {"slotid": slot})

    def terminate_program(self) -> Message[None]:
        self.ensure_connected()
        return self.send_message("program_terminate")

    def get_storage_information(self) -> Message[JsonStorageInfo]:
        self.ensure_connected()
        return self.send_message(
            "get_storage_status", response_parser=JsonStorageInfo.from_dict
        )

    def get_firmware_info(self) -> Message[JsonFirmwareInfo]:
        self.ensure_connected()
        return self.send_message(
            "get_hub_info", response_parser=JsonFirmwareInfo.from_dict
        )

    def __del__(self):
        self.active = False
        self._tickloop_thread.join()
        self._ser.close()


class DeviceManager:
    def __init__(self):
        self.connected_devices: dict[str, Device] = {}

        self.active = True
        self._tickloop_thread = threading.Thread(target=self.tickloop, daemon=True)
        self._tickloop_thread.start()

    def new_device(self, port: str):
        new_device = Device(port)
        self.connected_devices[port] = new_device

    def discover_comports(self):
        for port in serial_tool_search.comports():
            if port.name not in self.connected_devices:
                self.new_device(port.name)

    def remove_inactive_devices(self):
        self.connected_devices = {
            port: device
            for port, device in self.connected_devices.items()
            if device.active
        }

    def tick(self):
        self.remove_inactive_devices()
        self.discover_comports()

    def tickloop(self):
        while True:
            self.tick()
            time.sleep(1)

    def __del__(self):
        self.active = False
        self._tickloop_thread.join()
