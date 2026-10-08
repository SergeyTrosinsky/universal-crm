"""Командная строка.

    python -m app.cli create-admin --email admin@company.com --name "Иван Петров"
    python -m app.cli reset-password --email user@company.com
    python -m app.cli seed-demo-users
    python -m app.cli seed-showcase --yes     # ПОЛНАЯ замена данных демонстрационным сценарием
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from app.db.init_db import ensure_schema, seed_defaults
from app.db.session import SessionLocal
from app.models import Role
from app.services import user_service
from app.services.user_service import UserError


def _ask_password(given: str | None) -> str:
    if given:
        return given
    first = getpass.getpass("Пароль: ")
    if first != getpass.getpass("Повторите пароль: "):
        sys.exit("Пароли не совпадают")
    return first


def cmd_create_admin(args: argparse.Namespace) -> None:
    password = _ask_password(args.password)
    ensure_schema()
    with SessionLocal() as db:
        seed_defaults(db)
        role = db.scalar(select(Role).where(Role.code == "admin"))
        try:
            user = user_service.create_user(
                db, email=args.email, full_name=args.name, password=password, role_id=role.id
            )
        except UserError as e:
            sys.exit(f"Ошибка: {e}")
    print(f"Администратор создан: {user.email}")


def cmd_reset_password(args: argparse.Namespace) -> None:
    password = _ask_password(args.password)
    with SessionLocal() as db:
        user = user_service.get_user_by_email(db, args.email)
        if user is None:
            sys.exit("Пользователь не найден")
        try:
            user_service.change_own_password(db, user, password)
        except UserError as e:
            sys.exit(f"Ошибка: {e}")
    print(f"Пароль обновлён: {user.email}")


DEMO_PASSWORD = "Demo12345"
DEMO_USERS = [
    ("demo.admin@example.com", "Алексей Админов", "admin"),
    ("demo.manager@example.com", "Мария Менеджерова", "manager"),
    ("demo.manager2@example.com", "Игорь Продажин", "manager"),
    ("demo.employee@example.com", "Ольга Сотрудникова", "employee"),
    ("demo.employee2@example.com", "Денис Работников", "employee"),
]


def cmd_seed_demo_users(args: argparse.Namespace) -> None:
    """Создаёт тестовых пользователей по одному на каждую роль (и по второму для менеджера и сотрудника)."""
    ensure_schema()
    with SessionLocal() as db:
        seed_defaults(db)
        roles = {r.code: r for r in db.scalars(select(Role))}
        for email, name, role_code in DEMO_USERS:
            try:
                user_service.create_user(
                    db, email=email, full_name=name, password=args.password, role_id=roles[role_code].id
                )
                state = "создан"
            except UserError as e:
                state = f"пропущен ({e})"
            print(f"{role_code:9} {email:30} {name:22} {state}")
    print(f"\nПароль для новых пользователей: {args.password}")


def cmd_seed_showcase(args: argparse.Namespace) -> None:
    """Сбрасывает данные и наполняет CRM демонстрационным сценарием (см. app/demo_scenario.py)."""
    from app.demo_scenario import run_scenario

    if not args.yes:
        sys.exit(
            "Команда УДАЛИТ всех пользователей, клиентов, сделки, задачи, поля и шаблоны и создаст демо-данные.\n"
            "Сделайте резервную копию и запустите ещё раз с ключом --yes."
        )
    ensure_schema()
    with SessionLocal() as db:
        seed_defaults(db)
        summary = run_scenario(db, password=args.password, with_vin=args.with_vin)
    print("Демо-сценарий загружен.\n")
    print(f"Клиентов: {summary['clients']}, сделок: {summary['deals']}, задач: {summary['tasks']}\n")
    print(f"{'Email':32} {'ФИО':20} {'Роль':14} Описание")
    for _key, email, name, role, note in summary["users"]:
        print(f"{email:32} {name:20} {role:14} {note}")
    print(f"\nПароль у всех: {summary['password']}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="Служебные команды CRM")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="создать администратора")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Администратор")
    p.add_argument("--password", help="если не указан — будет запрошен интерактивно")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("reset-password", help="задать новый пароль пользователю")
    p.add_argument("--email", required=True)
    p.add_argument("--password")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("seed-demo-users", help="создать тестовых пользователей со всеми ролями")
    p.add_argument("--password", default=DEMO_PASSWORD)
    p.set_defaults(func=cmd_seed_demo_users)

    p = sub.add_parser("seed-showcase", help="демо-сценарий: заменить ВСЕ данные примером рабочей CRM")
    p.add_argument("--yes", action="store_true", help="подтверждаю удаление текущих данных")
    p.add_argument("--password", default="Kontinent2026", help="пароль демо-пользователей (по умолчанию Kontinent2026)")
    p.add_argument("--with-vin", action="store_true", help="сразу создать поля «VIN» и «Госномер» (для съёмки скриншотов)")
    p.set_defaults(func=cmd_seed_showcase)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
