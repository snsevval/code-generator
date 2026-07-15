"""Faz 7 — Tasarım bilgisi enjeksiyonu (ui-ux-pro-max entegrasyonu).

UI görevlerinde, ui-ux-pro-max skill'inin arama scripti çalıştırılıp üretilen
tasarım sistemi (stil, palet, tipografi, kaçınılacaklar) görev metnine eklenir.
Böylece Codegen "aklına esen" renklerle değil, tutarlı bir tasarım sistemine
göre yazar — bilgi katmanı, modelden bağımsız ve belirleyici biçimde taşınır.

Script yoksa/başarısızsa None döner; görev değişmeden akar (zarif bozulma).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

MAX_TASARIM_UZUNLUGU = 2500  # görev bağlamına eklenecek azami karakter
_ZAMAN_ASIMI = 90.0


def _script_yolu() -> Path:
    varsayilan = Path.home() / ".claude" / "skills" / "ui-ux-pro-max" / "scripts" / "search.py"
    return Path(os.environ.get("FCC_TASARIM_SCRIPT", str(varsayilan)))


def _sorgu_uret(gorev: str) -> str:
    """Görev metninden arama sorgusu: ilk cümlenin sade hali + UI vurgusu."""
    ozet = re.sub(r"\s+", " ", gorev).strip()[:120]
    return f"{ozet} web ui"


def tasarim_sistemi(gorev: str) -> str | None:
    """Göreve uygun tasarım sistemini üretir (markdown); üretilemezse None."""
    script = _script_yolu()
    if not script.is_file():
        return None
    try:
        sonuc = subprocess.run(
            [sys.executable, str(script), _sorgu_uret(gorev), "--design-system", "-f", "markdown"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_ZAMAN_ASIMI,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if sonuc.returncode != 0 or not sonuc.stdout.strip():
        return None
    cikti = sonuc.stdout.strip()
    if len(cikti) > MAX_TASARIM_UZUNLUGU:
        cikti = cikti[:MAX_TASARIM_UZUNLUGU] + "\n... [kırpıldı]"
    return cikti


def gorevi_zenginlestir(gorev: str) -> str:
    """Görev metnine tasarım sistemini ekler (üretilemezse aynen döner)."""
    sistem = tasarim_sistemi(gorev)
    if not sistem:
        return gorev
    return (
        gorev
        + "\n\nUyulacak tasarım sistemi (renk/tipografi/stil kararlarında buna sadık kal):\n"
        + sistem
    )
