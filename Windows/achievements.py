"""Local achievement progress. A short-lived helper (steam.py) tells Steam about new unlocks,
so the always-on runtime never shows up as a running game in Steam."""
import json
import subprocess
import sys
import threading
from pathlib import Path

from config import CONTRACT, DEMO, write_json

GOALS = CONTRACT['achievements']


def helper_command(ids):
    if getattr(sys, 'frozen', False): command = [str(Path(sys.executable).with_name('STTS.exe'))]
    else: command = [sys.executable, str(Path(__file__).with_name('launcher.py'))]
    return command + ['--steam-achievements', *ids]


class Achievements:
    def __init__(self, folder, enabled=not DEMO):
        self.path, self.enabled = Path(folder) / 'achievements.json', enabled
        try: self.state = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): self.state = {}
        self.lock = threading.Lock(); self.reporting = False

    def progress(self, stat):
        value = self.state.get(stat, 0)
        return len(value) if isinstance(value, list) else value

    def count(self, stat, amount=1):
        with self.lock: self.state[stat] = self.state.get(stat, 0) + amount
        self.check()

    def include(self, stat, value):
        # Distinct values, such as the microphone filters or languages used.
        with self.lock:
            values = self.state.setdefault(stat, [])
            if value in values: return
            values.append(value)
        self.check()

    def level(self, stat, value):
        # Current totals, such as saved phrases; the best total is kept.
        with self.lock:
            if value <= self.state.get(stat, 0): return
            self.state[stat] = value
        self.check()

    def check(self):
        if not self.enabled: return
        with self.lock:
            unlocked = self.state.setdefault('unlocked', [])
            for goal in GOALS:
                if goal['id'] not in unlocked and self.progress(goal['stat']) >= goal['goal']: unlocked.append(goal['id'])
            try: write_json(self.path, self.state)
            except OSError: pass
            pending = [ident for ident in unlocked if ident not in self.state.get('reported', [])]
            if not pending or self.reporting: return
            self.reporting = True
        threading.Thread(target=self.report, args=(pending,), daemon=True).start()

    def report(self, ids):
        try:
            # Steam may be closed; unreported unlocks are retried at the next check.
            result = subprocess.run(helper_command(ids), timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            stored = result.returncode == 0
        except (OSError, subprocess.SubprocessError): stored = False
        with self.lock:
            self.reporting = False
            if stored:
                self.state['reported'] = sorted(set(self.state.get('reported', [])) | set(ids))
                try: write_json(self.path, self.state)
                except OSError: pass
