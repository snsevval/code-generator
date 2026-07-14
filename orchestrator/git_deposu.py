"""Faz 5 — Workspace git entegrasyonu.

Her tamamlanan görevden sonra workspace'teki değişiklikler otomatik commit'lenir:
hangi ajanın/görevin neyi değiştirdiği tarihçede görünür ve kötü bir adım
`git revert/checkout` ile geri alınabilir.

- Workspace'te repo yoksa `git init` ile oluşturulur (üst repo'dan bağımsız,
  iç içe bir depo; workspace zaten üst reponun gitignore'unda).
- Commit kimliği yapılandırılmamışsa depoya yerel bir kimlik yazılır.
- `FCC_GIT=0` ortam değişkeni entegrasyonu kapatır; git kurulu değilse
  sessizce devre dışı kalır.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_ZAMAN_ASIMI = 30.0


class GitDeposu:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.workspace), *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_ZAMAN_ASIMI,
        )

    @classmethod
    def olustur(cls, workspace: Path | str) -> "GitDeposu | None":
        """Kullanılabilirse hazır bir depo döndürür; değilse None (sessiz)."""
        if os.environ.get("FCC_GIT", "1").lower() in ("0", "false", "no"):
            return None
        depo = cls(Path(workspace).resolve())
        try:
            if depo._git("rev-parse", "--is-inside-work-tree").returncode != 0:
                if depo._git("init").returncode != 0:
                    return None
            # Commit kimliği yoksa yerel (yalnızca bu depoya özel) kimlik yaz
            if not depo._git("config", "user.email").stdout.strip():
                depo._git("config", "user.name", "Orkestrator")
                depo._git("config", "user.email", "orkestrator@localhost")
            return depo
        except (OSError, subprocess.TimeoutExpired):
            return None  # git kurulu değil / erişilemiyor

    def commit(self, mesaj: str) -> bool:
        """Değişiklik varsa commit'ler; commit oluştuysa True döner."""
        try:
            self._git("add", "-A")
            # Sahnede değişiklik yoksa commit atma
            if self._git("diff", "--cached", "--quiet").returncode == 0:
                return False
            return self._git("commit", "-m", mesaj).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
