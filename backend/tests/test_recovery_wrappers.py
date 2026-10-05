"""Test wrapper failure/argument boundaries with fake commands, never real services."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def powershell():
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is unavailable")
    return executable


def test_setup_stops_at_a_failed_native_command():
    source = str(REPO / "setup.ps1").replace("'", "''")
    result = subprocess.run([powershell(), "-NoProfile", "-NonInteractive", "-Command",
        "function uv { Write-Output 'fake-uv'; $global:LASTEXITCODE=9 }; "
        "function npm { Write-Output 'unexpected-npm'; $global:LASTEXITCODE=0 }; "
        f"& '{source}'"], capture_output=True, text=True)
    assert result.returncode != 0
    assert result.stdout.count("fake-uv") == 1
    assert "unexpected-npm" not in result.stdout
    assert "Setup complete" not in result.stdout


def test_backup_wrapper_passes_quoted_labels_as_arguments_and_reports_failure():
    source = str(REPO / "backup-db.ps1").replace("'", "''")
    result = subprocess.run([powershell(), "-NoProfile", "-NonInteractive", "-Command",
        "function uv { ConvertTo-Json -InputObject @($args) -Compress; $global:LASTEXITCODE=9 }; "
        f"& '{source}' -Tag 'synthetic''s label'"], capture_output=True, text=True)
    assert result.returncode != 0
    assert json.loads(result.stdout.strip()) == [
        "run", "python", "-m", "app.services.backup", "backup", "--tag=synthetic's label",
    ]
    assert "Backup failed" in result.stderr


def test_bash_wrappers_have_valid_syntax():
    executable = shutil.which("bash")
    if executable is None:
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        if not candidate.exists():
            pytest.skip("Bash is unavailable")
        executable = str(candidate)
    for name in ["backup-db.sh", "restore-db.sh", "setup.sh", "reset-db.sh", "dev.sh"]:
        subprocess.run([executable, "-n", (REPO / name).as_posix()], check=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group runtime check")
def test_dev_cleanup_leaves_an_unrelated_process_running(tmp_path):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is unavailable")
    root = tmp_path / "launcher"
    for name in ["backend", "frontend", "bin"]:
        (root / name).mkdir(parents=True)
    shutil.copy2(REPO / "dev.sh", root / "dev.sh")
    for name in ["uv", "npm"]:
        command = root / "bin" / name
        command.write_text("#!/usr/bin/env bash\n"
            "if [[ ${2:-} == alembic ]]; then exit 0; fi\n"
            "echo ready >> \"$TEST_MARKERS\"\nsleep 60 &\nwait\n", encoding="utf-8")
        command.chmod(0o755)
    env = os.environ | {"TEST_ROOT": str(root), "TEST_MARKERS": str(root / "markers")}
    program = r'''
set -euo pipefail
export PATH="$TEST_ROOT/bin:$PATH"
sleep 60 &
sentinel=$!
launcher=""
trap 'kill "$sentinel" ${launcher:-} 2>/dev/null || true' EXIT
bash "$TEST_ROOT/dev.sh" &
launcher=$!
for attempt in {1..50}; do
  [[ -f "$TEST_MARKERS" && $(wc -l < "$TEST_MARKERS") -ge 2 ]] && break
  sleep 0.05
done
kill -TERM "$launcher"
wait "$launcher" || true
kill -0 "$sentinel"
'''
    result = subprocess.run([bash, "-c", program], env=env, capture_output=True,
        text=True, timeout=15, start_new_session=True)
    assert result.returncode == 0, result.stderr
