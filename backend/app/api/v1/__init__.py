from fastapi import APIRouter

from app.api.v1 import (
    admin_catalogue,
    admin_content,
    admin_masters,
    admin_ops,
    admin_users,
    auth,
    client,
    health,
    master,
    master_work,
    public,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(auth.me_router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_catalogue.router)
api_router.include_router(admin_masters.router)
api_router.include_router(master.router)
api_router.include_router(public.router)
api_router.include_router(public.media_router)
api_router.include_router(public.webhook_router)
api_router.include_router(admin_content.router)
api_router.include_router(admin_ops.router)
api_router.include_router(client.router)
api_router.include_router(client.notifications_router)
api_router.include_router(master_work.router)
