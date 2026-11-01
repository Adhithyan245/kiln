"""python -m kiln.scoring on synthetic runs, manifests, receipts and fake labels (no real data)."""
import io
import json
import subprocess
import sys
import urllib.error
from datetime import datetime, timezone

import pytest

import kiln.scoring.__main__ as cli
from kiln.night.prereg import build_manifest, post_manifest
from kiln.schemas import Category, ComputeRequest, Item, Label, Prediction

RUN = "C4-synthetic-s0-heldout"
SECRET_URL = "https://discord.example/api/webhooks/123/SYNTHETIC-SECRET-TOKEN"
MESSAGE_ID = "1300000000000000001"
POSTED_AT = "2026-01-01T03:00:00.000000+00:00"
CATEGORIES = [Category.completely_reacted, Category.unreacted, Category.transformed, Category.partially_reacted]


def build_repo(tmp_path):
    """Synthetic repo: items file, one run, manifest and receipt (via kiln.night.prereg), fake labels."""
    items = [Item(item_id=f"syn-{i}", source="precursor_genome", precursor_a=f"A{i}O", precursor_b=f"B{i}O",
                  temperature_c=700.0, dwell_h=1.0, split="heldout") for i in range(4)]
    dev = Item(item_id="syn-dev", source="precursor_genome", precursor_a="ZO", precursor_b="YO", temperature_c=700.0, split="dev")
    (tmp_path / "items.jsonl").write_text("".join(i.model_dump_json() + "\n" for i in [*items, dev]))
    run_dir = tmp_path / "runs" / RUN
    run_dir.mkdir(parents=True)
    predictions = [Prediction(run_id=RUN, condition="C4", seed=0, item_id=item.item_id, p_react=p, category=c,
                              cause="", fix="", evidence=[], cost={}, compute_requests=[f"{RUN}:compute:{n}"] if n == 0 else [])
                   for n, (item, p, c) in enumerate(zip(items, (0.9, 0.2, 0.3, 0.7), CATEGORIES))]
    (run_dir / "predictions.jsonl").write_text("".join(p.model_dump_json() + "\n" for p in predictions))
    request = ComputeRequest(request_id=f"{RUN}:compute:0", run_id=RUN, item_id="syn-0", agent="thermo", tier="single_point",
                             reason="synthetic", inputs={}, settings={}, cache_key="k", compute_units=1.0, gpu_seconds=2.5,
                             p_react_before=0.5, p_react_after=0.9)
    (run_dir / "compute_requests.jsonl").write_text(request.model_dump_json() + "\n")
    build_manifest(tmp_path, "runs", "protocol/predictions.manifest.json")
    posted = {}

    def poster(content):
        posted["content"] = content
        return json.dumps({"id": MESSAGE_ID, "timestamp": POSTED_AT}).encode()
    record = post_manifest(tmp_path, "protocol/predictions.manifest.json", "protocol/posts.jsonl", poster=poster)
    # Fake labels, outside the repo's labels/ folder; synthetic values only.
    labels = [Label(item_id="syn-0", category="completely_reacted", reacted=True),
              Label(item_id="syn-1", category="unreacted", reacted=False),
              Label(item_id="syn-2", category="unreacted", reacted=False),
              Label(item_id="syn-3", category="partially_reacted", reacted=True)]
    (tmp_path / "fake_labels.jsonl").write_text("".join(label.model_dump_json() + "\n" for label in labels))
    message = {"id": MESSAGE_ID, "content": posted["content"], "timestamp": POSTED_AT, "edited_timestamp": None}
    return record, message


def argv(tmp_path, *extra):
    return ["--repo-root", str(tmp_path), "--run-dir", f"runs/{RUN}", "--labels", str(tmp_path / "fake_labels.jsonl"),
            "--receipt", "protocol/posts.jsonl", "--items-file", str(tmp_path / "items.jsonl"), *extra]


@pytest.fixture
def label_reads(monkeypatch):
    calls = []
    real = cli.read_labels_jsonl

    def spy(path):
        calls.append(path)
        return real(path)
    monkeypatch.setattr(cli, "read_labels_jsonl", spy)
    return calls


def fake_discord(message):
    return cli.discord_confirm(lambda message_id: message, environ={})


def test_scores_after_discord_confirmation(tmp_path, capsys, label_reads):
    record, message = build_repo(tmp_path)
    assert cli.main(argv(tmp_path), confirm=fake_discord(message), environ={}) == 0
    assert len(label_reads) == 1
    result = json.loads((tmp_path / "results" / RUN / "evaluation.json").read_text())
    assert result["run"] == {"run_id": RUN, "run_dir": f"runs/{RUN}", "manifest_sha256": record["sha256"],
                             "verification": "discord", "message_id": MESSAGE_ID}
    metrics = result["metrics"]
    assert metrics["n"] == 4 and metrics["auroc"] == 1.0 and metrics["four_class_accuracy"] == 0.75
    assert result["compute_total"]["requests"] == 1 and result["compute_total"]["moved_toward_label"] == 1
    assert result["compute_requests"][0]["moved_toward_label"] is True
    table = capsys.readouterr().out
    assert "| AUROC (reacted vs not) | 1.000 |" in table and "| Four-class accuracy | 0.750 |" in table
    assert (tmp_path / "results" / RUN / "evaluation.md").read_text() in table


