import ast
import base64
import datetime
import msvcrt
import re
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path

import ast_comments as ast
import colorama
import compyner.__main__
import compyner.engine
import serial.tools.list_ports_windows
import tqdm

from . import spikeapi
from .spike_prime_compyne import spike_prime_compyne


def greet():
    print(colorama.Fore.BLUE + compyner.__main__.ASCII_LOGO + colorama.Style.RESET_ALL)
    print(f"{'for Spike Prime':>48}")
    print()


def get_device():
    print(colorama.Fore.GREEN + "> Searching for devices..." + colorama.Style.RESET_ALL)
    devices = serial.tools.list_ports_windows.comports()
    if len(devices) == 0:
        print(
            colorama.Fore.RED
            + colorama.Style.BRIGHT
            + "Error: No devices found"
            + colorama.Style.RESET_ALL
        )
        sys.exit(1)
    if len(devices) == 1:
        device_choice = devices[0]
    else:
        for index, device in enumerate(devices):
            print(f"{index+1:>2}. {device.device}")
        device_choice = devices[int(input("Device: ")) - 1]

    print(colorama.Fore.GREEN + "> Connecting..." + colorama.Fore.RESET)
    return spikeapi.Device(device_choice.device)


def show_stdout(device: spikeapi.Device, error_replace_location: Path | None):
    if error_replace_location:
        lineno_map = compyner.engine.get_lineno_map(
            ast.parse(error_replace_location.read_text("utf-8"))
        )

        def error_replacer(match: re.Match[str]):
            match_str = match.group(0)
            if not match_str.startswith(f'"{error_replace_location}"'):
                return match_str
            mapped = lineno_map.get(int(match_str.rsplit("line ", 1)[1][:-1]))
            if mapped is None:
                return match_str
            return f'(comPYned) "{mapped}"'

    print(colorama.Fore.CYAN + ">> Press any key to exit" + colorama.Fore.RESET)
    while True:
        if not device.active:
            print(colorama.Fore.RED + "> Device disconnected" + colorama.Fore.RESET)
            break
        if device.logs:
            log = device.logs.popleft()
            if log.type == spikeapi.LogType.PRINT:
                print(colorama.Fore.LIGHTBLACK_EX + log.entry + colorama.Fore.RESET)
            if log.type == spikeapi.LogType.USER_PROGRAM_PRINT:
                print(log.entry)
            elif log.type == spikeapi.LogType.USER_PROGRAM_ERROR:
                if error_replace_location:
                    log.entry = re.sub(r'".*", line \d*,', error_replacer, log.entry)
                print(colorama.Fore.RED + log.entry + colorama.Fore.RESET)
            elif log.type == spikeapi.LogType.RUNTIME_ERROR:
                print(colorama.Fore.YELLOW + log.entry + colorama.Fore.RESET)

        if msvcrt.kbhit():
            print(
                colorama.Fore.LIGHTGREEN_EX
                + "> Got input. Exiting..."
                + colorama.Fore.RESET
            )
            break


def wipe_slots(device: spikeapi.Device, slots: list[int]):
    print(colorama.Fore.GREEN + "> Wiping slots..." + colorama.Fore.RESET)
    existing_slots = device.get_storage_information().wait_for_response().slots.keys()
    for slot in slots:
        if str(slot) in existing_slots:
            device.wipe_slot(slot).wait_for_response()

def move_slots(device: spikeapi.Device, from_slot:int, to_slot: int):
    print(colorama.Fore.GREEN + "> Moving slot..." + colorama.Fore.RESET)
    device.move_slot(from_slot, to_slot).wait_for_response()


def start(
    device: spikeapi.Device,
    slot: int = 0,
    file: Path | None = None,
    hide_output: bool = False,
    wait: bool = True
):
    print(colorama.Fore.GREEN + "> Running..." + colorama.Fore.RESET)
    device.run_program(slot)

    if wait:
        while not device.running_program:
            pass

    if not hide_output:
        show_stdout(device, file)


def stop(
    device: spikeapi.Device,
    wait: bool = True
):
    print(colorama.Fore.GREEN + "> Terminating..." + colorama.Fore.RESET)
    device.terminate_program()

    if wait:
        while device.running_program:
            pass
        


