import ast
from argparse import ArgumentParser
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


ASCII_LOGO = r"""
                     ____ __   __               
   ___ ___  _ __ ___ |  _ \ \ / / __   ___ _ __ 
  / __/ _ \| '_ ` _ \| |_) \ V / '_ \ / _ \ '__|
 | (_| (_) | | | | | |  __/ | || | | |  __/ |   
  \___\___/|_| |_| |_|_|    |_||_| |_|\___|_|   
"""


def main() -> None:
    print()
    print(colorama.Fore.BLUE + compyner.__main__.ASCII_LOGO + colorama.Style.RESET_ALL)
    print(f"{'for Spike Prime':>48}")
    print()

    parser = ArgumentParser()
    parser.add_argument(
        "input",
        action="store",
        type=compyner.__main__.file_path_exists,
    )
    parser.add_argument(
        "--slot",
        "-s",
        required=False,
        action="store",
        type=int,
        default=0,
    )

    parser.add_argument("--debug", action="store_true")
    
    args = parser.parse_args()

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
    device = spikeapi.Device(device_choice.device)

    # Step 1: ComPYning
    print(colorama.Fore.GREEN + "> ComPYning..." + colorama.Fore.RESET)
    comPYned: str = spike_prime_compyne(args.input, slot=args.slot, debug_build=args.debug)
    args.input.with_suffix(".cpyd.py").write_text(comPYned, "utf-8")

    # Step 2: Compiling
    print(colorama.Fore.GREEN + "> Compiling...", end="")
    proc = subprocess.run(["mpy-cross-v5", args.input.with_suffix(".cpyd.py")])
    mpy = args.input.with_suffix(".cpyd.mpy").read_bytes()
    # file.with_suffix(".cpyd.mpy").unlink()
    print(" done" + colorama.Fore.RESET)

    # Step 3: Uploading
    print(colorama.Fore.GREEN + "> Uploading..." + colorama.Fore.RESET)
    progress_bar = tqdm.tqdm(total=len(mpy), unit="B", unit_scale=True)

    def callback(done, total, bs):
        progress_bar.update(bs)

    device.upload_file(
        mpy,
        args.slot,
        sys.argv[1],
        filename="__init__.mpy",
        callback=callback,
    )

    progress_bar.close()

    # Step 4: Running
    print(colorama.Fore.GREEN + "> Running..." + colorama.Fore.RESET)
    device.run_program(args.slot)

    while not device.running_program:
        pass

    print(colorama.Fore.CYAN + ">> Press any key to exit" + colorama.Fore.RESET)

    # Step 5: Monitoring

    error_replace_location = args.input.with_suffix(".cpyd.py")
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


if __name__ == "__main__":
    main()
