import os
import jwt
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth as firebase_auth
from loguru import logger  # imported first — used at module load time below

try:
    from .db import db
except ImportError:
    from db import db

# ---------------------------------------------------------------------------
# Security Configuration
# ---------------------------------------------------------------------------
_env = os.environ.get('ENV', 'development')

JWT_SECRET = os.environ.get('JWT_SECRET', '')
if not JWT_SECRET:
    if _env == 'production':
        raise RuntimeError(
            "FATAL: JWT_SECRET environment variable is not set. "
            "The server will not start without a strong secret in production. "
            "Set JWT_SECRET to a random string of at least 32 characters."
        )
    # Development-only fallback — the guard above ensures this never runs in production
    JWT_SECRET = 'spinr-dev-secret-key-NOT-FOR-PRODUCTION'
elif _env == 'production' and len(JWT_SECRET) < 32:
    raise RuntimeError(
        f"FATAL: JWT_SECRET is too short ({len(JWT_SECRET)} chars). "
        "Minimum 32 characters required in production."
    )

JWT_ALGORITHM = 'HS256'
OTP_EXPIRY_MINUTES = 5

security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def generate_otp() -> str:
    """Generate a cryptographically random 6-digit OTP."""
    return ''.join(random.choices(string.digits, k=6))


def create_jwt_token(user_id: str, phone: str, session_id: str = None) -> str:
    payload = {
        'user_id': user_id,
        'phone': phone,
        'exp': datetime.utcnow() + timedelta(days=30)
    }
    if session_id:
        payload['session_id'] = session_id

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    # Do NOT log the JWT secret or any portion of it
    logger.info(f"JWT token created for user_id={user_id}, session_id={session_id}")
    return token


def verify_jwt_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail='Token has expired')
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail='Invalid token')


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Resolve the current user using Firebase ID token (preferred) or fallback to legacy JWT."""
    if not credentials:
        raise HTTPException(status_code=401, detail='No authorization token provided')
    token = credentials.credentials

    # First, try Firebase ID token
    try:
        try:
            payload = firebase_auth.verify_id_token(token)
        except Exception:
            payload = None

        if payload:
            uid = payload.get('uid') or payload.get('user_id')
            user = await db.users.find_one({'id': uid})
            if not user:
                phone = payload.get('phone_number')
                if phone:
                    user = await db.users.find_one({'phone': phone})
                if not user:
                    new_user = {
                        'id': uid,
                        'phone': phone or '',
                        'role': 'rider',
                        'created_at': datetime.utcnow(),
                        'profile_complete': False
                    }
                    await db.users.insert_one(new_user)
                    user = new_user

            if user:
                driver = await db.drivers.find_one({'user_id': user['id']})
                user['is_driver'] = True if driver else False
            return user
    except HTTPException:
        # fall through to try legacy JWT
        pass

    # Fallback: legacy JWT validation
    try:
        payload = verify_jwt_token(token)
    except Exception as e:
        # Do NOT log the token value or the secret — only log that verification failed
        logger.warning("JWT verification failed — check JWT_SECRET env var is consistent across deployments")
        raise HTTPException(status_code=401, detail=f'Invalid token: {str(e)}')

    user = None
    try:
        user = await db.users.find_one({'id': payload['user_id']})
    except Exception as e:
        logger.warning(f'Could not look up user from DB: {e}')

    if user:
        # Enforce single-device login: check if the session_id matches the one in DB
        token_session = payload.get('session_id')
        db_session = user.get('current_session_id')
        if db_session and token_session != db_session:
            logger.info(f"Session mismatch for user_id={user.get('id')} — device change or forced re-login")
            raise HTTPException(status_code=401, detail='Session expired. Logged in from another device.')
        # If the JWT carries a role claim (e.g. admin), honour it over the DB value
        jwt_role = payload.get('role')
        if jwt_role:
            user['role'] = jwt_role

    if not user:
        # User not in DB yet — create them (preserve role from JWT if present)
        user = {
            'id': payload['user_id'],
            'phone': payload.get('phone', ''),
            'role': payload.get('role', 'rider'),
            'created_at': datetime.utcnow().isoformat(),
            'profile_complete': False,
        }
        try:
            await db.users.insert_one(user)
            logger.info(f'Created new user {user["id"]} from JWT')
        except Exception as e:
            logger.warning(f'Could not insert user into DB: {e}')
        user['is_driver'] = False
        return user

    try:
        driver = await db.drivers.find_one({'user_id': user['id']})
        user['is_driver'] = True if driver else False
    except Exception:
        user['is_driver'] = False
    return user


async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Require the caller to be an authenticated admin."""
    role = current_user.get('role', '')
    if role not in ('admin', 'super_admin', 'operations', 'support', 'finance', 'custom'):
        raise HTTPException(status_code=403, detail='Admin access required')
    return current_user


# Alias for backward compatibility
get_current_admin = get_admin_user
