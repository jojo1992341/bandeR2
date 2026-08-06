from fastapi import APIRouter
from .auth import router as auth_router
from .media import router as media_router
from .rythmo import router as rythmo_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(media_router)
router.include_router(rythmo_router)
