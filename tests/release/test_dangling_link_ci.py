"""Contract tests for the shipped-document link gate."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
EXPORT_SCRIPT = ROOT / "tools" / "release" / "export_public.sh"
LINK_STEP_NAME = "Every internal link in a shipped doc must resolve"


def _link_step_command() -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    step_index = next(i for i, line in enumerate(lines) if LINK_STEP_NAME in line)
    run_index = next(
        i for i in range(step_index + 1, len(lines)) if lines[i].lstrip().startswith("run:")
    )
    run_line = lines[run_index]
    value = run_line.split("run:", 1)[1].strip()
    if value != "|":
        return value

    indentation = len(run_line) - len(run_line.lstrip())
    command_lines: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indentation:
            break
        command_lines.append(line[indentation + 2 :])
    return "\n".join(command_lines)


def _fake_python(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "python-calls.txt"
    python = fake_bin / "python"
    python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\nexit \"${FAKE_PYTHON_EXIT:-0}\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return fake_bin, call_log


@pytest.mark.parametrize(
    ("source_checkout", "expected_arguments"),
    [
        (True, "scripts/check-dangling-links.py"),
        (False, "scripts/check-dangling-links.py ."),
    ],
)
def test_link_step_checks_the_export_in_source_and_checkout_in_public(
    tmp_path: Path, source_checkout: bool, expected_arguments: str
) -> None:
    fake_bin, call_log = _fake_python(tmp_path)
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "tools" / "release").mkdir(parents=True)
    if source_checkout:
        (checkout / "tools" / "release" / "patch_staging.py").touch()

    env = os.environ.copy()
    env.update(PATH=f"{fake_bin}:/usr/bin:/bin", CALL_LOG=str(call_log))
    result = subprocess.run(
        ["bash", "-c", _link_step_command()], cwd=checkout, env=env, text=True
    )

    assert result.returncode == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == [expected_arguments]


def test_link_step_propagates_checker_failure(tmp_path: Path) -> None:
    fake_bin, call_log = _fake_python(tmp_path)
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "tools" / "release").mkdir(parents=True)
    (checkout / "tools" / "release" / "patch_staging.py").touch()

    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}:/usr/bin:/bin",
        CALL_LOG=str(call_log),
        FAKE_PYTHON_EXIT="7",
    )
    result = subprocess.run(
        ["bash", "-c", _link_step_command()], cwd=checkout, env=env, text=True
    )

    assert result.returncode == 7


def test_export_uses_python_from_path_without_a_repo_venv(tmp_path: Path) -> None:
    fake_root = tmp_path / "source"
    release_dir = fake_root / "tools" / "release"
    release_dir.mkdir(parents=True)
    shutil.copy2(EXPORT_SCRIPT, release_dir / "export_public.sh")
    (release_dir / "export_manifest.txt").write_text(
        "README.md\nsrc/database\nEXCLUDE unused\n", encoding="utf-8"
    )
    (release_dir / "mapping_seeds.public.py").write_text("# public\n", encoding="utf-8")
    (release_dir / "patch_staging.py").write_text("# fake\n", encoding="utf-8")
    (release_dir / "leak_gate.py").write_text("# fake\n", encoding="utf-8")
    (fake_root / "src" / "database").mkdir(parents=True)
    (fake_root / "src" / "database" / "mapping_seeds.py").write_text(
        "# private\n", encoding="utf-8"
    )
    (fake_root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=fake_root, check=True)

    fake_bin, call_log = _fake_python(tmp_path)
    python3 = fake_bin / "python3"
    python3.symlink_to(fake_bin / "python")
    env = os.environ.copy()
    env.update(PATH=f"{fake_bin}:/usr/bin:/bin", CALL_LOG=str(call_log))
    staging = tmp_path / "staging"

    result = subprocess.run(
        ["bash", str(release_dir / "export_public.sh"), str(staging)],
        cwd=fake_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        f"{release_dir / 'patch_staging.py'} {staging}",
        f"{release_dir / 'leak_gate.py'} --paths {staging} --strict",
    ]
