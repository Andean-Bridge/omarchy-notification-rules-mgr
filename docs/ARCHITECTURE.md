# How Notification Rules works

Notification Rules is a `bar-widget` plugin with a Quickshell UI (`Panel.qml`) and a small Python helper (`backend.py`). The helper uses Omarchy's current, public local controls. The plugin does not replace `org.freedesktop.Notifications` or copy Omarchy's notification service.

## Crash notification path

```text
systemd-coredump journal
        │
        ▼
omarchy-crash-watch.service
  ├─ executable basename matches OMARCHY_CRASH_IGNORE → no toast
  └─ no match → omarchy-notification-send → Omarchy notification service
```

The crash watcher reads `OMARCHY_CRASH_IGNORE` and `OMARCHY_CRASH_DEDUPE_SECONDS` when it starts. The helper compiles active process rules into one anchored Bash extended regular expression, places it in a plugin-owned **user systemd drop-in**, reloads the user manager, and restarts the watcher. Names are escaped as regex literals and systemd quoted. If another drop-in defines `OMARCHY_CRASH_IGNORE`, a new rule is rejected with an error instead of silently changing the effective configuration.

The matcher sees the executable **basename**, as Omarchy's watcher does. `MSBuild` does not match `dotnet`; two paths ending in `MSBuild` do match the same rule. Suppression happens before a toast exists. The system journal still records the coredump, so the crash inbox can show it, but Omarchy's notification history does not acquire a corresponding toast entry.

## Rules, profiles, and schedules

The panel sends a CLI action to `backend.py` through Quickshell's `Process` API. The helper loads JSON configuration, validates the action, computes the effective policy, writes the managed override when it changes, calls Omarchy's DND IPC when appropriate, and returns a JSON snapshot for rendering.

A rule records the process, action (`silence`), profile scope, creation time, expiry time, and whether it ends with the Debugging session. Creating a new rule for the same process and scope replaces its duration. Leaving Debugging removes session rules. Expired rules are pruned by the widget's one-minute timer and at the next reconciliation after shell startup.

Quiet hours use local 24-hour clock times. At the start, the plugin stores the prior DND state, turns on DND, and applies an all-crash ignore while the schedule is active. At the end it restores the prior DND state unless profile or manual DND control has taken precedence. If enabled, the digest queries coredumps recorded during that quiet window and sends one summary through `omarchy-notification-send`. The query asks for the latest 251 entries in the window, keeps at most 250, selects only fields needed by the UI, and reads at most 4 MiB for 15 seconds. A capped digest reports its crash count as a lower bound. The bar widget must be running for an on-time transition; an interrupted shell reconciles when it next loads.

Profile defaults are intentionally simple: Normal and Debugging leave DND off, Focus enables DND, and Presenting enables DND plus all-crash muting. Per-process rules can apply to all profiles or a single one.

## Activity sources

- The crash inbox reads at most the latest 250 `systemd-coredump` journal entries and keeps only entries with the current user's UID. Its subprocess output has the same 4 MiB and 15-second caps as the digest. It groups those entries by executable basename and evaluates each against the plugin's current policy.
- Recent notifications come from Omarchy's existing popup and short history JSON files. The helper scans directory entries lazily, retains only the 64 newest candidate paths in a heap, and reads at most 64 KiB from each selected file. It trims app, summary, and body text before returning at most 20 cards. Oversized and malformed files are skipped. A card is eligible for a crash mute when its app is `omarchy-action` and its summary begins with `Process crashed: `.
- The panel can call Omarchy's `showHistory`, `dismissAll`, and `clear` IPC methods. These operations have Omarchy's native semantics; `clear` clears archived recent history, while `dismissAll` clears visible toasts.

No local activity data is transmitted by this plugin. Installation and updates use GitHub only through Omarchy's normal `plugin add` and `plugin update` commands.

## Safety and failure behavior

The helper executes subprocesses with argument arrays, without shell interpolation, and caps non-journal command output at 64 KiB. Saved settings and state reads have a 256 KiB cap; service override reads have a 64 KiB cap. Oversized or malformed settings return an error, and an override too large to inspect is treated as a conflict. It creates JSON files with mode `0600` and writes the managed systemd override atomically. If a user-manager reload or watcher restart fails, it restores the prior override and reports an error. It does not edit Omarchy's installed files.

The watcher uses `journalctl -f -n 0`; restarting it creates a small interval in which a crash may not become a toast. The coredump remains in the journal. Removing the plugin folder alone leaves its managed override active, so the README includes explicit removal steps.

## Why normal notifications have no exact mute

Omarchy's current plugin-facing API exposes global DND and history controls, but no hook that accepts or rejects an individual notification before the service displays it. An ordinary app alert cannot be muted by title or sender from this bar widget. DND is global and can be bypassed by Omarchy action or critical notifications. The interface therefore offers exact mute buttons only for recognized crash alerts and labels the digest as crash-only.
