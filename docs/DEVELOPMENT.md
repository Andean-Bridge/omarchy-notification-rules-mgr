# Development and verification

## Repository layout

| File | Role |
| --- | --- |
| `manifest.json` | Omarchy plugin ID, kind, bar entry point, and default right-section placement. |
| `Panel.qml` | Theme-aware bar icon, popup, controls, and JSON snapshot rendering. |
| `backend.py` | Rule validation, systemd override, Omarchy IPC, journal queries, and schedule reconciliation. |
| `tests/test_backend.py` | Isolated tests for exact matching, durations, profile scope, quiet hours, rollback, bounded journal and file reads, and recent crash recognition. |

The plugin uses Python's standard library only. Minimum Python version is 3.10 because the helper uses union type annotations.

## Run checks

```bash
omarchy plugin validate .
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
/usr/lib/qt6/bin/qmlformat -n Panel.qml >/dev/null
```

`qmlformat -n` parses QML without rewriting it. The Omarchy validator checks the manifest and relative entry points. The unit tests mock service commands and write only to temporary directories; they do not change the user's notification settings.

For a read-only backend snapshot on an Omarchy desktop:

```bash
python3 backend.py read | python3 -m json.tool
```

The other CLI actions are live controls: `add`, `remove`, `profile`, `dnd`, `quiet`, `dedupe`, `capture`, `replay`, `dismiss`, and `clear`. `tick` also reconciles state and may change DND or the crash watcher. Do not run mutation actions as tests against a real desktop.

Journal queries always request at most 251 entries and limit captured output to 4 MiB and 15 seconds. Keep these caps when changing the crash inbox or digest; digest counts must be marked as lower bounds whenever a cap is reached.

Snapshot inputs have their own limits: the notification view keeps 64 candidate files, reads at most 64 KiB from each, and returns 20 clipped cards; saved JSON files are limited to 256 KiB; service override files and control-command output are limited to 64 KiB. Do not replace these with eager directory lists, full-file `read_text()`, or unlimited subprocess capture.

## Try a local checkout

Omarchy's normal installation clones a published Git repository:

```bash
omarchy plugin add https://github.com/Andean-Bridge/omarchy-notification-rules-mgr.git --enable
```

For an unpublished development copy, place the plugin files under `~/.config/omarchy/plugins/andean-bridge.notification-rules-mgr/`, then run:

```bash
omarchy-shell shell rescanPlugins
omarchy plugin enable andean-bridge.notification-rules-mgr
omarchy-shell shell summon andean-bridge.notification-rules-mgr
```

Use the README's removal steps when finished. If QML changes do not fully appear after a hot reload, run `omarchy restart shell` and summon the panel again. The live bar geometry can be inspected with `omarchy-shell shell debugBarGeometry`.

The helper normally lives inside the installed plugin directory. `OMARCHY_NOTIFICATION_RULES_BACKEND` can point to another absolute `backend.py` path for local UI development; set it in the shell environment before launching `omarchy-shell`.

## When changing the rule model

Keep these contracts in sync:

1. `rule_expiry` and `mutate` in `backend.py` validate duration keys and profile scope.
2. Duration buttons in `Panel.qml` send those keys as CLI arguments.
3. The systemd override contains only the effective ignore pattern and nondefault repeat window; every process name must be escaped as a literal before joining the expression.
4. `snapshot` must return the fields consumed by the panel. Errors use `{ "ok": false, "error": "…" }` so the UI can show them without discarding its last good snapshot.
5. Documentation must distinguish the coredump journal from Omarchy's recent notification history.

A release should pass the checks above and be exercised in the live bar before publishing. The marketplace validates the exact published commit, so submit the repository only after pushing the intended version.
