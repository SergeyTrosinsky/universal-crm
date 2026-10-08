class ValidationFailed(ValueError):
    """Ошибки ввода: {имя_поля: сообщение}. Поля кастомных атрибутов называются cf_<code>,
    общая ошибка — ключ "__all__"."""

    def __init__(self, errors: dict[str, str] | str):
        if isinstance(errors, str):
            errors = {"__all__": errors}
        self.errors = errors
        super().__init__("; ".join(errors.values()))


class NotFound(LookupError):
    pass
