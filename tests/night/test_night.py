from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from kiln.night.alerts import Alerter
from kiln.night.gate import sha256_file
from kiln.night.plan import Plan, PlanError, load_plan
from kiln.night.prereg import build_manifest, post_manifest
from kiln.night.runner import NightRunner, resolve_cmd
from kiln.night.spend import read_spend

PLANS = Path(__file__).resolve().parents[2] / "src" / "kiln" / "night" / "plans"
CAPS = {"max_tokens": 1_000_000, "max_usd": 100.0, "max_gpu_hours": 10.0}


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def touch(name: str) -> list[str]:
    """A step that appends its name to calls.txt in the working directory (the repo root)."""
    return py(f"open('calls.txt','a').write('{name}\\n')")


def make_plan(steps: list[dict], **kw) -> Plan:
    data = {"name": "t", "caps": CAPS, "retry": {"base_s": 1, "factor": 2, "jitter": 0.0},
            "cap_check_s": 0.0, "steps": steps}
    data.update(kw)
    return Plan.model_validate(data)


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.messages: list[str] = []
        self.fail = fail

    def __call__(self, text: str) -> None:
        self.messages.append(text)
        if self.fail:
            raise OSError("webhook down")


def make_runner(tmp_path: Path, plan: Plan, poster: Recorder | None = None, sleeps: list | None = None):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    state = tmp_path / "state"
    sleeps = sleeps if sleeps is not None else []
    alerter = Alerter(state / "alerts.log", poster or Recorder(), "t")
    runner = NightRunner(plan, state, repo_root=repo, runs_dir=repo / "runs", alerter=alerter,
                         sleep=sleeps.append)
    return runner, repo


def calls(repo: Path) -> list[str]:
    path = repo / "calls.txt"
    return path.read_text().split() if path.exists() else []


# ---------- plans ----------

@pytest.mark.parametrize("name", ["night1.toml", "night2.toml"])
def test_bundled_plans_parse(name: str) -> None:
    plan = load_plan(PLANS / name)
    assert plan.order()
    assert plan.caps.complete() == (name == "night2.toml")   # night2 caps set from the dry run; never defaulted


def test_night2_pushes_before_the_label_steps_and_stops_there() -> None:
    plan = load_plan(PLANS / "night2.toml")
    order = [s.name for s in plan.order()]
    assert order.index("push") < order.index("fetch_labels")
    assert plan.step("fetch_labels").on_fail == plan.step("score").on_fail == "stop"
    cmd = plan.step("run_conditions").cmd
    assert "--items-file" in cmd and "--frozen" in cmd and "--allow-no-remote" in plan.step("push").cmd
    assert cmd[cmd.index("--parallel") + 1] == "12"
    assert order.index("run_conditions") < order.index("finalize") < order.index("manifest")
    assert plan.step("manifest").depends_on == ["finalize"]


def test_h100_replication_never_writes_where_the_gb10_run_does() -> None:
    gb10, h100 = load_plan(PLANS / "night2.toml"), load_plan(PLANS / "night2-h100.toml")
    assert h100.caps.complete() and h100.labels_must_be_absent
    assert (h100.gate.receipt, h100.gate.manifest) == ("protocol/posts-h100.jsonl", "protocol/predictions-h100.manifest.json")
    for name in ("run_conditions", "finalize", "manifest"):
        cmd = h100.step(name).cmd
        assert cmd[cmd.index("--runs-dir") + 1] == "runs-h100"
    assert "--out" in h100.step("manifest").cmd and "protocol/predictions-h100.manifest.json" in h100.step("manifest").cmd
    assert "protocol/posts-h100.jsonl" in h100.step("post_hash").cmd
    shared = {"runs", "protocol/posts.jsonl", "protocol/predictions.manifest.json"}
    assert not shared & {a for s in h100.steps for a in s.cmd}             # no GB10 output path anywhere
    assert h100.step("run_conditions").env == ["GEMINI_API_KEY_2"]
    same = lambda plan: [a for a in plan.step("run_conditions").cmd if a not in ("--runs-dir", "runs-h100")]  # noqa: E731
    assert same(h100) == same(gb10)                                          # same experiment otherwise
    order = [s.name for s in h100.order()]
    assert order.index("finalize") < order.index("manifest") < order.index("post_hash") < order.index("push")


