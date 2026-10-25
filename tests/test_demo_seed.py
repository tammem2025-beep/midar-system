from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_demo_seed_creates_isolated_disconnected_sample_data_and_refuses_overwrite(tmp_path: Path):
    demo_dir = tmp_path / "isolated-m-demo"
    original_database = tmp_path / "original-work.db"
    original_database.write_bytes(b"do-not-touch-original-data")
    original_before = original_database.read_bytes()

    created = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "seed_demo.py"),
            "--data-dir",
            str(demo_dir),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert created.returncode == 0, created.stderr
    assert "All sample records are fictional" in created.stdout
    assert "Demo login: demo-owner@example.com" in created.stdout

    database = demo_dir / "m-demo.db"
    env_file = demo_dir / ".env"
    assert database.is_file() and env_file.is_file()
    env_text = env_file.read_text(encoding="utf-8")
    secret = next(line.partition("=")[2] for line in env_text.splitlines() if line.startswith("SECRET_KEY="))
    assert len(secret) >= 32
    assert "REPLACE_WITH_GENERATED_SECRET" not in env_text

    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 5
        assert db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM social_accounts WHERE connection_status != 'disconnected'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM messages WHERE delivery_status != 'local_only'").fetchone()[0] == 0
        demo_audit = db.execute("SELECT details FROM audit_logs WHERE action='demo.seeded'").fetchone()[0]
        assert json.loads(demo_audit) == {"sample_data": True, "external_actions": False}

    original_before_second_run = original_database.read_bytes()
    second_run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "seed_demo.py"),
            "--data-dir",
            str(demo_dir),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert second_run.returncode == 2
    assert "Refusing to overwrite demo data" in second_run.stderr
    assert original_database.read_bytes() == original_before
    assert original_database.read_bytes() == original_before_second_run
