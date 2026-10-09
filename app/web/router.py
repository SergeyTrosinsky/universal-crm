from fastapi import APIRouter, Depends

from app.core import csrf
from app.web.pages import (
    auth, clients, dashboard, deal_templates, deals, fields, general, import_export, profile, settings, statuses,
    tasks,
)

web_router = APIRouter(include_in_schema=False, dependencies=[Depends(csrf.verify_web)])
web_router.include_router(auth.router)
web_router.include_router(profile.router)
web_router.include_router(import_export.router)
web_router.include_router(clients.router)
web_router.include_router(deals.router)
web_router.include_router(fields.router)
web_router.include_router(deal_templates.router)
web_router.include_router(statuses.router)
web_router.include_router(settings.router)
web_router.include_router(tasks.router)
web_router.include_router(dashboard.router)
web_router.include_router(general.router)