def test_h100_preflight_requires_the_second_gemini_account(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    code = load_plan(PLANS / "night2-h100.toml").step("preflight").cmd[2]
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("GEMINI_API_KEY")}
    run = lambda extra: subprocess.run([sys.executable, "-c", code], env={**env, **extra}, capture_output=True)  # noqa: E731
    assert run({"GEMINI_API_KEY_2": "x"}).returncode == 0
    assert run({"GEMINI_API_KEY_2": "x", "GEMINI_API_KEY": "y"}).returncode != 0
    assert run({}).returncode != 0


def test_on_fail_stop_alerts_and_stops_the_night(tmp_path: Path) -> None:
    plan = make_plan([{"name": "a", "cmd": touch("a")},
                      {"name": "b", "cmd": py("raise SystemExit(3)"), "depends_on": ["a"], "retries": 0,
                       "on_fail": "stop"},
                      {"name": "c", "cmd": touch("c"), "depends_on": ["a"]},
                      {"name": "z", "cmd": touch("z"), "always": True}])
    poster = Recorder()
    runner, repo = make_runner(tmp_path, plan, poster)
    report = runner.run(install_signals=False)
    assert calls(repo) == ["a", "z"]                    # c never ran; the always-step still did
    assert report.status["b"] == "failed" and report.status["c"] == "not_run"
    assert any("on_fail=stop" in m for m in poster.messages)


def test_night2_order_and_gates() -> None:
    plan = load_plan(PLANS / "night2.toml")
    order = [s.name for s in plan.order()]
    assert order.index("post_hash") < order.index("fetch_labels") < order.index("score")
    assert plan.step("fetch_labels").requires_receipt and plan.step("score").requires_receipt
    assert [s.name for s in plan.finally_steps()] == ["stop_brev"]
    assert plan.labels_must_be_absent


def test_night2_pins_the_experiment_model() -> None:
    cmd = load_plan(PLANS / "night2.toml").step("run_conditions").cmd
    assert cmd[cmd.index("--model") + 1] == "gemini-3.8-flash"
    for path in PLANS.glob("*.toml"):
        assert "gemini-2.5-flash" not in path.read_text(encoding="utf-8")  # 404 for new users


def test_unknown_dependency_and_cycle_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown"):
        make_plan([{"name": "a", "cmd": ["x"], "depends_on": ["nope"]}])
    with pytest.raises(ValueError, match="cycle"):
        make_plan([{"name": "a", "cmd": ["x"], "depends_on": ["b"]},
                   {"name": "b", "cmd": ["x"], "depends_on": ["a"]}])
    bad = tmp_path / "bad.toml"
    bad.write_text("name = 'x'\nsteps = []\n")
    with pytest.raises(PlanError):
        load_plan(bad)


def test_run_refuses_without_caps(tmp_path: Path) -> None:
    plan = make_plan([{"name": "a", "cmd": touch("a")}], caps={})
    runner, repo = make_runner(tmp_path, plan)
    with pytest.raises(PlanError, match="OPEN-02"):
        runner.run(install_signals=False)
    assert calls(repo) == []


def test_resolve_cmd_expands_env_and_python() -> None:
    out = resolve_cmd(["python", "stop", "${X}", "$Y"], {"X": "a", "Y": "b"})
    assert out == [sys.executable, "stop", "a", "b"]


# ---------- running ----------

def test_runs_in_order_and_resumes(tmp_path: Path) -> None:
    steps = [{"name": "a", "cmd": touch("a")}, {"name": "b", "cmd": touch("b"), "depends_on": ["a"]}]
    runner, repo = make_runner(tmp_path, make_plan(steps))
    assert runner.run(install_signals=False).ok
    assert calls(repo) == ["a", "b"]

    again, _ = make_runner(tmp_path, make_plan(steps))
    report = again.run(install_signals=False)
    assert report.status == {"a": "resumed", "b": "resumed"} and calls(repo) == ["a", "b"]

    changed = [steps[0], {"name": "b", "cmd": touch("b2"), "depends_on": ["a"]}]
    third, _ = make_runner(tmp_path, make_plan(changed))
    assert third.run(install_signals=False).status == {"a": "resumed", "b": "done"}
    assert calls(repo) == ["a", "b", "b2"]
    state = json.loads((tmp_path / "state" / "state.json").read_text())
    assert state["steps"]["b"] == "done"


