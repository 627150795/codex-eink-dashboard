# Codex E-Ink Monitor

[中文](README.md) | **English**

This is a small local tool that puts Codex Desktop status on an inexpensive Bluetooth e-ink display. It is for people who want to buy a cheap `SKD-CLOCK`-style 212×104 monochrome display and keep an always-visible view of Codex quota and task status on their desk, without keeping the Codex window open all the time.

![Codex e-ink monitor in real use](docs/images/codex-eink-real-device.jpg)

> Real-world view: the display sits next to a keyboard and shows the current Codex tasks, quota, and plan progress.

## What this project is for

When Codex is running in the background, its window may be covered by other work. This program reads Codex sessions, sidebar titles, unread markers, and quota information locally, renders a black-and-white frame for the e-ink panel, and sends it through the device's original BLE image protocol.

The display can show:

- the existing Codex sidebar title of the currently running task;
- task start, plan-step changes, completion, failure, and unread state;
- the exact remaining percentage of the primary quota and its reset date;
- up to eight status slots for running/completed/failed tasks, plus up to six task-text rows.

Visible events normally trigger a refresh after an approximately one-second coalescing window. Once a Bluetooth upload finishes, the service checks again for changes that arrived during the upload. The 30-second active-task and 60-second idle polling intervals are only fallbacks for missed file events or quota changes; normal task changes do not have to wait for those intervals.

This is not a replacement for Codex, a cloud service, or a general-purpose e-ink SDK. It only puts a quiet summary of your local Codex state on a desk display.

## Low-cost positioning

The goal is to make “buy a cheap e-ink display to watch Codex quota” genuinely practical. Based on the author's purchase experience, similar `SKD-CLOCK` devices on Pinduoduo can cost about **RMB 15 after coupons**. Promotions, stores, shipping, and hardware batches change, so treat that as a reference price rather than a promise.

On the low-cost end, this **may be one of the cheapest Codex quota monitor solutions currently available**. This describes the overall “software + inexpensive e-ink display” entry cost; it is not a permanent, exhaustive price ranking of every product or software project.

In the author's normal low-frequency-refresh use, one charge can last **more than two months**. Actual battery life depends on refresh frequency, Bluetooth advertising, temperature, battery capacity, and the device batch.

## Screen guide

The following works like a game manual for the display. The examples refer to `RUN 2`, `8.5`, `LEFT 35%`, and `● 2/5` in the photo above.

| Area | Display | Meaning |
| --- | --- | --- |
| Top left | `RUN 2` | `RUN` means one or more tasks are running. The `2` is the number of active tasks. |
| Top left | `WAIT 1` | A task is waiting for confirmation, permission, or the next input. The number is still the active-task count. |
| Top left | `DONE 0` | No task is currently running, but a recently completed task is still unread. |
| Top left | `ERR 0` | An unread task failed; open Codex to see the error details. |
| Top left | `LIMIT 0` | The quota has been exhausted or a usage limit has been reached. |
| Top left | `OFFLINE 0` | Codex status has not been read successfully for a while, so the display may be stale. |
| Top left | `IDLE 0` | No task is running and there is no unread completion/failure alert. |
| Top right | `8.5` | The next weekly quota reset date, in `month.day` format. In the photo it means August 5; it is not the last refresh time. |
| Top right | `API` | The display is using API-account mode; the ChatGPT primary-quota percentage is hidden in this mode. |
| Quota area | `LEFT 35%` + bar | 35% of the primary quota remains. The number is the exact integer percentage and the bar is its visual form. |
| Task area title | `TASKS` | The rows use existing Codex sidebar titles. The program does not invent a replacement name from an English request, directory, or thread ID. |
| Task-row prefix | `>` | The task is running. |
| Task-row prefix | `?` | The task is waiting. |
| Bottom status strip | `●` or `2/5` | A task is running. If a real `update_plan` exists for the turn, the display shows current step/total, such as `2/5`; otherwise it shows the dot glyph. |
| Bottom status strip | `✓` | The task completed, and Codex still marks it as unread. |
| Bottom status strip | `×` | The task failed, and Codex still marks it as unread. |

The bottom status strip has up to 8 positions arranged as **4 on the top row and 4 on the bottom row**. Completed and failed `✓`/`×` states are automatically cleared after two hours; reading the blue unread marker in Codex clears them earlier. The task-text area shows up to six rows and uses `...` for overflow.

Failed tasks are primarily indicated by the top-left `ERR` state and the bottom `×` glyph. In the current portrait layout, the `TASKS` text area lists running and waiting tasks.

## Supported hardware

The current implementation has been tested against an `SKD-CLOCK` device with these common characteristics:

- 212×104 monochrome e-ink panel;
- original DA14585 firmware (firmware 1.8 has been verified);
- BLE image transfer support;
- no need to flash firmware, add an ESP development board, or expose an HTTP/LAN service.

Different batches and other panel sizes may use different protocols. After connecting, the program checks the reported resolution and status packet again. A mismatch is rejected instead of writing an unsafe frame to the device.

## Installation and running

In Windows PowerShell, enter the project directory and create a virtual environment with Pillow, Bleak, Watchdog, and the other dependencies:

```powershell
.\install.ps1
Copy-Item .\config.example.json .\config.json
```

Fill in your display's Bluetooth address in `config.json` (or leave it empty so the program scans for a device with the `SKD-CLOCK` prefix), then run:

```powershell
.\start.ps1 preview --all --output previews
.\start.ps1 probe
.\start.ps1 once
.\start.ps1 run
```

