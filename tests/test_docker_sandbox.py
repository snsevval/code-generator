"""Faz 1 — Docker sandbox entegrasyon testleri.

Docker daemon çalışmıyorsa testler atlanır (birim testlerinden bağımsız).

Çalıştırma:
    uv run pytest tests/test_docker_sandbox.py -v
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from orchestrator.tool_executor import DockerShellRunner, ToolExecutor


def _docker_calisiyor() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        sonuc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return sonuc.returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_calisiyor(), reason="Docker daemon çalışmıyor"
)


@pytest.fixture
def executor(tmp_path):
    return ToolExecutor(tmp_path, shell_runner=DockerShellRunner(tmp_path))


def test_sandbox_komut_calistirir(executor):
    sonuc = executor.run_shell("echo sandbox-selam")
    assert sonuc.ok, sonuc.cikti
    assert "sandbox-selam" in sonuc.cikti


def test_sandbox_workspace_baglanir(executor):
    # Dışarıda (host'ta) yazılan dosya konteynerden okunabilmeli
    executor.write_file("veri.txt", "hosttan-icerik\n")
    sonuc = executor.run_shell("cat veri.txt")
    assert sonuc.ok, sonuc.cikti
    assert "hosttan-icerik" in sonuc.cikti


def test_sandbox_yazma_hosta_yansir(executor, tmp_path):
    # Konteynerde yazılan dosya host'tan görülebilmeli
    sonuc = executor.run_shell("echo konteynerden > cikti.txt")
    assert sonuc.ok, sonuc.cikti
    assert (tmp_path / "cikti.txt").read_text().strip() == "konteynerden"


def test_sandbox_calisma_dizini_workspace(executor):
    sonuc = executor.run_shell("pwd")
    assert sonuc.ok, sonuc.cikti
    assert "/workspace" in sonuc.cikti


def test_sandbox_aga_kapali(executor):
    # --network none: dışarı istek atılamamalı
    sonuc = executor.run_shell(
        'python -c "import urllib.request; urllib.request.urlopen(\'https://example.com\', timeout=5)"',
        timeout=60,
    )
    assert not sonuc.ok
    assert "çıkış kodu: 0" not in sonuc.cikti


def test_sandbox_zaman_asimi(executor):
    sonuc = executor.run_shell("sleep 30", timeout=5)
    assert not sonuc.ok
    assert "zaman aşımı" in sonuc.cikti
