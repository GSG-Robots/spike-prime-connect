# `spike-prime-connect`

This is a CLI tool that allows you to connect and communicate to your Spike Prime or Robot Inventor hub.

Some actions you can perform are:

- Uploading, moving and deleting projects
  ```bash
  spike-prime-connect upload <path/to/file.py> --slot <slotid>
  spike-prime-connect move <old_slotid> <new_slotid>
  spike-prime-connect wipe --slot <slot_id>
  spike-prime-connect wipe --all
  ```
- Starting and stopping projects
  ```bash
  spike-prime-connect start <slotid>
  spike-prime-connect stop
  ```
- Reading from the hubs stdout
  ```bash
  spike-prime-connect read
  ```
- Opening a REPL to execute code directly on the hub
  ```bash
  spike-prime-connect repl
  ```
- Retrieving information about the hub and its state
  ```bash
  spike-prime-connect get slots
  spike-prime-connect get storage
  spike-prime-connect get firmware
  spike-prime-connect get uuid
  spike-prime-connect get battery
  ```
- Rebooting and powering off
  ```bash
  spike-prime-connect reboot
  spike-prime-connect reboot --hard
  spike-prime-connect poweroff
  ```

> [!WARNING]
> You are using this program at your own risk, we don not provide warranty!  
> This project is neither frequently and extensively tested and might contain bugs causing harm to your PC's or hub's system nor do we provide or indicate that there would be future support.  
> (_This was inserted because of the EU Cyber Resilience Act_)

> [!NOTE]
> LEGO® Education SPIKE™, LEGO® MINDSTORMS® and LEGO® are trademarks of the LEGO Group of companies.
> This project is not in any way affiliated with or supported by LEGO.
