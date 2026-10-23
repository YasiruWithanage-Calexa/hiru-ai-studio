"""The repositories for this request. One Supabase client per process, created in the lifespan."""
from __future__ import annotations

from fastapi import Request

from api.repositories import Repos


def get_repos(request: Request) -> Repos:
    return request.app.state.repos