def test_retry_with_backoff_then_fail_and_skip_dependents(tmp_path: Path) -> None:
    steps = [
        {"name": "bad", "cmd": py("import sys; open('calls.txt','a').write('bad\\n'); sys.exit(3)"), "retries": 2},
        {"name": "child", "cmd": touch("child"), "depends_on": ["bad"]},
        {"name": "other", "cmd": touch("other")},
        {"name": "cleanup", "cmd": touch("cleanup"), "always": True},
    ]
    poster, sleeps = Recorder(), []
    runner, repo = make_runner(tmp_path, make_plan(steps), poster, sleeps)
    report = runner.run(install_signals=False)
    assert report.status["bad"] == "failed"
    assert report.status["child"].startswith("skipped:deps")
    assert report.status["other"] == "done" and report.status["cleanup"] == "done"
    assert calls(repo) == ["bad", "bad", "bad", "other", "cleanup"]
    assert sleeps == [1, 2]
    assert any("FAILED after 3 attempts" in m for m in poster.messages)
    assert not report.ok
    assert not (tmp_path / "state" / "bad.done").exists()


def test_timeout_kills_hanging_step(tmp_path: Path) -> None:
    plan = make_plan([{"name": "hang", "cmd": py("import time; time.sleep(60)"), "timeout_s": 0.5, "retries": 0}])
    runner, _ = make_runner(tmp_path, plan)
    report = runner.run(install_signals=False)
    assert report.status["hang"] == "failed"
    assert "timeout" in (tmp_path / "state" / "alerts.log").read_text()


def test_cap_breach_stops_cleanly(tmp_path: Path) -> None:
    steps = [{"name": "a", "cmd": touch("a")}, {"name": "cleanup", "cmd": touch("cleanup"), "always": True}]
    poster = Recorder()
    runner, repo = make_runner(tmp_path, make_plan(steps), poster)
    run_dir = repo / "runs" / "C4-s0"
    run_dir.mkdir(parents=True)
    (run_dir / "cost.json").write_text(json.dumps({"PG-1": {"tokens_in": 10, "tokens_out": 5, "usd": 150.0}}))
    report = runner.run(install_signals=False)
    assert report.status == {"a": "not_run", "cleanup": "done"}
    assert "USD cap" in (report.stopped or "")
    assert calls(repo) == ["cleanup"]
    assert any("stopping" in m for m in poster.messages)