- `preview`: generate PNG files without connecting to Bluetooth.
- `probe`: connect and read resolution, firmware, voltage, and other status; it does not write an image.
- `once`: upload one frame when the content changes; `--force` forces an upload.
- `run`: run the monitor continuously. File events trigger immediate refreshes; 30/60-second polling is the fallback.
- `stats`: summarize daily `uploaded`/`unchanged`/`retry` counts from `logs/dashboard.log`.

```powershell
.\start.ps1 stats
.\start.ps1 stats --day 2026-07-21
.\start.ps1 stats --day 2026-07-21 --hourly
.\start.ps1 stats --last-days 7
.\start.ps1 stats --json
```

The local deployment uses `config.json` in the project root. The public repository only contains the device-address-free `config.example.json`; copy it before configuring your own display. Landscape is the default layout. Set `orientation` to `landscape` to switch back from portrait without changing the protocol or reinstalling dependencies.

## Automatic startup

The Windows task `Codex E-Ink Dashboard` can be installed for the current user:

```powershell
.\install-task.ps1
```

Remove it with:

```powershell
.\uninstall-task.ps1
```

The background log is written to `logs\dashboard.log`. The task is single-instance, can restart up to three times after an unexpected exit, and records `service-start` / `service-exit` lifecycle events.

It is allowed to start on battery and does not stop merely because the power source changes. Besides the logon trigger, a lightweight once-per-minute watchdog trigger can recover an unexpectedly stopped process. It does not wake or restart the computer; sleep pauses it, and Windows catches up after wake.

## Refresh and power behavior

- **Content first**: the service renders from local sessions/quota plus cached resolution/voltage and computes a SHA-256 hash; an unchanged bitmap means **no scan and no Bluetooth connection**.
- A BLE connection is opened only when the bitmap changes (or `--force` is used): read status, re-render with hysteresis-quantized voltage, and write the image in the same connection.
- In portrait mode, the top-right field shows only the weekly quota reset date as `M.D`; API plans show `API`. Device voltage, `SYNC`, reset icons, and exact reset times are not shown there.
- The quota uses the exact integer percentage returned by the live endpoint; every 1% change may trigger a full-screen refresh.
- A changed frame sends 22 image packets of 129 bytes, followed by one `0x62` commit command.
- A disconnect or transient GATT error retransmits the complete frame from the beginning, with up to two retries by default; it does not attempt unreliable resume-from-offset behavior.

## Immediate updates

- The service watches Codex session files, the sidebar-title index, and unread-state files. A start, plan-step change, completion, failure, or unread-marker change causes a redraw after the one-second quiet window; every redraw also reads the latest quota instead of waiting for the next polling deadline.
- If the image hash is unchanged, the service does not scan, connect, or write over Bluetooth. Events that arrive during an upload are retained and checked immediately after the upload.
- 30-second active and 60-second idle polling remain as fallbacks for missed file events and quota changes without a local event.
- If one live quota read fails temporarily, the last successfully read live percentage is retained so the display does not jump back to an old value or show a misleading transition.
- Task names come only from existing Codex sidebar titles. If there is no existing title, the display says `未命名任务` in the Chinese layout rather than inventing a name from an English request, directory, or task ID.
- `state_5.sqlite` and `logs_2.sqlite` are read only for titles and active-thread information, not watched as event sources, so quota collection cannot trigger its own loop.

## Configuration

Copy `config.example.json` and pass the local file with the global `--config` option:

```powershell
.\start.ps1 --config .\config.json preview --all --output previews
```

Common options:

- `privacy_mode: "summary"`: show task titles and a one-line completion summary.
- `privacy_mode: "titles"`: show titles only, without completion summaries.
- `account_mode: "api"`: use only after confirming that the account is an API account; this skips ChatGPT quota reads and local quota fallback, and shows `API` in the portrait top-right field. The default `"auto"` keeps automatic detection.
- `resolution`: read it from the device by default; do not set it manually except for troubleshooting.
- `image_index`: original image slot, from 0 to 6; default 0.
- `orientation`: `landscape` keeps the original layout; `portrait_cw` is the current portrait orientation; `portrait_ccw` corrects the opposite physical rotation. Portrait mode currently supports only the 212×104 panel.

## Portrait layout

The portrait logical canvas is 104×212 and is rotated before upload to the device's required 212×104 image packet. It contains the task status, primary quota, running tasks, and recent alerts. The original top `SYNC` area now shows the weekly quota reset date as `M.D`, such as `7.21`; it prefers the `secondary` weekly window and falls back to the only available reset window when needed. API plans show `API`, hide the primary quota text and bar, and move the task area directly below the title bar. If Codex explicitly reports that ChatGPT quota authentication is unavailable, the account is detected as API. A confirmed API deployment can set `account_mode: "api"` to avoid falling back to a historical reset date after a transient read failure. Device voltage is not displayed.

The task area is followed by up to eight status slots in a 4×2 grid. The fixed order is running, unread completion, and failure. A running task shows `current step/total` only when a real `update_plan` exists for that turn; otherwise it shows the running glyph and never guesses progress. Completed and failed tasks must still be unread in Codex Desktop (blue marker) to appear. The running, check, and cross marks are reusable 7×7 monochrome pixel glyphs rather than Unicode font characters, so each refresh does not depend on font coverage. The task-text area shows at most six rows and uses `...` for overflow.

## Bluetooth notes

The device currently reports `allow_bluetooth=true` and normally keeps advertising. If it cannot be scanned later, press the device button once or wait for its advertising window. The program checks the resolution again after connecting; an invalid status packet, mismatched resolution, or insufficient MTU rejects the image write.

The program does not perform OTA updates, erase firmware, modify system settings, delete photos, or open an HTTP/LAN service. Codex content is read locally, and the logs do not record full prompts or replies.
