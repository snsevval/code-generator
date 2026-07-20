"""Faz 1 — Tool Executor birim testleri.

Çalıştırma:
    uv run pytest tests/test_tool_executor.py -v
"""

from __future__ import annotations

import sys

import pytest

from orchestrator.tool_executor import ToolExecutor

PYTHON = f'"{sys.executable}"'  # yol boşluk içerebilir, tırnakla


@pytest.fixture
def executor(tmp_path):
    return ToolExecutor(tmp_path)


# --- read_file / write_file ---


def test_yaz_ve_oku(executor):
    yazma = executor.write_file("src/main.py", "print('merhaba')\n")
    assert yazma.ok
    assert "oluşturuldu" in yazma.cikti

    okuma = executor.read_file("src/main.py")
    assert okuma.ok
    assert okuma.cikti == "print('merhaba')\n"


def test_yeni_dosya_diffi(executor):
    sonuc = executor.write_file("a.txt", "satir1\n")
    assert sonuc.ok
    assert "/dev/null" in sonuc.cikti  # yeni dosya işareti
    assert "+satir1" in sonuc.cikti


def test_guncelleme_diffi(executor):
    executor.write_file("a.txt", "eski\n")
    sonuc = executor.write_file("a.txt", "yeni\n")
    assert sonuc.ok
    assert "güncellendi" in sonuc.cikti
    assert "-eski" in sonuc.cikti
    assert "+yeni" in sonuc.cikti


def test_olmayan_dosya_okuma(executor):
    sonuc = executor.read_file("yok.txt")
    assert not sonuc.ok
    assert "bulunamadı" in sonuc.cikti


def test_ic_ice_klasor_olusturma(executor):
    sonuc = executor.write_file("a/b/c/derin.txt", "icerik")
    assert sonuc.ok
    assert executor.read_file("a/b/c/derin.txt").cikti == "icerik"


def test_klasore_yazma_reddi(executor):
    executor.write_file("klasor/dosya.txt", "x")
    sonuc = executor.write_file("klasor", "olmaz")
    assert not sonuc.ok


# --- list_files ---


def test_list_files_alt_klasorlerle(executor):
    executor.write_file("a.txt", "x")
    executor.write_file("alt/b.py", "yy")
    sonuc = executor.list_files()
    assert sonuc.ok
    assert "a.txt (1 B)" in sonuc.cikti
    assert "alt/b.py (2 B)" in sonuc.cikti


