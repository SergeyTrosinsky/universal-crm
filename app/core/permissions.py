"""Каталог прав. Роли хранят список строк в roles.permissions; "*" = всё."""
CLIENTS_READ = "clients:read"
CLIENTS_WRITE = "clients:write"
CLIENTS_DELETE = "clients:delete"
DEALS_READ = "deals:read"
DEALS_WRITE = "deals:write"
DEALS_DELETE = "deals:delete"
DEALS_READ_ALL = "deals:read_all"      # видеть сделки других сотрудников (иначе — только свои)
DEALS_ASSIGN = "deals:assign"          # назначать ответственного
TASKS_READ = "tasks:read"
TASKS_WRITE = "tasks:write"
TASKS_READ_ALL = "tasks:read_all"      # видеть задачи других сотрудников
TASKS_ASSIGN = "tasks:assign"          # ставить задачи другим сотрудникам
DASHBOARD_READ = "dashboard:read"
USERS_MANAGE = "users:manage"          # пользователи и роли
SETTINGS_MANAGE = "settings:manage"    # кастомные поля и статусы

ALL = "*"

# Для UI редактора ролей: (название группы, [(право, подпись), ...])
PERMISSION_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Клиенты", [
        (CLIENTS_READ, "Просмотр"),
        (CLIENTS_WRITE, "Создание и редактирование"),
        (CLIENTS_DELETE, "Удаление"),
    ]),
    ("Сделки", [
        (DEALS_READ, "Просмотр"),
        (DEALS_WRITE, "Создание и редактирование"),
        (DEALS_DELETE, "Удаление"),
        (DEALS_READ_ALL, "Сделки всех сотрудников (иначе — только свои)"),
        (DEALS_ASSIGN, "Назначение ответственных"),
    ]),
    ("Задачи", [
        (TASKS_READ, "Свои задачи"),
        (TASKS_WRITE, "Создание и редактирование"),
        (TASKS_READ_ALL, "Задачи всех сотрудников"),
        (TASKS_ASSIGN, "Назначение задач другим сотрудникам"),
    ]),
    ("Система", [
        (DASHBOARD_READ, "Главная со статистикой"),
        (SETTINGS_MANAGE, "Настройка CRM (поля, статусы)"),
        (USERS_MANAGE, "Пользователи и роли"),
    ]),
]

ALL_PERMISSIONS: list[str] = [code for _, items in PERMISSION_GROUPS for code, _ in items]
PERMISSION_LABELS: dict[str, str] = {
    code: f"{group}: {label}" for group, items in PERMISSION_GROUPS for code, label in items
}
