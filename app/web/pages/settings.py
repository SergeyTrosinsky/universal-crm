"""Раздел «Настройки»: пользователи и роли."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.permissions import USERS_MANAGE
from app.db.session import get_db
from app.models import Role, User
from app.services import role_service, user_service
from app.services.role_service import RoleError
from app.services.user_service import UserError
from app.web.deps import require_web_permission
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/settings")


def _user_or_404(db: Session, user_id: int) -> User:
    target = user_service.get_user(db, user_id)
    if target is None:
        raise HTTPException(404, "Пользователь не найден")
    return target


def _role_or_404(db: Session, role_id: int) -> Role:
    role = role_service.get_role(db, role_id)
    if role is None:
        raise HTTPException(404, "Роль не найдена")
    return role


# ---------------------------------------------------------------- пользователи
@router.get("/users")
def users_list(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(USERS_MANAGE))
):
    return render(request, "settings/users.html", {"users": user_service.list_users(db)}, user=user)


def _user_form(request, db, actor, *, target=None, form=None, error=None, status_code=200):
    ctx = {
        "target": target,
        "roles": role_service.list_roles(db),
        "form": form or {},
        "error": error,
    }
    return render(request, "settings/user_form.html", ctx, user=actor, status_code=status_code)


@router.get("/users/new")
def user_new_page(
    request: Request, db: Session = Depends(get_db), actor: User = Depends(require_web_permission(USERS_MANAGE))
):
    return _user_form(request, db, actor, form={"is_active": True})


@router.post("/users/new")
def user_create(
    request: Request,
    email: str = Form(""),
    full_name: str = Form(""),
    password: str = Form(""),
    role_id: int = Form(...),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_web_permission(USERS_MANAGE)),
):
    form = {"email": email, "full_name": full_name, "role_id": role_id, "is_active": is_active is not None}
    try:
        created = user_service.create_user(
            db,
            email=email,
            full_name=full_name,
            password=password,
            role_id=role_id,
            is_active=is_active is not None,
            actor=actor,
        )
    except UserError as e:
        db.rollback()
        return _user_form(request, db, actor, form=form, error=str(e), status_code=400)
    flash(request, f"Пользователь «{created.full_name}» создан")
    return redirect("/settings/users")


@router.get("/users/{user_id}/edit")
def user_edit_page(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_web_permission(USERS_MANAGE)),
):
    target = _user_or_404(db, user_id)
    form = {
        "email": target.email,
        "full_name": target.full_name,
        "role_id": target.role_id,
        "is_active": target.is_active,
    }
    return _user_form(request, db, actor, target=target, form=form)


@router.post("/users/{user_id}/edit")
def user_update(
    user_id: int,
    request: Request,
    full_name: str = Form(""),
    password: str = Form(""),
    role_id: int = Form(...),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_web_permission(USERS_MANAGE)),
):
    target = _user_or_404(db, user_id)
    form = {"email": target.email, "full_name": full_name, "role_id": role_id, "is_active": is_active is not None}
    try:
        user_service.update_user(
            db,
            target,
            actor=actor,
            full_name=full_name,
            role_id=role_id,
            is_active=is_active is not None,
            password=password or None,
        )
    except UserError as e:
        db.rollback()
        db.refresh(target)
        return _user_form(request, db, actor, target=target, form=form, error=str(e), status_code=400)
    flash(request, "Изменения сохранены")
    return redirect("/settings/users")


# ----------------------------------------------------------------------- роли
@router.get("/roles")
def roles_list(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(USERS_MANAGE))
):
    ctx = {"roles": role_service.list_roles(db), "counts": role_service.users_count_by_role(db)}
    return render(request, "settings/roles.html", ctx, user=user)


def _role_form(request, actor, *, role=None, form=None, error=None, status_code=200):
    ctx = {"role": role, "form": form or {"permissions": []}, "error": error}
    return render(request, "settings/role_form.html", ctx, user=actor, status_code=status_code)


@router.get("/roles/new")
def role_new_page(request: Request, actor: User = Depends(require_web_permission(USERS_MANAGE))):
    return _role_form(request, actor)


@router.post("/roles/new")
def role_create(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
    permissions: list[str] = Form([]),
    db: Session = Depends(get_db),
    actor: User = Depends(require_web_permission(USERS_MANAGE)),
):
    form = {"code": code, "name": name, "description": description, "permissions": permissions}
    try:
        created = role_service.create_role(
            db, code=code, name=name, description=description, permissions=permissions
        )
    except RoleError as e:
        db.rollback()
        return _role_form(request, actor, form=form, error=str(e), status_code=400)
    flash(request, f"Роль «{created.name}» создана")
    return redirect("/settings/roles")


@router.get("/roles/{role_id}/edit")
def role_edit_page(
    role_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_web_permission(USERS_MANAGE)),
):
    role = _role_or_404(db, role_id)
    form = {
        "code": role.code,
        "name": role.name,
        "description": role.description or "",
        "permissions": list(role.permissions or []),
    }
    return _role_form(request, actor, role=role, form=form)


@router.post("/roles/{role_id}/edit")
def role_update(
    role_id: int,
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    permissions: list[str] = Form([]),
    db: Session = Depends(get_db),
    actor: User = Depends(require_web_permission(USERS_MANAGE)),
):
    role = _role_or_404(db, role_id)
    form = {"code": role.code, "name": name, "description": description, "permissions": permissions}
    try:
        role_service.update_role(
            db,
            role,
            name=name,
            description=description,
            # у роли администратора права не редактируются
            permissions=None if role.has_permission("*") else permissions,
        )
    except RoleError as e:
        db.rollback()
        db.refresh(role)
        return _role_form(request, actor, role=role, form=form, error=str(e), status_code=400)
    flash(request, "Роль сохранена")
    return redirect("/settings/roles")


@router.post("/roles/{role_id}/delete")
def role_delete(
    role_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_web_permission(USERS_MANAGE)),
):
    role = _role_or_404(db, role_id)
    try:
        role_service.delete_role(db, role)
    except RoleError as e:
        db.rollback()
        flash(request, str(e), "error")
        return redirect("/settings/roles")
    flash(request, "Роль удалена")
    return redirect("/settings/roles")
