from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.api.errors import to_http
from app.core.permissions import TASKS_READ, TASKS_WRITE
from app.db.session import get_db
from app.models import Task, User
from app.schemas.common import PageOut
from app.schemas.task import TaskCreate, TaskRead, TaskStatusChange, TaskUpdate
from app.services import task_service
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_or_404(db: Session, task_id: int, viewer: User) -> Task:
    task = task_service.get_task(db, task_id)
    # Чужую задачу не раскрываем даже фактом существования
    if task is None or not task_service.has_access(viewer, task):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    return task


@router.get("", response_model=PageOut[TaskRead])
def list_tasks(
    q: str | None = Query(None, description="Поиск по названию, описанию, клиенту и сделке"),
    view: str | None = Query(None, description="open (по умолчанию) | overdue | today | done | all"),
    status_: str | None = Query(None, alias="status", description="todo | in_progress | done | cancelled"),
    priority: str | None = None,
    assignee: str | None = Query(None, description="me | all | id пользователя. По умолчанию — me"),
    client_id: int | None = None,
    deal_id: int | None = None,
    due_from: str | None = Query(None, description="YYYY-MM-DD"),
    due_to: str | None = Query(None, description="YYYY-MM-DD"),
    sort: str | None = Query(None, description="due | -due | priority | title | created | -created"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    viewer: User = Depends(require_permission(TASKS_READ)),
) -> PageOut[TaskRead]:
    result = task_service.list_tasks(
        db, viewer, q=q, view=view, status=status_, priority=priority, assignee=assignee or "me",
        client_id=client_id, deal_id=deal_id, due_from=due_from, due_to=due_to,
        sort=sort, page=page, per_page=per_page,
    )
    return PageOut[TaskRead](
        items=[TaskRead.model_validate(t) for t in result.items],
        total=result.total, page=result.page, per_page=result.per_page, pages=result.pages,
    )


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(TASKS_WRITE)),
) -> Task:
    try:
        return task_service.create_task(db, data=payload.model_dump(exclude_unset=True), actor=actor)
    except ValidationFailed as e:
        raise to_http(e) from e


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: int, db: Session = Depends(get_db), viewer: User = Depends(require_permission(TASKS_READ))
) -> Task:
    return _get_or_404(db, task_id, viewer)


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(TASKS_WRITE)),
) -> Task:
    task = _get_or_404(db, task_id, actor)
    try:
        return task_service.update_task(
            db, task, data=payload.model_dump(exclude_unset=True), actor=actor, partial=True
        )
    except ValidationFailed as e:
        raise to_http(e) from e


@router.post("/{task_id}/status", response_model=TaskRead)
def change_task_status(
    task_id: int,
    payload: TaskStatusChange,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(TASKS_WRITE)),
) -> Task:
    task = _get_or_404(db, task_id, actor)
    try:
        return task_service.change_status(db, task, payload.status.value)
    except ValidationFailed as e:
        raise to_http(e) from e


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int, db: Session = Depends(get_db), actor: User = Depends(require_permission(TASKS_WRITE))
) -> Response:
    task_service.delete_task(db, _get_or_404(db, task_id, actor))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
