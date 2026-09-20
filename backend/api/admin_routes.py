"""Platform-wide admin routes: search users, change any user's role.

Distinct from `classroom_routes.py`'s classroom-scoped faculty promotion --
this is the unrestricted "change anyone's status in the entire db" power,
admin-only, per the product decision that the role hierarchy's top tier has
no scoping boundary. Every change is audit-logged with actor, target, old
and new role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit
from backend import classrooms as classroom_service
from backend.auth import Principal, require_admin
from backend.auth.roles import role_for_email
from backend.db import get_session
from backend.models import Role, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _effective_role(user: User) -> Role:
    return user.role_override if user.role_override is not None else role_for_email(user.email)


@router.get("/users")
async def search_users(
    q: str = Query(default="", max_length=320),
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(User).order_by(User.email).limit(50)
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.name.ilike(like)))
    rows = (await db.scalars(stmt)).all()
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": _effective_role(u).value,
                "role_override": u.role_override.value if u.role_override else None,
            }
            for u in rows
        ]
    }


class SetRoleRequest(BaseModel):
    role: Role


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str,
    body: SetRoleRequest,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    if user_id == principal.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An admin cannot change their own role -- ask another admin to do it.",
        )
    user = (await db.scalars(select(User).where(User.id == user_id))).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_role = _effective_role(user)
    user.role_override = body.role
    await db.flush()
    demoted_in: list[str] = []
    if body.role == Role.STUDENT:
        # A student must count as a student everywhere: any class where they
        # still held a faculty membership would keep them out of the student
        # roster and tag their prompts as faculty test traffic.
        demoted_in = await classroom_service.demote_all_class_faculty(db, user.id)
        for classroom_id in demoted_in:
            await audit.record(
                db,
                audit.CLASS_FACULTY_DEMOTED,
                user_id=principal.id,
                classroom_id=classroom_id,
                detail={"target_user_id": user_id, "reason": "platform role set to student"},
            )
    await audit.record(
        db,
        audit.ROLE_CHANGED,
        user_id=principal.id,
        detail={"target_user_id": user_id, "old_role": old_role.value, "new_role": body.role.value},
    )
    await db.commit()
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": body.role.value,
        "role_override": body.role.value,
        "moved_to_student_in": demoted_in,
    }


@router.delete("/users/{user_id}/role-override")
async def clear_user_role_override(
    user_id: str,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Undoes a prior PATCH .../role: the user's role goes back to being
    purely domain-derived (admin allowlist / faculty domain / else
    student), re-evaluated on their very next request, same as any account
    that was never overridden."""
    if user_id == principal.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An admin cannot change their own role -- ask another admin to do it.",
        )
    user = (await db.scalars(select(User).where(User.id == user_id))).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_role = _effective_role(user)
    user.role_override = None
    new_role = role_for_email(user.email)
    await audit.record(
        db,
        audit.ROLE_CHANGED,
        user_id=principal.id,
        detail={
            "target_user_id": user_id,
            "old_role": old_role.value,
            "new_role": new_role.value,
            "cleared_override": True,
        },
    )
    await db.commit()
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": new_role.value,
        "role_override": None,
    }
