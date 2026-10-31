"""Run a night plan: resumable, retried, capped, alerted, and stoppable.

For each main step, in dependency order:
    skip if its done-marker matches the step spec (resume);
    skip if a dependency did not finish, a required env var is missing (on_missing_env="skip"),
    or a `requires_receipt` gate is closed;
    check the caps; a breach stops the night cleanly;
    run the subprocess with a timeout, retrying with exponential backoff and jitter;
    write the done-marker only on success.
Always-steps run last, even after failure, a cap breach or a stop signal.

A stop (SIGINT/SIGTERM or a cap breach) starts nothing new; the running subprocess gets
`stop_grace_s` to finish and is then terminated. State goes to <state_dir>/state.json after
every change, alerts to <state_dir>/alerts.log and, if configured, to Discord.
"""
from __future__ import annotations

import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from kiln.night.alerts import Alerter
from kiln.night.gate import labels_absent, receipt_ok
from kiln.night.plan import Plan, PlanError, Step
from kiln.night.spend import breach, read_spend

__all__ = ["NightRunner", "NightReport", "resolve_cmd"]

_VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)")
_POLL_S = 0.1


def resolve_cmd(cmd: list[str], env: dict[str, str]) -> list[str]:
    """`python` becomes this interpreter; ${VAR} and $VAR are expanded from env (missing -> '')."""
    out = [_VAR.sub(lambda m: env.get(m.group(1) or m.group(2), ""), arg) for arg in cmd]
    if out[0] == "python":
        out[0] = sys.executable
    return out


@dataclass
class NightReport:
    status: dict[str, str] = field(default_factory=dict)   # step -> done|resumed|failed|skipped:<why>|not_run
    stopped: str | None = None

    @property
    def ok(self) -> bool:
        return self.stopped is None and all(s in ("done", "resumed") or s.startswith("skipped:env")
                                            for s in self.status.values())


