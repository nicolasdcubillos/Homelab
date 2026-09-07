"""API JSON versionada del dashboard."""

from __future__ import annotations

from fastapi import APIRouter

from . import routes_admin, routes_auth, routes_market_regime, routes_me, routes_trading

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(routes_auth.router)
api_router.include_router(routes_me.router)
api_router.include_router(routes_admin.router)
api_router.include_router(routes_trading.router)
api_router.include_router(routes_market_regime.router)

__all__ = ["api_router"]
