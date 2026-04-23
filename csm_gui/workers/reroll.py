"""QThread wrapper around csm_core.assembler.reroll.reroll_pick."""
from __future__ import annotations
import random
from PyQt6.QtCore import QThread, pyqtSignal
from csm_core.assembler.plan import AssemblyPlan
from csm_core.assembler.reroll import reroll_pick, NoCandidatesError
from csm_core.template.schema import Template
from csm_core.vault.scanner import VaultIndex


class RerollWorker(QThread):
    finished = pyqtSignal(object)  # AssemblyPlan
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        plan: AssemblyPlan,
        block_id: str,
        pick_index: int,
        template: Template,
        vault_index: VaultIndex,
        rng: random.Random | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._plan = plan
        self._block_id = block_id
        self._pick_index = pick_index
        self._template = template
        self._vault_index = vault_index
        self._rng = rng

    def run(self) -> None:
        try:
            new_plan = reroll_pick(
                self._plan, self._block_id, self._pick_index,
                self._template, self._vault_index, rng=self._rng,
            )
        except NoCandidatesError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — boundary, surface to UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(new_plan)