def test_list_files_gizli_klasorleri_atlar(executor, tmp_path):
    executor.write_file("gercek.txt", "x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "izsiz.pyc").write_text("z")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("z")
    sonuc = executor.list_files()
    assert "gercek.txt" in sonuc.cikti
    assert "izsiz" not in sonuc.cikti
    assert ".git" not in sonuc.cikti


def test_list_files_bos_klasor(executor):
    assert executor.list_files().cikti == "(klasör boş)"


def test_list_files_disari_cikamaz(executor):
    sonuc = executor.list_files("..")
    assert not sonuc.ok
    assert "HATA" in sonuc.cikti


def test_dosya_var_mi(executor):
    assert not executor.dosya_var_mi("yok.txt")
    executor.write_file("var.txt", "x")
    assert executor.dosya_var_mi("var.txt")
    assert not executor.dosya_var_mi("../disarida.txt")  # kaçış → False


# --- edit_file ---


def test_edit_file_degistirir(executor):
    executor.write_file("a.py", "x = 1\ny = 2\nz = 3\n")
    sonuc = executor.edit_file("a.py", "y = 2", "y = 20")
    assert sonuc.ok
    assert "düzenlendi" in sonuc.cikti
    assert executor.read_file("a.py").cikti == "x = 1\ny = 20\nz = 3\n"


def test_edit_file_bulunamayan_metin(executor):
    executor.write_file("a.py", "x = 1")
    sonuc = executor.edit_file("a.py", "yok_boyle", "yeni")
    assert not sonuc.ok
    assert "bulunamadı" in sonuc.cikti


def test_edit_file_coklu_eslesme_reddedilir(executor):
    executor.write_file("a.py", "n = 0\nn = 0\n")
    sonuc = executor.edit_file("a.py", "n = 0", "n = 1")
    assert not sonuc.ok
    assert "2 kez" in sonuc.cikti
    # dosya değişmemiş olmalı
    assert executor.read_file("a.py").cikti == "n = 0\nn = 0\n"


def test_edit_file_diff_uretir(executor):
    executor.write_file("a.txt", "eski satır\n")
    sonuc = executor.edit_file("a.txt", "eski satır", "yeni satır")
    assert "-eski satır" in sonuc.cikti
    assert "+yeni satır" in sonuc.cikti


def test_edit_file_olmayan_dosya(executor):
    assert not executor.edit_file("yok.txt", "a", "b").ok


def test_edit_file_disari_cikamaz(executor):
    sonuc = executor.edit_file("../dis.txt", "a", "b")
    assert not sonuc.ok
    assert "HATA" in sonuc.cikti


def test_dispatcher_edit_file(executor):
    executor.write_file("d.txt", "merhaba dunya")
    sonuc = executor.calistir("edit_file", {"path": "d.txt", "eski_metin": "dunya", "yeni_metin": "sevval"})
    assert sonuc.ok
    assert executor.read_file("d.txt").cikti == "merhaba sevval"


# --- Path doğrulama ---


@pytest.mark.parametrize(
    "kotu_path",
    [
        "../disari.txt",
        "..\\disari.txt",
        "a/../../disari.txt",
        "C:\\Windows\\system32\\evil.txt",
        "/etc/passwd",
        "",
        "   ",
    ],
)
def test_workspace_disina_cikis_engellenir(executor, kotu_path):
    okuma = executor.read_file(kotu_path)
    yazma = executor.write_file(kotu_path, "zarar")
    assert not okuma.ok
    assert not yazma.ok
    assert "HATA" in yazma.cikti


def test_workspace_disi_dosya_olusmadi(tmp_path):
    executor = ToolExecutor(tmp_path)
    executor.write_file("../kacak.txt", "zarar")
    assert not (tmp_path.parent / "kacak.txt").exists()


@pytest.mark.parametrize(
    "bozuk_path",
    [
        "backend.py>\n<parameter=content>",  # canlıda görülen: araç etiketi path'e sızdı
        "backend.py\n",
        "dosya<parameter>.py",
        'a"b.py',
        "x|y.py",
    ],
)
def test_write_file_gecersiz_karakterli_path_cokmez(executor, bozuk_path):
    # Model araç çağrısı sözdizimini path'e sızdırınca (OSError Errno 22) TÜM görev
    # çöküyordu; artık dostça hata dönüp model tekrar denesin — istisna fırlamamalı
    sonuc = executor.write_file(bozuk_path, "içerik")
    assert not sonuc.ok
    assert "HATA" in sonuc.cikti


# --- run_shell ---


def test_shell_stdout(executor):
    sonuc = executor.run_shell(f"{PYTHON} -c \"print('selam')\"")
    assert sonuc.ok
    assert "çıkış kodu: 0" in sonuc.cikti
    assert "selam" in sonuc.cikti


def test_shell_sifir_olmayan_cikis_kodu(executor):
    sonuc = executor.run_shell(f'{PYTHON} -c "import sys; sys.exit(3)"')
    assert not sonuc.ok
    assert "çıkış kodu: 3" in sonuc.cikti


def test_shell_stderr_yakalanir(executor):
    sonuc = executor.run_shell(
        f"{PYTHON} -c \"import sys; print('uyari', file=sys.stderr)\""
    )
    assert "stderr" in sonuc.cikti
    assert "uyari" in sonuc.cikti


def test_shell_zaman_asimi(executor):
    sonuc = executor.run_shell(f'{PYTHON} -c "import time; time.sleep(10)"', timeout=1)
    assert not sonuc.ok
    assert "zaman aşımı" in sonuc.cikti


def test_shell_workspace_kokunde_calisir(executor, tmp_path):
    sonuc = executor.run_shell(f'{PYTHON} -c "import os; print(os.getcwd())"')
    assert sonuc.ok
    assert str(tmp_path).lower() in sonuc.cikti.lower()


def test_shell_bos_komut(executor):
    assert not executor.run_shell("").ok


@pytest.mark.parametrize(
    "komut",
    [
        "start /b uvicorn backend:app --port 8123",
        "START /B python sunucu.py",
        "nohup python sunucu.py",
        "python -m http.server 8000 &",
    ],
)
def test_shell_arka_plan_baslatici_reddedilir(executor, komut):
    # Torun süreç pipe'ı kilitler (canlıda görev dondu); start_server'a yönlendirilmeli
    sonuc = executor.run_shell(komut)
    assert not sonuc.ok
    assert "start_server" in sonuc.cikti


def test_shell_ve_zinciri_serbest(executor):
    # && zinciri arka plan başlatıcı değildir, engellenmemeli
    sonuc = executor.run_shell('python -c "print(1)" && python -c "print(2)"')
    assert sonuc.ok, sonuc.cikti


@pytest.mark.parametrize(
    "komut",
    [
        "pip uninstall -y pytest-docker",
        "pip install fastapi uvicorn",
        "python -m pytest test_x.py -p no:docker",
        "pytest --disable-plugin docker",
        "set DOCKER_HOST= && pytest test_x.py",
        "net start com.docker.service",
    ],
)
def test_shell_ortam_kurcalama_reddedilir(executor, komut):
    # Model 'docker sorunu' halüsinasyonuyla ortamı kurcalamaya kalkıyor (canlıda 35 tur);
    # paket/eklenti/docker-env komutları mekanik reddedilir, kod düzeltmeye yönlendirilir
    sonuc = executor.run_shell(komut)
    assert not sonuc.ok
    assert "KODDA" in sonuc.cikti


@pytest.mark.parametrize(
    "komut",
    [
        "winget install LLVM.LLVM -e --accept-source-agreements",
        "winget install --id=MSYS2.MSYS2",
        "choco install mingw",
        "scoop install gcc",
        "pacman -Sy mingw-w64-x86_64-toolchain --noconfirm",
        "apt-get install g++",
        "npm install -g typescript",
        "brew install gcc",
    ],
)
def test_shell_paket_kurulumu_reddedilir(executor, komut):
    # Canlıda: derleyici bulamayan ajan winget ile LLVM/MSYS2 kurmaya kalktı (izinsiz
    # sınır aşımı). Sistem yazılımı kurulumu mekanik reddedilir; kullanıcıya bırakılır.
    sonuc = executor.run_shell(komut)
    assert not sonuc.ok
    assert "KURMA yasak" in sonuc.cikti or "kuramazsın" in sonuc.cikti


def test_shell_derleme_komutu_engellenmez(executor):
    # Guard yalnız KURULUMU engeller; derleme/çalıştırma komutları serbest kalmalı
    sonuc = executor.run_shell(f'{PYTHON} -c "print(\'g++ main.cpp -o main.exe gibi\')"')
    assert sonuc.ok


def test_shell_pytest_normal_calisir(executor):
    # Guard normal pytest'i engellememeli (yalnız kurcalama kalıplarını)
    sonuc = executor.run_shell(f'{PYTHON} -c "print(\'pytest -q gibi\')"')
    assert sonuc.ok


def test_start_server_port_eksik_ornekli_hata(executor):
    sonuc = executor.calistir("start_server", {"command": "uvicorn backend:app --port 8123"})
    assert not sonuc.ok
    assert "port" in sonuc.cikti
    assert '"port": 8123' in sonuc.cikti  # birebir kopyalanabilir örnek
    assert "Komutu değiştirme" in sonuc.cikti  # kurcalama davranışını kessin


def test_shell_cok_satirli_komut_reddedilir(executor):
    # Windows cmd çok satırlı komutu sessizce bozuyor; mekanik olarak reddedilmeli
    sonuc = executor.run_shell('python -c "\nimport os\nprint(1)\n"')
    assert not sonuc.ok
    assert "çok satırlı" in sonuc.cikti
    assert "write_file" in sonuc.cikti  # modele sağlam yol tarif edilmeli


# --- Dispatcher ---


def test_dispatcher_gecerli_arac(executor):
    sonuc = executor.calistir("write_file", {"path": "d.txt", "content": "x"})
    assert sonuc.ok
    assert executor.calistir("read_file", {"path": "d.txt"}).cikti == "x"


def test_dispatcher_bilinmeyen_arac(executor):
    sonuc = executor.calistir("format_disk", {})
    assert not sonuc.ok
    assert "bilinmeyen araç" in sonuc.cikti


def test_dispatcher_eksik_parametre(executor):
    sonuc = executor.calistir("read_file", {})
    assert not sonuc.ok
