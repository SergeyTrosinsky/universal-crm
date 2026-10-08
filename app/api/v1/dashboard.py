from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import DASHBOARD_READ
from app.db.session import get_db
from app.models import User
from app.schemas.dashboard import DashboardOut
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def get_dashboard(
    period: str = Query(dashboard_service.DEFAULT_PERIOD, description="7 | 30 | 90 | 365 | all"),
    db: Session = Depends(get_db),
    viewer: User = Depends(require_permission(DASHBOARD_READ)),
) -> dict:
    """Блоки clients / deals / tasks приходят только если у роли есть право на соответствующий раздел."""
    return dashboard_service.build_dashboard(db, viewer, period)
