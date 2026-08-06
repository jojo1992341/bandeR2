from fastapi import APIRouter
from .auth import router as auth_router
from .media import router as media_router
from .rythmo import router as rythmo_router
from .export import router as export_router
from .projects import router as projects_router
from .typographic_profiles import router as profiles_router
from .ebu_stl import router as ebu_router
from .collaboration import router as collab_router
from .validation import router as validation_router
from .mfa import router as mfa_router
from .feature_flags import router as flags_router
from .dashboard import router as dashboard_router
from .search import router as search_router
from .feedback import router as feedback_router
from .sso import router as sso_router
from .teams import router as teams_router
from .public_api import router as public_router
from .mobile import router as mobile_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(media_router)
router.include_router(rythmo_router)
router.include_router(export_router)
router.include_router(projects_router)
router.include_router(profiles_router)
router.include_router(ebu_router)
router.include_router(collab_router)
router.include_router(validation_router)
router.include_router(mfa_router)
router.include_router(flags_router)
router.include_router(dashboard_router)
router.include_router(search_router)
router.include_router(feedback_router)
router.include_router(sso_router)
router.include_router(teams_router)
router.include_router(public_router)
router.include_router(mobile_router)
