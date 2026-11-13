"""A shot's Generate Video card in one request (plan/2026-11-13d phase 4, F11).

Selecting a shot read `/render-plans` and `/handoff`, each of which loaded the whole scene for the same shot. This loads
it once and answers both with the same builders, so each half equals its own route's answer
(`tests/api/test_shot_panel.py`). The two routes stay: the card reads one of them again when only that half changed.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from api.routers import handoff, renders
from api.routers.production import load_shot
from api.routers.renders import CanView, ReposDep, SettingsDep

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["panel"])


class ShotPanel(BaseModel):
    plans: renders.PlanPair  # = GET .../shots/{id}/render-plans
    handoff: handoff.HandoffView  # = GET .../shots/{id}/handoff


@router.get("/shots/{shot_id}/panel", response_model=ShotPanel)
async def get_panel(production_id: UUID, shot_id: UUID, access: CanView, repos: ReposDep, settings: SettingsDep,
                    assembler: handoff.AssemblerDep) -> ShotPanel:
    ld, st = await load_shot(repos, access, shot_id)
    plans = await renders.plans_for(repos, settings, ld, st)
    return ShotPanel(plans=plans, handoff=await handoff.view_of(repos, ld, st, assembler))
