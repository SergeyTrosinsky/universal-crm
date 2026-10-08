from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class MoneyOut(BaseModel):
    currency: str
    amount: Decimal


class ClientsStats(BaseModel):
    total: int
    new: int


class StatusStats(BaseModel):
    id: int
    name: str
    color: str
    kind: str
    count: int
    amounts: list[MoneyOut]


class MonthStats(BaseModel):
    month: str
    label: str
    created: int
    won: int


class ResponsibleStats(BaseModel):
    user_id: int | None
    name: str
    open: int
    won: int
    won_amounts: list[MoneyOut]


class DealsStats(BaseModel):
    open_count: int
    open_amounts: list[MoneyOut]
    won_count: int
    won_amounts: list[MoneyOut]
    lost_count: int
    lost_amounts: list[MoneyOut]
    created: int
    conversion: float | None
    by_status: list[StatusStats]
    monthly: list[MonthStats]
    by_responsible: list[ResponsibleStats]


class TasksStats(BaseModel):
    open: int
    overdue: int
    today: int
    team_overdue: int | None


class BreakdownItem(BaseModel):
    value: str
    count: int


class Breakdown(BaseModel):
    entity: str
    field_id: int
    field: str
    items: list[BreakdownItem]


class DashboardOut(BaseModel):
    period: str
    period_label: str
    since: datetime | None
    personal: bool = False
    clients: ClientsStats | None
    deals: DealsStats | None
    tasks: TasksStats | None
    breakdowns: list[Breakdown]
