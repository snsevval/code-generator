"""CLI girişi: uv run python -m orchestrator "görev metni"

Örnek:
    uv run python -m orchestrator "fibonacci hesaplayan bir CLI aracı yaz"
    uv run python -m orchestrator --devam "..."   # kesilen görevi sürdür
    uv run python -m orchestrator --docker "..."  # run_shell Docker sandbox'ta
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.loop import Orkestrator
from orchestrator.proje import ProjeOrkestratoru
from orchestrator.tool_executor import DockerShellRunner, ToolExecutor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="orchestrator", description="Agentic kod üretim döngüsü"
    )
    parser.add_argument("gorev", help="Yapılacak görevin açıklaması")
    parser.add_argument(
        "--workspace", default="workspace", help="Çalışma alanı klasörü (varsayılan: workspace)"
    )
    parser.add_argument(
        "--docker", action="store_true", help="run_shell komutlarını Docker sandbox'ta koş"
    )
    parser.add_argument(
        "--devam", action="store_true", help="Kayıtlı state'ten kaldığı yerden sürdür"
    )
    parser.add_argument(
        "--proje",
        action="store_true",
        help="Büyük hedef modu: hedefi alt görevlere bölüp zincir halinde koşar",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    runner = DockerShellRunner(workspace) if args.docker else None
    executor = ToolExecutor(workspace, shell_runner=runner)
    orkestrator = Orkestrator(workspace, executor=executor)

    if args.proje:
        proje = ProjeOrkestratoru(workspace, orkestrator=orkestrator)
        pstate = proje.hedef_calistir(args.gorev, devam=args.devam)
        print("\n" + "=" * 60)
        print(f"HEDEF: {pstate.hedef}")
        for alt in pstate.alt_gorevler:
            isaret = {"basarili": "[x]", "basarisiz": "[!]"}.get(alt["durum"], "[ ]")
            print(f"  {isaret} {alt['id']}. {alt['gorev']}")
        print("=" * 60)
        return 0 if all(a["durum"] == "basarili" for a in pstate.alt_gorevler) else 1

    state = orkestrator.gorev_calistir(args.gorev, devam=args.devam)

    print("\n" + "=" * 60)
    print(f"GÖREV: {state.gorev}")
    print(f"Doğrulama geçti mi: {state.ciktilar.get('dogrulama_gecti')}")
    print(f"Debug turu: {state.debug_turu}")
    print("\n--- Reviewer raporu ---\n")
    print(state.ciktilar.get("reviewer", "(yok)"))
    print("=" * 60)
    return 0 if state.ciktilar.get("dogrulama_gecti") == "True" else 1


if __name__ == "__main__":
    sys.exit(main())
