import ast
from argparse import ArgumentParser
import base64
import datetime
from pathlib import Path
import ast_comments as ast
import re
import sys
import compyner.engine
import serial.tools.list_ports_windows
import tqdm
import subprocess
import colorama
import compyner.__main__
from .spike_prime_compyne import spike_prime_compyne
import msvcrt
from . import spikeapi


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


def clean_slots(device: spikeapi.Device, slots: list[int]):
    print(colorama.Fore.GREEN + "> Wiping slots..." + colorama.Fore.RESET)
    existing_slots = device.get_storage_information().wait_for_response().slots.keys()
    for slot in slots:
        if str(slot) in existing_slots:
            device.wipe_slot(slot).wait_for_response()


def run(
    device: spikeapi.Device,
    slot: int = 0,
    file: Path | None = None,
    hide_output: bool = False,
):
    print(colorama.Fore.GREEN + "> Running..." + colorama.Fore.RESET)
    device.run_program(slot)

    while not device.running_program:
        pass

    if not hide_output:
        show_stdout(device, file)


def upload(
    device: spikeapi.Device,
    input: Path,
    slot: int = 0,
    debug: bool = False,
    autorun: bool = True,
    hide_output: bool = False,
):
    # Step 1: ComPYning
    print(colorama.Fore.GREEN + "> ComPYning..." + colorama.Fore.RESET)
    comPYned: str = spike_prime_compyne(input, slot=slot, debug_build=debug)
    input.with_suffix(".cpyd.py").write_text(comPYned, "utf-8")

    # Step 2: Compiling
    print(colorama.Fore.GREEN + "> Compiling...", end="")
    subprocess.run(
        ["mpy-cross", "--bytecode", "5", input.with_suffix(".cpyd.py")], check=False
    )
    mpy = input.with_suffix(".cpyd.mpy").read_bytes()
    input.with_suffix(".cpyd.mpy").unlink()
    print(" done" + colorama.Fore.RESET)

    # Step 3: Uploading
    print(colorama.Fore.GREEN + "> Uploading..." + colorama.Fore.RESET)
    progress_bar = tqdm.tqdm(total=len(mpy), unit="B", unit_scale=True)

    def callback(done, total, bs):
        progress_bar.update(bs)

    device.upload_file(
        mpy,
        slot,
        sys.argv[1],
        filename="__init__.mpy",
        callback=callback,
    )

    progress_bar.close()

    if autorun:
        run(device, slot, input.with_suffix(".cpyd.py"), hide_output)


def show_slots(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    data = device.get_storage_information().wait_for_response()
    print("Slots:")
    for slot_id, slot in data.slots.items():
        print(f"    {slot_id:>2}:")
        print(f"        ID          : {slot.id}")
        print(f"        Name        : {slot.name}")
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


def show_storage(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    data = device.get_storage_information().wait_for_response()
    print("Storage:")
    print(f"    Availible : {data.storage.available:>8} {data.storage.unit}")
    print(f"    Free      : {data.storage.free:>8} {data.storage.unit}")
    print(f"    Total     : {data.storage.total:>8} {data.storage.unit}")
    print(f"    Used      : {data.storage.pct:>8} %")


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


def show_uuid(device: spikeapi.Device):
    print(colorama.Fore.GREEN + "> Loading data..." + colorama.Fore.RESET)
    data = device.get_firmware_info().wait_for_response()
    print(f"Device UUID: {data.device_uuid}")


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
    upload_parser.add_argument("--run", action="store_true")
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
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("slot", action="store", type=int)
    run_parser.add_argument(
        "--read",
        action="store_true",
        help="dont show program output",
    )
    run_parser.add_argument(
        "--file",
        action="store",
        type=compyner.__main__.file_path_exists,
        required=False,
        default=None,
        help="path to a compyned file. Will be used to replace error locations",
    )
    clean_parser = subparsers.add_parser("clean")
    opt_group = clean_parser.add_mutually_exclusive_group(required=True)
    opt_group.add_argument("slot", action="store", nargs="*", type=int)
    opt_group.add_argument("--all", action="store_true")
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("detail", choices=["storage", "slots", "firmware", "uuid"])
    args = parser.parse_args()

    try:

        if args.action == "upload":
            device = get_device()
            upload(
                device,
                args.input,
                args.slot,
                args.debug,
                args.run,
                not args.read,
            )
        elif args.action == "run":
            device = get_device()
            run(device, args.slot, args.file, not args.read)
        elif args.action == "read":
            device = get_device()
            show_stdout(device, args.file)
        elif args.action == "clean":
            device = get_device()
            clean_slots(device, range(16) if args.all else args.slot)
        elif args.action == "get":
            device = get_device()
            if args.detail == "storage":
                show_storage(device)
            elif args.detail == "slots":
                show_slots(device)
            elif args.detail == "uuid":
                show_uuid(device)
            else:
                show_firmware(device)
        else:
            parser.error("Invalid action")
    except ConnectionError as e:
        print("Lost connection", e)


if __name__ == "__main__":
    main()
