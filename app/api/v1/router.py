from fastapi import APIRouter, Depends

from app.core import csrf
from app.api.v1 import auth, clients, custom_fields, dashboard, deal_templates, deals, roles, settings, statuses, tasks, users

api_router = APIRouter(dependencies=[Depends(csrf.verify_api)])
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(custom_fields.router)
api_router.include_router(deal_templates.router)
api_router.include_router(statuses.router)
api_router.include_router(clients.router)
api_router.include_router(deals.router)
api_router.include_router(tasks.router)
api_router.include_router(dashboard.router)
api_router.include_router(settings.router)
