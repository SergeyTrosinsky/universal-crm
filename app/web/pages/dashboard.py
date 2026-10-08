"""Главная со статистикой."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.permissions import DASHBOARD_READ
from app.db.session import get_db
from app.models import User
from app.services import dashboard_service
from app.web.deps import require_web_permission
from app.web.templating import render

router = APIRouter()


def dashboard_page(request: Request, db: Session, user: User):
    period = request.query_params.get("period") or dashboard_service.DEFAULT_PERIOD
    data = dashboard_service.build_dashboard(db, user, period)
    ctx = {
        "d": data,
        "recent": dashboard_service.recent_items(db, user),
        "periods": [(key, label) for key, (label, _) in dashboard_service.PERIODS.items()],
    }
    return render(request, "dashboard/index.html", ctx, user=user)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(DASHBOARD_READ))):
    return dashboard_page(request, db, user)
