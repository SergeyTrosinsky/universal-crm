"""Русские подписи для enum-ов (используются в шаблонах)."""
ENTITY_LABELS = {"client": "Клиенты", "deal": "Сделки"}
ENTITY_LABELS_SINGULAR = {"client": "клиента", "deal": "сделки"}

FIELD_TYPE_LABELS = {
    "text": "Текст",
    "textarea": "Многострочный текст",
    "integer": "Целое число",
    "decimal": "Число",
    "date": "Дата",
    "datetime": "Дата и время",
    "boolean": "Флажок (да/нет)",
    "select": "Выпадающий список",
    "multiselect": "Несколько из списка",
    "phone": "Телефон",
    "email": "Email",
    "url": "Ссылка",
}

STATUS_KIND_LABELS = {"open": "В работе", "won": "Успешно закрыта", "lost": "Проиграна"}
CLIENT_TYPE_LABELS = {"person": "Физлицо", "company": "Компания"}
CURRENCIES = {"RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸", "BYN": "Br", "UAH": "₴"}

TASK_STATUS_LABELS = {"todo": "К выполнению", "in_progress": "В работе", "done": "Выполнена", "cancelled": "Отменена"}
TASK_PRIORITY_LABELS = {"low": "Низкий", "normal": "Обычный", "high": "Высокий", "urgent": "Срочный"}
