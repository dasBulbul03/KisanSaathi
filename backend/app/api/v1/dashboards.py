"""Role-aware dashboard endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import (
    CurrentAdmin,
    CurrentBuyer,
    CurrentSeller,
    CurrentUser,
    DbSession,
)
from app.schemas.ai import AdminDashboard, BuyerDashboard, FarmerDashboard
from app.services.dashboard_service import DashboardService, role_dashboard

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

Dashboard = FarmerDashboard | BuyerDashboard | AdminDashboard


@router.get("/me", response_model=Dashboard, summary="Dashboard for the caller's role")
def my_dashboard(session: DbSession, user: CurrentUser) -> Dashboard:
    """The dashboard matching the caller's role, so a client can ask for one URL.

    Buyers get requirements and offers, sellers get lots, offers and price cards,
    and administrators get platform-wide trade and pending-action counts.
    """
    return role_dashboard(session, user)


@router.get("/farmer", response_model=FarmerDashboard, summary="Farmer dashboard")
def farmer_dashboard(session: DbSession, user: CurrentSeller) -> FarmerDashboard:
    """The seller view, restricted to farmers and FPOs.

    Use this when the client already knows the caller is a seller and wants the
    schema to be non-optional in its generated types.
    """
    return DashboardService(session).farmer_dashboard(user)


@router.get("/buyer", response_model=BuyerDashboard, summary="Buyer dashboard")
def buyer_dashboard(session: DbSession, user: CurrentBuyer) -> BuyerDashboard:
    """The buyer view: open requirements, submitted offers and payables."""
    return DashboardService(session).buyer_dashboard(user)


@router.get("/admin", response_model=AdminDashboard, summary="Administrator dashboard")
def admin_dashboard(session: DbSession, user: CurrentAdmin) -> AdminDashboard:
    """Platform-wide trade value, demand pressure and outstanding work queues."""
    return DashboardService(session).admin_dashboard()


__all__ = ["router"]