@pytest.mark.parametrize("change", [
    {"content": "Kiln predictions manifest sha256 " + "0" * 64},   # a different digest was posted
    {"edited_timestamp": "2026-01-01T04:00:00+00:00"},           # edited after posting
    {"id": "1300000000000000002"},                                 # not the receipt's message
    {"timestamp": "2999-01-01T00:00:00+00:00"},                    # posting time in the future
])
def test_discord_mismatch_locks_without_reading_labels(tmp_path, capsys, label_reads, change):
    _, message = build_repo(tmp_path)
    assert cli.main(argv(tmp_path), confirm=fake_discord({**message, **change}), environ={}) == 2
    assert label_reads == []
    assert "Scoring locked, labels not read" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_receipt_alone_is_never_proof(tmp_path, capsys, label_reads):
    build_repo(tmp_path)
    # No webhook in the environment: the receipt matches the manifest but nothing independent confirms it.
    assert cli.main(argv(tmp_path), environ={}) == 2
    assert "KILN_PREREG_WEBHOOK is not set" in capsys.readouterr().err
    assert label_reads == []


@pytest.mark.parametrize("answer", [1, "yes", "True", None])
def test_confirmer_must_return_literal_true(tmp_path, label_reads, answer):
    build_repo(tmp_path)
    assert cli.main(argv(tmp_path), confirm=lambda digest, record: answer, environ={}) == 2
    assert label_reads == []


@pytest.mark.parametrize("tamper", ["predictions", "manifest", "receipt"])
def test_local_tampering_locks(tmp_path, capsys, label_reads, tamper):
    _, message = build_repo(tmp_path)
    if tamper == "predictions":   # predictions changed after the manifest was hashed and posted
        path = tmp_path / "runs" / RUN / "predictions.jsonl"
        path.write_text(path.read_text().replace('"p_react":0.2', '"p_react":0.25'))
    elif tamper == "manifest":    # manifest rewritten to match: its sha256 is no longer the posted one
        path = tmp_path / "runs" / RUN / "predictions.jsonl"
        path.write_text(path.read_text().replace('"p_react":0.2', '"p_react":0.25'))
        build_manifest(tmp_path, "runs", "protocol/predictions.manifest.json")
    else:                         # no receipt record for this manifest
        (tmp_path / "protocol" / "posts.jsonl").write_text("")
    assert cli.main(argv(tmp_path), confirm=fake_discord(message), environ={}) == 2
    assert label_reads == []


def test_manual_confirmation_does_not_show_the_digest_first(tmp_path, label_reads):
    record, _ = build_repo(tmp_path)
    prompts = []

    def ask(prompt, answer):
        prompts.append(prompt)
        return answer
    assert cli.main(argv(tmp_path), confirm=cli.manual_confirm(lambda p: ask(p, "f" * 64)), environ={}) == 2
    assert label_reads == []
    assert cli.main(argv(tmp_path, "--verify", "manual"),
                    confirm=cli.manual_confirm(lambda p: ask(p, f"  {record['sha256'].upper()}\n")), environ={}) == 0
    assert len(label_reads) == 1
    assert all(record["sha256"] not in p for p in prompts)


def test_default_discord_fetch_uses_webhook_and_never_prints_it(tmp_path, capsys, monkeypatch, label_reads):
    _, message = build_repo(tmp_path)
    seen = []

    def urlopen(request, timeout):
        seen.append(request.full_url)
        raise urllib.error.URLError(f"cannot reach {SECRET_URL}")
    monkeypatch.setattr(cli.urllib.request, "urlopen", urlopen)
    assert cli.main(argv(tmp_path), environ={cli.WEBHOOK_ENV: SECRET_URL + "?wait=true"}) == 2
    assert seen == [f"{SECRET_URL}/messages/{MESSAGE_ID}"]
    output = capsys.readouterr()
    assert "SYNTHETIC-SECRET-TOKEN" not in output.out + output.err
    assert label_reads == []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda request, timeout: Response(json.dumps(message).encode()))
    assert cli.main(argv(tmp_path), environ={cli.WEBHOOK_ENV: SECRET_URL}) == 0
    assert len(label_reads) == 1


def test_bad_label_line_reports_field_names_only(tmp_path, capsys):
    _, message = build_repo(tmp_path)
    (tmp_path / "fake_labels.jsonl").write_text('{"item_id": "syn-0", "category": "PRIVATE-CATEGORY", "reacted": true}\n')
    assert cli.main(argv(tmp_path), confirm=fake_discord(message), environ={}) == 1
    err = capsys.readouterr().err
    assert "labels line 1 failed Label validation for category" in err
    assert "PRIVATE-CATEGORY" not in err


def test_module_entry_point_help():
    result = subprocess.run([sys.executable, "-m", "kiln.scoring", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--run-dir" in result.stdout and "--labels" in result.stdout and "--receipt" in result.stdout


def test_discord_confirm_ignores_receipt_fields_other_than_message_id():
    digest = "a" * 64
    message = {"id": MESSAGE_ID, "content": f"Kiln predictions manifest sha256 {digest} (commit x)",
               "timestamp": POSTED_AT, "edited_timestamp": None}
    confirm = cli.discord_confirm(lambda message_id: message, environ={},
                                  now=lambda: datetime(2026, 11, 2, tzinfo=timezone.utc))
    assert confirm(digest, {"message_id": MESSAGE_ID, "sha256": "anything"}) is True
    assert confirm(digest, {"message_id": None, "sha256": digest}) is False
    assert confirm("b" * 64, {"message_id": MESSAGE_ID, "sha256": "b" * 64}) is False