def test_spend_sums_cost_and_gpu_seconds(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    run.mkdir()
    (run / "cost.json").write_text(json.dumps({"tokens_in": 3, "tokens_out": 4, "usd": 1.5}))
    (run / "compute_requests.jsonl").write_text('{"gpu_seconds": 1800}\n{"gpu_seconds": 1800}\n')
    spend = read_spend(tmp_path)
    assert (spend.tokens, spend.usd, spend.gpu_hours) == (7, 1.5, 1.0)
    (run / "cost.json").write_text("{broken")
    assert read_spend(tmp_path).errors


def test_webhook_failure_does_not_crash(tmp_path: Path) -> None:
    runner, _ = make_runner(tmp_path, make_plan([{"name": "a", "cmd": touch("a")}]), Recorder(fail=True))
    assert runner.run(install_signals=False).ok
    assert "alert delivery failed" in (tmp_path / "state" / "alerts.log").read_text()


def test_heartbeat_message(tmp_path: Path) -> None:
    runner, _ = make_runner(tmp_path, make_plan([{"name": "a", "cmd": touch("a")}]))
    assert "pending=1" in runner.heartbeat_message()


def test_missing_env_skip_or_fail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("KILN_TEST_UNSET", raising=False)
    steps = [
        {"name": "need", "cmd": touch("need"), "env": ["KILN_TEST_UNSET"]},
        {"name": "brev", "cmd": touch("brev"), "env": ["KILN_TEST_UNSET"], "on_missing_env": "skip", "always": True},
    ]
    runner, repo = make_runner(tmp_path, make_plan(steps))
    report = runner.run(install_signals=False)
    assert report.status["need"] == "failed" and report.status["brev"].startswith("skipped:env")
    assert calls(repo) == []


# ---------- label gates ----------

def test_labels_present_fails_preflight(tmp_path: Path) -> None:
    steps = [{"name": "a", "cmd": touch("a")}]
    runner, repo = make_runner(tmp_path, make_plan(steps, labels_must_be_absent=True))
    (repo / "labels").mkdir()
    report = runner.run(install_signals=False)
    assert report.status == {"a": "not_run"} and "labels" in (report.stopped or "")
    assert calls(repo) == []


def write_predictions(repo: Path) -> None:
    run = repo / "runs" / "C4-gemini-s0-heldout"
    run.mkdir(parents=True, exist_ok=True)
    (run / "predictions.jsonl").write_text('{"item_id": "PG-1"}\n')


def test_receipt_gate(tmp_path: Path) -> None:
    steps = [{"name": "labels_step", "cmd": touch("labels_step"), "requires_receipt": True}]
    runner, repo = make_runner(tmp_path, make_plan(steps))
    write_predictions(repo)
    build_manifest(repo, "runs", "protocol/predictions.manifest.json")
    report = runner.run(install_signals=False)
    assert report.status["labels_step"].startswith("skipped:gate") and calls(repo) == []

    posted: list[str] = []
    record = post_manifest(repo, "protocol/predictions.manifest.json", "protocol/posts.jsonl",
                           poster=lambda c: posted.append(c) or b'{"id": "1", "timestamp": "t"}')
    assert record["sha256"] == sha256_file(repo / "protocol/predictions.manifest.json")
    assert record["message_id"] == "1" and len(posted) == 1
    # Idempotent: the same digest is not posted twice.
    post_manifest(repo, "protocol/predictions.manifest.json", "protocol/posts.jsonl",
                  poster=lambda c: posted.append(c) or b"{}")
    assert len(posted) == 1

    ok_runner, _ = make_runner(tmp_path, make_plan(steps))
    assert ok_runner.run(install_signals=False).status["labels_step"] == "done"


def test_receipt_gate_rejects_edited_predictions(tmp_path: Path) -> None:
    steps = [{"name": "labels_step", "cmd": touch("labels_step"), "requires_receipt": True}]
    runner, repo = make_runner(tmp_path, make_plan(steps))
    write_predictions(repo)
    build_manifest(repo, "runs", "protocol/predictions.manifest.json")
    post_manifest(repo, "protocol/predictions.manifest.json", "protocol/posts.jsonl", poster=lambda c: b"{}")
    (repo / "runs" / "C4-gemini-s0-heldout" / "predictions.jsonl").write_text('{"item_id": "PG-2"}\n')
    report = runner.run(install_signals=False)
    assert "changed since hashing" in report.status["labels_step"]
    assert calls(repo) == []


def test_manifest_writes_per_run_hash(tmp_path: Path) -> None:
    write_predictions(tmp_path)
    build_manifest(tmp_path, "runs", "protocol/m.json")
    run = tmp_path / "runs" / "C4-gemini-s0-heldout"
    assert (run / "prediction.sha256").read_text().strip() == sha256_file(run / "predictions.jsonl")


# ---------- dry run ----------

def test_dry_run_executes_nothing(tmp_path: Path) -> None:
    steps = [{"name": "a", "cmd": touch("a")}, {"name": "z", "cmd": touch("z"), "always": True}]
    runner, repo = make_runner(tmp_path, make_plan(steps, caps={}))
    lines = runner.dry_run()
    assert [l.split(":")[0] for l in lines] == ["a", "z"]
    assert calls(repo) == [] and not (tmp_path / "state").exists()


def test_cli_dry_run_on_bundled_plan(tmp_path: Path, capsys) -> None:
    from kiln.night.__main__ import main
    assert main(["run", str(PLANS / "night2.toml"), "--dry-run", "--state-dir", str(tmp_path / "s")]) == 0
    out = capsys.readouterr().out
    assert "fetch_labels" in out and "requires_receipt" in out
