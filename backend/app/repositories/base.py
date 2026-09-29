"""Generic repository base with pagination, filtering and sorting helpers."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401  (documentation only)
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)

SORTER_MAP: dict[str, Any] = {}


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: type[ModelT], session: Session) -> None:
        self.model = model
        self.session = session

    # ------------------------------------------------------------- queries
    @property
    def soft_delete_column(self) -> Any | None:
        """``is_deleted`` when the model is soft-deletable, otherwise ``None``."""
        return getattr(self.model, "is_deleted", None)

    def _base_query(self) -> Select:
        stmt = select(self.model)
        if self.soft_delete_column is not None:
            stmt = stmt.where(self.soft_delete_column.is_(False))
        return stmt

    def get(self, entity_id: uuid.UUID | str, *, with_for_update: bool = False) -> ModelT | None:
        try:
            pk: Any = entity_id if isinstance(entity_id, uuid.UUID) else uuid.UUID(str(entity_id))
        except (ValueError, AttributeError, TypeError):
            return None
        stmt = self._base_query().where(self.model.id == pk)
        if with_for_update:
            stmt = stmt.with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def find_one_by(self, **filters: Any) -> ModelT | None:
        stmt = self._base_query()
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        return self.session.execute(stmt).scalar_one_or_none()

    def find_all(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ModelT]:
        stmt = self.apply_filters(self._base_query(), filters)
        stmt = self.apply_sort(stmt, order_by)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def find_first(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: Sequence[str] | None = None,
    ) -> ModelT | None:
        results = self.find_all(filters=filters, order_by=order_by, limit=1)
        return results[0] if results else None

    def apply_filters(self, stmt: Select, filters: dict[str, Any] | None) -> Select:
        for key, value in (filters or {}).items():
            if value is None:
                continue
            column = getattr(self.model, key, None)
            if column is None:
                continue
            if isinstance(value, (list, tuple, set)):
                stmt = stmt.where(column.in_(list(value)))
            else:
                stmt = stmt.where(column == value)
        return stmt

    def apply_sort(
        self, stmt: Select, order_by: Sequence[str] | None, *, default: str = "created_at"
    ) -> Select:
        order_by = order_by or [default]
        for raw in order_by:
            descending = raw.startswith("-")
            field = raw[1:] if descending else raw
            column = getattr(self.model, field, None)
            if column is not None:
                stmt = stmt.order_by(column.desc() if descending else column.asc())
        return stmt

    def paginate(
        self,
        *,
        stmt: Select | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ModelT], int]:
        stmt = stmt if stmt is not None else self._base_query()
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int(self.session.execute(count_stmt).scalar_one())
        results = (
            self.session.execute(stmt.limit(page_size).offset((page - 1) * page_size))
            .scalars()
            .all()
        )
        return list(results), total

    def count(self, **filters: Any) -> int:
        """Count rows, honouring soft deletes and list/in_ filters."""
        sub = self.apply_filters(self._base_query(), filters).subquery()
        return int(self.session.execute(select(func.count()).select_from(sub)).scalar_one())

    def exists(self, **filters: Any) -> bool:
        return self.count(**filters) > 0

    def aggregate_sum(self, column_name: str, **filters: Any) -> float:
        column = getattr(self.model, column_name)
        stmt = select(func.coalesce(func.sum(column), 0.0)).select_from(self.model)
        for key, value in filters.items():
            attr = getattr(self.model, key, None)
            if attr is not None and value is not None:
                stmt = stmt.where(attr == value)
        return float(self.session.execute(stmt).scalar_one() or 0.0)

    # ------------------------------------------------------------ mutation
    def create(self, **values: Any) -> ModelT:
        instance = self.model(**values)
        self.session.add(instance)
        self.session.flush()
        self.session.refresh(instance)
        return instance

    def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        self.session.flush()
        return instance

    def update(self, instance: ModelT, **values: Any) -> ModelT:
        for key, value in values.items():
            if value is not None and hasattr(instance, key):
                setattr(instance, key, value)
        self.session.flush()
        return instance

    def delete(self, instance: ModelT, *, hard: bool = False) -> None:
        if hard:
            self.session.delete(instance)
        elif hasattr(instance, "is_deleted"):
            instance.is_deleted = True
        self.session.flush()

    def bulk_delete(self, **filters: Any) -> int:
        stmt = sa_delete(self.model)
        for key, value in filters.items():
            column = getattr(self.model, key, None)
            if column is not None and value is not None:
                stmt = stmt.where(column == value)
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

    def flush(self) -> None:
        self.session.flush()

    def refresh(self, instance: ModelT) -> ModelT:
        self.session.refresh(instance)
        return instance
