"""
Main router aggregator
Import all route modules and combine them here
"""
from fastapi import APIRouter
from .auth import router as auth_router
from .rides import router as rides_router
from .drivers import router as drivers_router
from .admin import router as admin_router
from .corporate_accounts import router as corporate_accounts_router

# Create the main API router
api_router = APIRouter()

# Include all sub-routers
api_router.include_router(auth_router)
api_router.include_router(rides_router)
api_router.include_router(drivers_router)
api_router.include_router(admin_router)
api_router.include_router(corporate_accounts_router)

# Health check and root endpoints
@api_router.get("/")
async def root():
    return {"message": "Spinr API", "version": "1.0.0"}

@api_router.get("/health")
async def health_check():
    from datetime import datetime, timezone
    try:
        from supabase_client import supabase  # type: ignore
        if supabase is None:
            raise RuntimeError("Supabase client not initialised")
        supabase.table('users').select('id').limit(1).execute()
        return {"status": "healthy", "database": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "database": "error", "error": str(e)})
