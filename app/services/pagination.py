import math
from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    extra: dict = field(default_factory=dict)

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def first_item(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def last_item(self) -> int:
        return min(self.total, self.page * self.per_page)

    def window(self, around: int = 2) -> list[int | None]:
        """Номера страниц для навигации; None — многоточие."""
        wanted = {1, self.pages, *range(max(1, self.page - around), min(self.pages, self.page + around) + 1)}
        result: list[int | None] = []
        previous = 0
        for number in sorted(wanted):
            if number - previous > 1:
                result.append(None)
            result.append(number)
            previous = number
        return result


def clamp_page(page: int, total: int, per_page: int) -> int:
    pages = max(1, math.ceil(total / per_page))
    return min(max(1, page), pages)
