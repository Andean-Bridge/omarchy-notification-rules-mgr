import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("notification_rules_backend", Path(__file__).resolve().parents[1] / "backend.py")
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


def completed(argv, returncode=0, stderr=""):
    return subprocess.CompletedProcess(argv, returncode, "", stderr)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 24, 15, 0, tzinfo=dt.timezone.utc)
        self.config = backend.default_config()

    def test_exact_process_pattern_escapes_regex_characters(self):
        backend.mutate(self.config, "add", ["MS.Build[1]", "silence", "forever", "All"], self.now)
        pattern = backend.effective_pattern(self.config, self.now)
        self.assertEqual(pattern, r"^(MS\.Build\[1\])$")
        self.assertIsNotNone(__import__("re").search(pattern, "MS.Build[1]"))
        self.assertIsNone(__import__("re").search(pattern, "MSxBuild1"))

    def test_profile_rules_and_debug_session_expiry(self):
        backend.mutate(self.config, "profile", ["Debugging"], self.now)
        backend.mutate(self.config, "add", ["MSBuild", "silence", "session", "Debugging"], self.now)
        self.assertEqual(backend.effective_pattern(self.config, self.now), "^(MSBuild)$")
        backend.mutate(self.config, "profile", ["Normal"], self.now)
        self.assertEqual(self.config["rules"], [])
        self.assertEqual(backend.effective_pattern(self.config, self.now), "")

    def test_hour_expiry_and_overnight_quiet_hours(self):
        backend.mutate(self.config, "add", ["MSBuild", "silence", "hour", "All"], self.now)
        self.assertEqual(backend.effective_pattern(self.config, self.now + dt.timedelta(minutes=59)), "^(MSBuild)$")
        self.assertEqual(backend.effective_pattern(self.config, self.now + dt.timedelta(hours=1)), "")
        backend.mutate(self.config, "quiet", ["on", "22:00", "08:00", "on"], self.now)
        self.assertTrue(backend.quiet_active(self.config, self.now.replace(hour=23)))
        self.assertTrue(backend.quiet_active(self.config, self.now.replace(hour=7)))
        self.assertFalse(backend.quiet_active(self.config, self.now.replace(hour=9)))
        self.assertEqual(backend.effective_pattern(self.config, self.now.replace(hour=23)), ".*")

    def test_requested_mute_durations(self):
        self.assertEqual(backend.rule_expiry("eight_hours", self.now)[0], int((self.now + dt.timedelta(hours=8)).timestamp()))
        self.assertEqual(backend.rule_expiry("seven_days", self.now)[0], int((self.now + dt.timedelta(days=7)).timestamp()))
        self.assertEqual(backend.rule_expiry("forever", self.now), (None, False))

    def test_invalid_rule_and_malformed_config_are_rejected(self):
        with self.assertRaises(ValueError):
            backend.mutate(self.config, "add", ["MSBuild", "discard", "forever", "All"], self.now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"quietHours": "22:00"}))
            with self.assertRaises(ValueError):
                backend.read_json(path, backend.default_config())
            path.write_text(json.dumps({"rules": ["not a rule"]}))
            with self.assertRaisesRegex(ValueError, "Invalid rule"):
                backend.read_json(path, backend.default_config())

    def test_replacing_rule_still_works_at_the_rule_limit(self):
        for index in range(backend.MAX_RULES):
            backend.mutate(self.config, "add", [f"process-{index}", "silence", "hour", "All"], self.now)
        backend.mutate(self.config, "add", ["process-0", "silence", "forever", "All"], self.now)
        self.assertEqual(len(self.config["rules"]), backend.MAX_RULES)
        self.assertIsNone(self.config["rules"][0]["expiresAt"])
        with self.assertRaisesRegex(ValueError, "Rule limit reached"):
            backend.mutate(self.config, "add", ["new-process", "silence", "hour", "All"], self.now)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = Path(self.directory.name)
        self.location = {
            "dropin": base / "systemd/user/omarchy-crash-watch.service.d/50-omarchy-notification-rules-mgr.conf",
            "capture_off": base / "state/crash-capture-off",
        }
        self.now = dt.datetime(2026, 9, 24, 15, 0, tzinfo=dt.timezone.utc)
        self.config = backend.default_config()
        backend.mutate(self.config, "add", ["MSBuild", "silence", "forever", "All"], self.now)

    def test_dropin_is_quoted_and_watcher_restarted_only_on_change(self):
        with patch.object(backend, "run", side_effect=lambda argv, **kwargs: completed(argv)) as run:
            self.assertTrue(backend.apply_crash_settings(self.config, self.location, self.now))
            self.assertFalse(backend.apply_crash_settings(self.config, self.location, self.now))
        content = self.location["dropin"].read_text()
        self.assertIn('Environment="OMARCHY_CRASH_IGNORE=^(MSBuild)$"', content)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0], ["systemctl", "--user", "try-restart", "omarchy-crash-watch.service"])

    def test_failed_restart_restores_prior_override(self):
        target = self.location["dropin"]
        target.parent.mkdir(parents=True)
        target.write_text("[Service]\nEnvironment=OLD\n")
        def simulate(argv, **kwargs):
            return completed(argv, 1, "restart failed") if "try-restart" in argv else completed(argv)
        with patch.object(backend, "run", side_effect=simulate):
            with self.assertRaisesRegex(RuntimeError, "restart failed"):
                backend.apply_crash_settings(self.config, self.location, self.now)
        self.assertEqual(target.read_text(), "[Service]\nEnvironment=OLD\n")

    def test_journal_grouping_keeps_silenced_crashes_visible(self):
        rows = [
            {"name": "MSBuild", "timestamp": 20, "pid": "1"},
            {"name": "MSBuild", "timestamp": 10, "pid": "2"},
            {"name": "dotnet", "timestamp": 8, "pid": "3"},
        ]
        grouped = backend.group_crashes(rows, self.config, self.now)
        self.assertEqual(grouped[0]["count"], 2)
        self.assertEqual(grouped[0]["policy"], "muted by rule")
        self.assertEqual(grouped[1]["policy"], "allowed")

    def test_journal_query_caps_rows_and_bounds_quiet_hours(self):
        records = b"".join(
            (json.dumps({
                "_UID": str(os.getuid()), "COREDUMP_EXE": "/usr/bin/MSBuild",
                "__REALTIME_TIMESTAMP": str(index * 1_000_000),
            }) + "\n").encode()
            for index in range(252)
        )
        with patch.object(backend, "bounded_journal_output", return_value=(records, False, True)) as read:
            rows, limited = backend.journal_rows(since=100, until=200)
        command = read.call_args.args[0]
        self.assertEqual(command[command.index("-n") + 1], "251")
        self.assertIn("--since=@100", command)
        self.assertIn("--until=@200", command)
        self.assertEqual(len(rows), 250)
        self.assertTrue(limited)

    def test_journal_capture_has_hard_byte_limit(self):
        output, limited, complete = backend.bounded_journal_output(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1048576)"],
            max_bytes=1024,
        )
        self.assertEqual(len(output), 1024)
        self.assertTrue(limited)
        self.assertFalse(complete)

    def test_digest_labels_limited_count_as_lower_bound(self):
        rows = [{"name": "MSBuild", "timestamp": 150}, {"name": "MSBuild", "timestamp": 140}]
        with patch.object(backend, "journal_rows", return_value=(rows, True)) as query, \
             patch.object(backend, "run", side_effect=lambda argv, **kwargs: completed(argv)) as run:
            status = backend.send_crash_digest(100, 200)
        query.assert_called_once_with(since=100, until=200)
        self.assertIn("At least 2 crashes", run.call_args.args[0][-1])
        self.assertIn("at least 2", status)

    def test_failed_digest_send_is_reported_and_transition_status_is_preserved(self):
        rows = [{"name": "MSBuild", "timestamp": 150}]
        with patch.object(backend, "journal_rows", return_value=(rows, False)), \
             patch.object(backend, "run", side_effect=lambda argv, **kwargs: completed(argv, 1)):
            self.assertIn("could not be sent", backend.send_crash_digest(100, 200))
        location = {**self.location, "config": Path(self.directory.name) / "config.json",
                    "state": Path(self.directory.name) / "state.json"}
        state = {**backend.default_state(), "quietActive": True, "quietStartedAt": 100}
        self.config["quietHours"].update({"enabled": True, "start": "14:00", "end": "16:00"})
        with patch.object(backend, "send_crash_digest", return_value="Quiet hours ended · 1 crash summarized"), \
             patch.object(backend, "apply_crash_settings", return_value=True):
            backend.reconcile(self.config, state, location, self.now.replace(hour=17))
        self.assertEqual(state["status"], "Quiet hours ended · 1 crash summarized")

    def test_recent_crash_alert_exposes_its_process_for_mute_actions(self):
        popups = Path(self.directory.name) / "popups"
        history = popups / "history"
        history.mkdir(parents=True)
        (history / "1.json").write_text(json.dumps({"app": "omarchy-action", "summary": "Process crashed: MSBuild", "timestamp": 1000}))
        (history / "2.json").write_text(json.dumps({"app": "chat", "summary": "Process crashed: dotnet", "timestamp": 2000}))
        rows = backend.recent_notifications({"popups": popups, "history": history})
        self.assertEqual(rows[0]["crashProcess"], "")
        self.assertEqual(rows[1]["crashProcess"], "MSBuild")

    def test_recent_notifications_bound_accumulated_history_and_large_files(self):
        popups = Path(self.directory.name) / "popups"
        history = popups / "history"
        history.mkdir(parents=True)
        for index in range(180):
            timestamp = 1_000_000 + index * 1_000
            (history / f"{timestamp}-{index}.json").write_text(json.dumps({
                "app": "build", "summary": f"Alert {index}",
                "body": "ok", "timestamp": timestamp,
            }))
        oversized = history / "9999999999999-999.json"
        oversized.write_text(json.dumps({"app": "build", "body": "x" * (backend.MAX_NOTIFICATION_BYTES + 1)}))
        (popups / "9999999999998-998.json").symlink_to(oversized)
        with patch.object(backend, "bounded_file_bytes", wraps=backend.bounded_file_bytes) as read:
            rows = backend.recent_notifications({"popups": popups, "history": history})
        self.assertEqual(len(rows), backend.MAX_RECENT_NOTIFICATIONS)
        self.assertEqual(rows[0]["summary"], "Alert 179")
        self.assertLessEqual(read.call_count, backend.MAX_NOTIFICATION_FILES)
        self.assertNotIn(oversized, [call.args[0] for call in read.call_args_list])

    def test_recent_notification_text_is_bounded_for_panel_output(self):
        popups = Path(self.directory.name) / "popups"
        history = popups / "history"
        history.mkdir(parents=True)
        (history / "1000-1.json").write_text(json.dumps({
            "app": "a" * 500, "summary": "s" * 1000,
            "body": "b" * 20_000, "timestamp": 1000,
        }))
        rows = backend.recent_notifications({"popups": popups, "history": history})
        self.assertEqual(len(rows[0]["app"]), backend.MAX_NOTIFICATION_APP_CHARS)
        self.assertEqual(len(rows[0]["summary"]), backend.MAX_NOTIFICATION_SUMMARY_CHARS)
        self.assertEqual(len(rows[0]["body"]), backend.MAX_NOTIFICATION_BODY_CHARS)

    def test_settings_file_and_command_output_are_bounded(self):
        settings = Path(self.directory.name) / "settings.json"
        settings.write_bytes(b"x" * (backend.MAX_SETTINGS_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "read limit"):
            backend.read_json(settings, backend.default_config())
        with self.assertRaisesRegex(RuntimeError, "Command output exceeded"):
            backend.run([sys.executable, "-c", "import sys; sys.stdout.write('x' * 1048576)"])

    def test_oversized_crash_override_is_not_loaded(self):
        target = self.location["dropin"]
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x" * (backend.MAX_OVERRIDE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "read limit"):
            backend.apply_crash_settings(self.config, self.location, self.now)

    def test_quiet_hours_restores_previous_dnd_when_no_profile_controls_it(self):
        state = backend.default_state()
        location = {**self.location, "config": Path(self.directory.name) / "config.json", "state": Path(self.directory.name) / "state.json"}
        self.config["rules"] = []
        self.config["quietHours"].update({"enabled": True, "start": "14:00", "end": "16:00", "digest": False})
        commands = []
        def capture(argv, **kwargs):
            commands.append(argv)
            return completed(argv)
        with patch.object(backend, "run", side_effect=capture), patch.object(backend, "dnd_state", return_value=False):
            backend.reconcile(self.config, state, location, self.now)
            backend.reconcile(self.config, state, location, self.now.replace(hour=17))
        self.assertEqual(state["preQuietDnd"], None)
        self.assertIn(["omarchy-shell", "notifications", "setDnd", "on"], commands)
        self.assertIn(["omarchy-shell", "notifications", "setDnd", "off"], commands)


if __name__ == "__main__":
    unittest.main()