class NightRunner:
    def __init__(
        self,
        plan: Plan,
        state_dir: str | Path,
        *,
        repo_root: str | Path = ".",
        runs_dir: str | Path = "runs",
        alerter: Alerter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.plan = plan
        self.state_dir = Path(state_dir)
        self.repo_root = Path(repo_root).resolve()
        self.runs_dir = Path(runs_dir)
        self.alerter = alerter or Alerter(self.state_dir / "alerts.log", None, plan.name)
        self.sleep = sleep
        self.rng = rng or random.Random()
        self.report = NightReport()
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._last_cap_check = 0.0

    # ---------- public ----------

    def request_stop(self, why: str) -> None:
        if not self._stop.is_set():
            self.report.stopped = why
            self._stop.set()
            self.alerter.send(f"stopping: {why}")

    def dry_run(self) -> list[str]:
        lines = []
        for s in self.plan.order() + self.plan.finally_steps():
            state = "resume (done)" if self._is_done(s) else "run"
            flags = [f for f, on in (("always", s.always), ("requires_receipt", s.requires_receipt)) if on]
            deps = f" after {', '.join(s.depends_on)}" if s.depends_on else ""
            lines.append(f"{s.name}: {state}{deps} {' '.join(s.cmd)}" + (f" [{', '.join(flags)}]" if flags else ""))
        return lines

    def run(self, *, install_signals: bool = True) -> NightReport:
        if not self.plan.caps.complete():
            raise PlanError("plan caps max_tokens, max_usd and max_gpu_hours must all be set (OPEN-02)")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        restore = self._install_signals() if install_signals else None
        heartbeat = threading.Thread(target=self._heartbeat, daemon=True)
        heartbeat.start()
        self.alerter.send(f"night {self.plan.name!r} starting")
        try:
            if self.plan.labels_must_be_absent and not labels_absent(self.repo_root):
                self.request_stop("preflight: labels/ is present on the run host before the hash is posted")
            for step in self.plan.order():
                self.report.status[step.name] = self._main_step(step)
                self._save()
        finally:
            for step in self.plan.finally_steps():
                self.report.status[step.name] = self._finally_step(step)
                self._save()
            self._finished.set()
            if restore:
                restore()
            failed = [n for n, s in self.report.status.items() if s == "failed"]
            self.alerter.send(f"night {self.plan.name!r} finished: {'OK' if self.report.ok else 'NOT OK'}; "
                              f"failed={failed} stopped={self.report.stopped!r}")
        return self.report

    # ---------- steps ----------

    def _main_step(self, step: Step) -> str:
        if self._is_done(step):
            return "resumed"
        if self._stop.is_set():
            return "not_run"
        bad = [d for d in step.depends_on if self.report.status.get(d) not in ("done", "resumed")]
        if bad:
            self.alerter.send(f"{step.name}: skipped, dependencies not done: {bad}")
            return f"skipped:deps {bad}"
        missing = [v for v in step.env if not os.environ.get(v)]
        if missing:
            if step.on_missing_env == "skip":
                self.alerter.send(f"{step.name}: skipped, env not set: {missing}")
                return f"skipped:env {missing}"
            self.alerter.send(f"{step.name}: FAILED, env not set: {missing}")
            return "failed"
        if step.requires_receipt:
            ok, why = receipt_ok(self.repo_root, self.plan.gate.receipt, self.plan.gate.manifest)
            if not ok:
                self.alerter.send(f"{step.name}: blocked by label gate: {why}")
                return f"skipped:gate {why}"
        if self._check_caps(force=True):
            return "not_run"
        return self._execute(step)

    def _finally_step(self, step: Step) -> str:
        if self._is_done(step):
            return "resumed"
        missing = [v for v in step.env if not os.environ.get(v)]
        if missing:
            if step.on_missing_env == "skip":
                self.alerter.send(f"{step.name}: skipped, env not set: {missing}")
                return f"skipped:env {missing}"
            self.alerter.send(f"{step.name}: FAILED, env not set: {missing}")
            return "failed"
        return self._execute(step, honour_stop=False)

    def _execute(self, step: Step, honour_stop: bool = True) -> str:
        tries = step.retries + 1
        for attempt in range(1, tries + 1):
            code, why = self._spawn(step, honour_stop)
            if code == 0:
                self._mark_done(step)
                return "done"
            if honour_stop and self._stop.is_set():
                self.alerter.send(f"{step.name}: interrupted ({why}); will rerun on resume")
                return "not_run"
            if attempt < tries:
                delay = min(self.plan.retry.base_s * self.plan.retry.factor ** (attempt - 1),
                            self.plan.retry.max_delay_s)
                delay *= 1 + self.plan.retry.jitter * self.rng.random()
                self.alerter.send(f"{step.name}: attempt {attempt}/{tries} failed ({why}); retrying in {delay:.0f}s")
                self.sleep(delay)
        self.alerter.send(f"{step.name}: FAILED after {tries} attempts ({why})")
        if step.on_fail == "stop" and honour_stop:
            self.request_stop(f"{step.name} failed and is marked on_fail=stop")
        return "failed"

    def _spawn(self, step: Step, honour_stop: bool) -> tuple[int, str]:
        env = dict(os.environ)
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")  # AGENTS.md rule 6
        out_path = self.state_dir / f"{step.name}.log"
        kwargs: dict = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        try:
            with out_path.open("ab") as out:
                proc = subprocess.Popen(resolve_cmd(step.cmd, env), cwd=self.repo_root, env=env,
                                        stdout=out, stderr=subprocess.STDOUT, **kwargs)
        except OSError as exc:
            return -1, f"could not start: {type(exc).__name__}: {exc}"
        start = time.monotonic()
        stop_seen: float | None = None
        while proc.poll() is None:
            now = time.monotonic()
            if now - start > step.timeout_s:
                self._kill(proc)
                return -1, f"timeout after {step.timeout_s:.0f}s"
            if honour_stop:
                self._check_caps()
                if self._stop.is_set():
                    stop_seen = stop_seen or now
                    if now - stop_seen > self.plan.stop_grace_s:
                        self._kill(proc)
                        return -1, "terminated after stop grace period"
            time.sleep(_POLL_S)
        return proc.returncode, f"exit code {proc.returncode}"

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError):
            proc.kill()
            proc.wait()

    # ---------- state, caps, heartbeat ----------

    def _marker(self, step: Step) -> Path:
        return self.state_dir / f"{step.name}.done"

    def _is_done(self, step: Step) -> bool:
        m = self._marker(step)
        return m.exists() and m.read_text(encoding="utf-8").strip() == step.spec_hash()

    def _mark_done(self, step: Step) -> None:
        self._marker(step).write_text(step.spec_hash() + "\n", encoding="utf-8")

    def _save(self) -> None:
        state = {"plan": self.plan.name, "stopped": self.report.stopped, "steps": self.report.status}
        tmp = self.state_dir / "state.json.tmp"
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_dir / "state.json")

    def _check_caps(self, force: bool = False) -> bool:
        """True if the night must stop. Reads spend at most every cap_check_s (and always when forced)."""
        now = time.monotonic()
        if force or now - self._last_cap_check >= self.plan.cap_check_s or self._last_cap_check == 0.0:
            self._last_cap_check = now
            why = breach(read_spend(self.runs_dir), self.plan.caps)
            if why:
                self.request_stop(f"cap: {why}")
        return self._stop.is_set()

    def heartbeat_message(self) -> str:
        counts: dict[str, int] = {}
        for s in self.report.status.values():
            key = s.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
        pending = len(self.plan.steps) - len(self.report.status)
        return (f"heartbeat: {counts} pending={pending}; "
                f"{read_spend(self.runs_dir).summary(self.plan.caps)}")

    def _heartbeat(self) -> None:
        while not self._finished.wait(self.plan.heartbeat_s):
            self.alerter.send(self.heartbeat_message())

    def _install_signals(self) -> Callable[[], None] | None:
        if threading.current_thread() is not threading.main_thread():
            return None
        old = {}
        for name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                old[sig] = signal.signal(sig, lambda s, f: self.request_stop(f"signal {signal.Signals(s).name}"))
            except (ValueError, OSError):
                continue

        def restore() -> None:
            for sig, handler in old.items():
                signal.signal(sig, handler)
        return restore
