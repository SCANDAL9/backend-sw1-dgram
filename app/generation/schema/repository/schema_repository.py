"""
Schema Repository — Data access layer for XMI import/export and board UML definitions.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import BoardElement
from app.modeling.diagram.entity.uml_entity import ClassElement, Attribute, Association


class SchemaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_board_elements(self, board_id: str) -> list[BoardElement]:
        stmt = select(BoardElement).where(BoardElement.board_id == board_id)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_classes_by_ids(self, class_ids: list[str]) -> list[ClassElement]:
        if not class_ids:
            return []
        stmt = select(ClassElement).where(ClassElement.id.in_(class_ids))
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_classes_by_package(self, package_id: str) -> list[ClassElement]:
        stmt = select(ClassElement).where(ClassElement.package_id == package_id)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_attributes_for_class(self, class_id: str) -> list[Attribute]:
        stmt = select(Attribute).where(Attribute.class_id == class_id).order_by(Attribute.order_index)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_associations(self, class_ids: list[str]) -> list[Association]:
        if not class_ids:
            return []
        stmt = select(Association).where(
            Association.source_class_id.in_(class_ids),
            Association.target_class_id.in_(class_ids),
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