def upload(
    device: spikeapi.Device,
    input: Path,
    slot: int = 0,
    debug: bool = False,
    autostart: bool = True,
    hide_output: bool = False,
):
    # Step 1: ComPYning
    print(colorama.Fore.GREEN + "> ComPYning..." + colorama.Fore.RESET)
    comPYned: str = spike_prime_compyne(input, slot=slot, debug_build=debug)
    input.with_suffix(".cpyd.py").write_text(comPYned, "utf-8")

    # Step 2: Compiling
    print(colorama.Fore.GREEN + "> Compiling..." + colorama.Fore.RESET, end="")
    proc = subprocess.run(
        ["mpy-cross-v5", input.with_suffix(".cpyd.py").absolute()],
        check=False,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        print(
            colorama.Style.BRIGHT
            + colorama.Fore.RED
            + "\nFailed:"
            + colorama.Style.NORMAL
        )
        print(proc.stderr.decode("utf-8") + colorama.Style.RESET_ALL)
        return
    mpy = input.with_suffix(".cpyd.mpy").absolute().read_bytes()
    input.with_suffix(".cpyd.mpy").absolute().unlink()
    print(colorama.Fore.GREEN + " done" + colorama.Fore.RESET)

    # Step 3: Uploading
    print(colorama.Fore.GREEN + "> Uploading..." + colorama.Fore.RESET)
    progress_bar = tqdm.tqdm(total=len(mpy), unit="B", unit_scale=True)

    def callback(done, total, bs):
        progress_bar.update(bs)

    device.upload_file(
        mpy,
        slot,
        input.name,
        filename="__init__.mpy",
        callback=callback,
    )

    progress_bar.close()

    if autostart:
        start(device, slot, input.with_suffix(".cpyd.py"), hide_output)


def show_slots(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    data = device.get_storage_information().wait_for_response()
    print("Slots:")
    for slot_id, slot in data.slots.items():
        print(f"    {slot_id:>2}:")
        print(f"        ID          : {slot.id}")
        print(f"        Name        : {base64.b64decode(slot.name).decode("utf-8")}")
        print(f"        Project ID  : {slot.project_id}")
        print(f"        Type        : {slot.type}")
        print(f"        Size        : {slot.size} kb")
        print(
            f"        Created At  : {datetime.datetime.fromtimestamp(slot.created / 1000).strftime("%d.%m.%Y %H:%M:%S")}"
        )
        print(
            f"        Modified At : {datetime.datetime.fromtimestamp(slot.modified / 1000).strftime("%d.%m.%Y %H:%M:%S")}"
        )
    if not data.slots:
        print("    No slots.")
    print()


def show_storage(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    data = device.get_storage_information().wait_for_response()
    print("Storage:")
    print(f"    Availible : {data.storage.available:>8} {data.storage.unit}")
    print(f"    Free      : {data.storage.free:>8} {data.storage.unit}")
    print(f"    Total     : {data.storage.total:>8} {data.storage.unit}")
    print(f"    Used      : {data.storage.pct:>8} %")
    print()


def show_firmware(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    data = device.get_firmware_info().wait_for_response()
    print("Firmware:")
    print(f"    Checksum         : {data.firmware.checksum}")
    print(f"    Firmware Version : {".".join(map(str, data.firmware.version))}")
    print(f"    Runtime Version  : {".".join(map(str, data.runtime.version))}")
    print(f"    Capabilities     : {", ".join(data.capabilities)}")
    print(f"    Variant          : {data.variant}")
    print(f"    USB PID          : {data.usb_pid}")
    print()


def show_uuid(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    data = device.get_firmware_info().wait_for_response()
    print(f"Device UUID: {data.device_uuid}")
    
def show_battery(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    device.start_repl()
    device.exec_in_repl("import hub")
    charger_detect = device.eval_in_repl("hub.battery.charger_detect()")
    voltage = device.eval_in_repl("hub.battery.voltage()")
    current = device.eval_in_repl("hub.battery.current()")
    capacity_left = device.eval_in_repl("hub.battery.capacity_left()")
    temperature = device.eval_in_repl("hub.battery.temperature()")
    print("Battery:")
    print(f"    Capacity Left : {capacity_left} %")
    print(f"    Charging      : {charger_detect}")
    print(f"    Voltage       : {voltage} mV")
    print(f"    Current       : {current} ?")
    print(f"    Temperature   : {temperature} °C")
    print()
    print(colorama.Fore.YELLOW + ">> Performing soft reboot." + colorama.Fore.RESET)
    device.soft_reboot()

def show_repl(device: spikeapi.Device):
    device.start_repl()
    device.logs.clear()
    print(colorama.Fore.LIGHTBLUE_EX + ">> Press ^E to enter paste mode; enter ':exit' to exit" + colorama.Fore.RESET)
    try:
        while True:
            cmd = input(colorama.Fore.LIGHTBLACK_EX + (">>> " if not device._repl_paste else "=== ") + colorama.Fore.WHITE)
            if cmd == ":exit":
                return
            device.exec_in_repl(cmd)
            while device.logs:
                entry = device.logs.popleft().entry[1:]
                if entry.startswith(">>>") or entry.startswith("==="):
                    continue
                print(colorama.Fore.WHITE + entry + colorama.Fore.RESET)
    finally:
        print()
        print(colorama.Fore.YELLOW + ">> Performing soft reboot." + colorama.Fore.RESET)
        device.soft_reboot()

def main() -> None:
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="action")
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument(
        "input",
        action="store",
        type=compyner.__main__.file_path_exists,
    )
    upload_parser.add_argument(
        "--slot",
        "-s",
        required=False,
        action="store",
        type=int,
        default=0,
    )
    upload_parser.add_argument("--debug", action="store_true")
    upload_parser.add_argument("--start", action="store_true")
    upload_parser.add_argument(
        "--read",
        action="store_true",
        help="show program output",
    )
    read_parser = subparsers.add_parser("read")
    read_parser.add_argument(
        "--file",
        action="store",
        type=compyner.__main__.file_path_exists,
        required=False,
        default=None,
        help="path to a compyned file. Will be used to replace error locations",
    )
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("slot", action="store", type=int)
    start_parser.add_argument(
        "--read",
        action="store_true",
        help="dont show program output",
    )
    start_parser.add_argument(
        "--file",
        action="store",
        type=compyner.__main__.file_path_exists,
        required=False,
        default=None,
        help="path to a compyned file. Will be used to replace error locations",
    )
    start_parser.add_argument(
        "--wait",
        action="store_true",
        help="wait until program is started",
    )
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument(
        "--wait",
        action="store_true",
        help="wait until program is stopped",
    )
    subparsers.add_parser("poweroff")
    reboot_parser = subparsers.add_parser("reboot")
    reboot_parser.add_argument(
        "--hard",
        action="store_true",
        help="fully reboot",
    )
    subparsers.add_parser("repl")
    wipe_parser = subparsers.add_parser("wipe")
    opt_group = wipe_parser.add_mutually_exclusive_group(required=True)
    opt_group.add_argument("slot", action="store", nargs="*", type=int)
    opt_group.add_argument("--all", action="store_true")
    move_parser = subparsers.add_parser("move")
    move_parser.add_argument("from_slot", action="store", type=int)
    move_parser.add_argument("to_slot", action="store", type=int)
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("detail", choices=["storage", "slots", "firmware", "uuid", "battery"])
    args = parser.parse_args()

    try:
        if args.action == "upload":
            device = get_device()
            upload(
                device,
                args.input,
                args.slot,
                args.debug,
                args.start,
                not args.read,
            )
        elif args.action == "start":
            device = get_device()
            start(device, args.slot, args.file, not args.read, args.wait)
        elif args.action == "stop":
            device = get_device()
            stop(device, args.wait)
        elif args.action == "read":
            device = get_device()
            show_stdout(device, args.file)
        elif args.action == "wipe":
            device = get_device()
            wipe_slots(device, range(16) if args.all else args.slot)
        elif args.action == "move":
            device = get_device()
            move_slots(device, args.from_slot, args.to_slot)
        elif args.action == "get":
            device = get_device()
            if args.detail == "storage":
                show_storage(device)
            elif args.detail == "slots":
                show_slots(device)
            elif args.detail == "uuid":
                show_uuid(device)
            elif args.detail == "battery":
                show_battery(device)
            else:
                show_firmware(device)
        elif args.action == "poweroff":
            device = get_device()
            device.start_repl()
            device.exec_in_repl("import hub")
            device.exec_in_repl("hub.power_off(fast=True)")
        elif args.action == "reboot":
            device = get_device()
            device.start_repl()
            if args.hard:
                device.exec_in_repl("import hub")
                device.exec_in_repl("hub.power_off(restart=True)")
            else:
                device.soft_reboot()
        elif args.action == "repl":
            device = get_device()
            show_repl(device)
        else:
            parser.error("Invalid action")
    except ConnectionError as e:
        print("Lost connection", e)


if __name__ == "__main__":
    main()
