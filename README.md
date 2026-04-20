# OBS Controller App

Windows-first background utility that listens for a PlayStation 4 **SHARE** button on a connected gamepad, drives **OBS Studio** exclusively through **obs-websocket** (no hotkeys), and automatically **moves and renames** finished recordings into managed folders. A small **top-right toast** confirms actions; an optional **system tray** menu opens logs, reconnects OBS, or exits.

## What it does

- **Double-tap SHARE** (within a configurable window, default 300 ms): toggles OBS recording — start if idle, stop if active. After a clean stop, the finished file is detected only once it is **stable on disk**, then moved to your **final recordings** folder and renamed as `Recordings N.ext` using the next free index.
- **Single-tap SHARE** (one press, then quiet until the tap window expires): deletes the **last finished** recording file the app tracked (never a file OBS is still writing).
- **Notifications**: minimal top-right popups for success, info, and errors.
- **Logging**: rotating log file under the `logs` folder next to `settings.json`.

## Requirements

- Windows 10 or 11.
- **Python 3.10+** (3.12–3.14 recommended). Very old Python may lack compatible wheels for some dependencies.
- **OBS Studio** with **WebSocket server** enabled (v5).
- A **PS4 / DualShock 4** (or compatible) controller seen by Windows as a joystick.
- Python packages listed in `requirements.txt`.

### pygame vs pygame-ce

This repo depends on **`pygame-ce`**, which is API-compatible with `pygame` but ships current wheels (including for newer CPython). If you prefer stock `pygame`, replace the dependency in `requirements.txt` **after** confirming `pip install pygame` succeeds on your Python version.

## Install dependencies

From the repository root (`obs-controller`):

```powershell
cd c:\Developer\Personal\Programs\obs-controller
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Enable OBS WebSocket

1. Open **OBS Studio** → **Tools** → **WebSocket Server Settings**.
2. Enable the server, set the **port** (default **4455**), and set a **password** if you want authentication.
3. Put the same **host**, **port**, and **password** into `obs_controller_app\settings.json`.

The app uses the official WebSocket v5 protocol via `obsws-python` — no AutoHotkey and no simulated keyboard shortcuts.

## Configure `settings.json`

The file lives next to the package as `obs_controller_app\settings.json` (or next to your frozen `.exe` when packaged). Important keys:

| Key | Purpose |
| --- | --- |
| `obs_host` / `obs_port` / `obs_password` | WebSocket endpoint. |
| `obs_recordings_output_folder` | Fallback folder to scan if OBS directory queries fail — should match where OBS writes recordings. |
| `obs_clips_output_folder` | Reserved for future replay-buffer workflows; created if used later. |
| `final_recordings_folder` | Where finished recordings are moved and renamed. |
| `final_clips_folder` | Reserved for clip finalization. |
| `share_double_tap_window_ms` | Max gap between two SHARE presses to count as a double-tap (single-tap waits this long). |
| `notification_duration_ms` | Toast visibility time. |
| `enable_system_tray` | Tray menu on/off. |
| `debug_logging` | Verbose logs when `true`. |
| `share_button_index` | Zero-based joystick button index for SHARE (often `8` on DS4 over many Windows drivers — change if needed). |
| `joystick_device_index` | Which `pygame` joystick slot to open (usually `0`). |
| `file_stable_*` / `file_finalize_timeout_sec` | How long to wait for encoders to finish flushing files before move/delete. |

Adjust paths to real folders on your PC. Use forward slashes or escaped backslashes in JSON.

## Run the app

```powershell
cd c:\Developer\Personal\Programs\obs-controller
python -m obs_controller_app.main
```

Keep OBS running with WebSocket enabled. Connect the controller before or after launch; if the device index is wrong, edit `joystick_device_index` or `share_button_index`.

## SHARE controls (summary)

| Gesture | When OBS recording is off | When OBS recording is on |
| --- | --- | --- |
| **Double-tap SHARE** | Start recording | Stop, finalize file, move/rename into `final_recordings_folder`, remember path for single-tap delete |
| **Single-tap SHARE** | Deletes last **finished** recording if one is tracked | Same (does not stop an active encode) |

Single-tap is **delayed** until the double-tap window expires so a quick double-tap never triggers delete.

## How files are organized

- While recording, OBS writes to its configured recording directory (queried live via `GetRecordDirectory` when possible).
- After stop, the app waits until **recording is inactive**, then picks the newest matching video file whose timestamp plausibly belongs to the session, and waits until the **file size is stable** before moving it.
- Destination names look like **`Recordings 1.mp4`**, **`Recordings 2.mkv`**, etc. The next index is **one greater than the highest existing number** in the destination folder — gaps are allowed (e.g. existing `1`, `2`, `5` → next `6`).
- **Clips** / replay buffer automation is intentionally stubbed (`move_and_rename_clip`, clip folders) for a later iteration without changing the overall layout.

## Logs and tray

- Logs directory: `obs_controller_app\logs\` (next to `settings.json` in development).
- Tray entries: **Open logs folder**, **Reconnect OBS**, **Exit**.

## Package into an EXE (PyInstaller)

1. Install PyInstaller in the same environment:

   ```powershell
   python -m pip install pyinstaller
   ```

2. Build (run from repo root):

   ```powershell
   cd c:\Developer\Personal\Programs\obs-controller
   pyinstaller --noconsole --name OBSController `
     --add-data "obs_controller_app\settings.json;obs_controller_app" `
     obs_controller_app\main.py
   ```

   PyInstaller’s `--add-data` syntax uses `SRC;DEST` on Windows. Ensure `settings.json` sits beside the frozen app if you prefer editing it outside the bundle, or ship defaults and let users replace the file next to the EXE (see `config.py` which resolves paths from the executable directory when `sys.frozen` is set).

3. First launch after packaging: confirm Windows Defender / SmartScreen trust as needed.

## Extending later

- **Replay buffer / clips**: wire OBS save events or requests into `FileOrganizer.move_and_rename_clip` and `final_clips_folder`.
- **Alternate controller backends**: keep the same high-level semantics (`on_share_pressed`) and replace `Ps4InputListener`.

## License

This sample project is provided as-is for local use; add a license file if you redistribute.
