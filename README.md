# Notification Rules for Omarchy

A theme-aware bar panel for taming repetitive crash notifications while keeping useful alerts visible. It uses Omarchy's existing crash watcher, notification controls, and local activity data. It does not replace or clone Omarchy's notification service.

## The development use case

A build or debugging session can produce the same **“Process crashed: MSBuild”** toast over and over. Muting the sender `omarchy-action` would also hide unrelated Omarchy alerts. Notification Rules lets you mute the **`MSBuild` executable** for 1 hour, 8 hours, 7 days, or forever. Other crash alerts continue, and the MSBuild coredumps remain searchable in the crash inbox.

The same workflow works for other noisy process crashes during development, such as `dotnet`, test runners, or an application under active debugging. A rule matches the executable **basename**, so two programs with the same basename at different paths share one rule.

## Features

| Feature | What it does |
| --- | --- |
| Exact crash mute | Suppresses Omarchy's toast for a named crashed executable through the existing `OMARCHY_CRASH_IGNORE` control. |
| Quick durations | Offers **1h, 8h, 7d, and Forever** in Home, the crash inbox, and recent crash notification cards. Tapping another duration replaces that process's rule. |
| More rule choices | The Rules tab also offers **Until tomorrow** (09:00 local time) and **Debug session**, plus all-profile or current-profile scope. |
| Profiles | Switches among Normal, Focus, Presenting, and Debugging. Rules can be tied to one profile. |
| Crash inbox | Groups and searches recent coredumps by executable; muted crashes remain visible here even when no toast was sent. |
| Recent notifications | Searches Omarchy's short recent list. A `Process crashed: …` card from `omarchy-action` offers the four mute durations. |
| Quiet hours | Enables DND and pauses crash toasts on a daily local-time schedule. An optional digest summarizes crashes when quiet hours end. |
| Direct controls | Toggle DND or all crash capture, adjust the crash repeat window, replay recent notifications, dismiss visible toasts, and clear recent history. |

### Profile defaults

| Profile | DND | Crash alerts |
| --- | --- | --- |
| Normal | Off | On, except matching rules |
| Focus | On | On, except matching rules |
| Presenting | On | Paused |
| Debugging | Off | On, except matching rules; supports session mutes |

Omarchy crash notifications intentionally bypass DND, so Focus does not silence them by itself. Use a process rule or Presenting when you want those alerts quiet.

## Requirements

- Omarchy Quattro with `omarchy-shell` plugins and `omarchy-crash-watch.service`; tested on **Omarchy 4.0.4-1**.
- Python 3.10 or newer, `journalctl`, and user `systemctl`. These are standard on the tested Omarchy installation; there are **no pip packages** to install.
- A running bar widget for timely rule expiry, quiet-hour transitions, and digests. When the shell starts again, the plugin reconciles saved state.

The plugin runs as your user. It reads the local coredump journal and Omarchy's recent-notification files. It does not send activity to a remote service.

## Install and open

```bash
omarchy plugin add https://github.com/Andean-Bridge/omarchy-notification-rules-mgr.git --enable
```

The plugin defaults to the **right** bar section. Click its bell icon to open the panel. You can also summon it from a terminal or keybinding:

```bash
omarchy-shell shell summon andean-bridge.notification-rules-mgr
```

The popup stays anchored to its bar icon. Move the icon with Omarchy's bar drag-and-drop or `omarchy bar move`; the popup follows it. It is not a free-floating window.

If the bell is missing after an update, verify that the plugin is enabled and reload the shell:

```bash
omarchy plugin list
omarchy restart shell
```

Installing and enabling the plugin does not add an ignore rule or change DND. Choosing a control in the panel applies that setting.

## Mute MSBuild in three steps

1. Open **Notification Rules** from the bell icon.
2. In **Home**, choose `1h`, `8h`, `7d`, or `Forever`, enter `MSBuild`, and select **Mute now**. You can also find `MSBuild` under **Activity → Crash inbox** and select a duration there.
3. Open **Rules** to see the exact process name, profile scope, and expiry. Select **Remove** to allow its toasts again.

The **Activity → Recent notifications** view offers the same four buttons on recognized Omarchy crash alerts. Other app notifications are shown for reference; this plugin cannot make an exact per-alert mute rule for them with Omarchy's current plugin API.

## Quiet hours and digests

In **Settings**, enter 24-hour local times such as `22:00` and `08:00`, then enable Quiet hours. The schedule turns on DND and temporarily ignores all crash alerts. It restores the prior DND state when the window ends, unless a selected profile or manual DND setting now controls that state.

The optional digest counts **crashes only**. It is sent at the end of quiet hours when the bar widget is running, or after the shell resumes and reconciles an elapsed quiet window. Critical and `omarchy-action` notifications can bypass Omarchy's DND, so quiet hours are not a guarantee that every kind of alert disappears.

## Where data lives

| Path | Purpose |
| --- | --- |
| `~/.config/omarchy/notification-rules-mgr.json` | Profiles, rules, durations, repeat window, and quiet-hour preferences. |
| `~/.local/state/omarchy/notification-rules-mgr.json` | Quiet-hour transition state and the latest panel status. |
| `~/.config/systemd/user/omarchy-crash-watch.service.d/50-omarchy-notification-rules-mgr.conf` | Plugin-managed crash ignore pattern and repeat window. |
| `~/.local/state/omarchy/notifications/` | Omarchy's own recent notification files; read by the panel. |
| systemd coredump journal | Recent crash inbox and digest source; read by the panel. |

The systemd override is written atomically. Omarchy's watcher is restarted when the effective ignore list or repeat window changes. The plugin refuses to write an ignore rule if another unit override also sets `OMARCHY_CRASH_IGNORE`, so it does not silently replace that rule.

See [How it works](docs/ARCHITECTURE.md) for the data flow and implementation boundaries.

## Limits

- Rules match **crashed executable names**, not every notification's app, title, or body. Normal and critical notification filtering would need a hook in Omarchy's notification service.
- A muted crash is retained in the **system journal**, not Omarchy's toast history, because the watcher never sends that toast. The recent-notification list does not label items as shown or silenced.
- Omarchy currently keeps only ten archived recent notifications. The crash inbox reads the latest 250 coredump records.
- The digest summarizes crashes, not all notifications.
- Rebuilding the crash watcher's environment briefly restarts it. A crash in that gap remains journaled but might not show a toast.
- “Discard” is not offered. The plugin can stop a crash toast, but it cannot prevent systemd from recording the coredump.

## Remove

Removing the plugin does **not** automatically remove its systemd override. To restore normal crash alerts, remove that managed file and reload the user service:

```bash
omarchy plugin remove andean-bridge.notification-rules-mgr
rm -f ~/.config/systemd/user/omarchy-crash-watch.service.d/50-omarchy-notification-rules-mgr.conf
systemctl --user daemon-reload
systemctl --user try-restart omarchy-crash-watch.service
```

You may also delete the plugin's saved settings and transition state:

```bash
rm -f ~/.config/omarchy/notification-rules-mgr.json ~/.local/state/omarchy/notification-rules-mgr.json
```

## Develop and verify

```bash
omarchy plugin validate .
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
/usr/lib/qt6/bin/qmlformat -n Panel.qml >/dev/null
```

For a local development copy in another folder, set `OMARCHY_NOTIFICATION_RULES_BACKEND` to the absolute path of `backend.py` before starting `omarchy-shell`. See [Development](docs/DEVELOPMENT.md) for the CLI contract and checks.

## License

[MIT](LICENSE). Copyright 2026 Andean Bridge.
