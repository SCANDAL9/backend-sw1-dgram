"""
Repositorio para elementos UML y elementos de Board (CU3).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.diagram.entity.uml_entity import ClassElement, Attribute, Association, Package
from app.modeling.diagram.entity.board_normalized_entity import BoardElement


class ElementRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_class_by_id(self, class_id: str) -> ClassElement | None:
        return await self.db.get(ClassElement, class_id)

    async def list_classes_by_package(self, package_id: str) -> list[ClassElement]:
        stmt = select(ClassElement).where(ClassElement.package_id == package_id).order_by(ClassElement.name)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_attributes_by_class(self, class_id: str) -> list[Attribute]:
        stmt = select(Attribute).where(Attribute.class_id == class_id).order_by(Attribute.order_index)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
