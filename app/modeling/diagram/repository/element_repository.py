"""
Repositorio para elementos UML y elementos de Board (CU3).
Encapsula el acceso a datos para elementos de diagramas, atributos, asociaciones y tableros.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.diagram.entity.uml_entity import (
    ClassElement, Attribute, Association, Package, AssociationType, AssociationClassLink
)
from app.modeling.diagram.entity.board_normalized_entity import BoardElement
from app.workspace.projects.entity.project_entity import Project


class ElementRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_class_by_id(self, class_id: str) -> Optional[ClassElement]:
        return await self.db.get(ClassElement, class_id)

    async def list_classes_by_package(self, package_id: str) -> List[ClassElement]:
        stmt = select(ClassElement).where(ClassElement.package_id == package_id).order_by(ClassElement.name)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_attributes_by_class(self, class_id: str) -> List[Attribute]:
        stmt = select(Attribute).where(Attribute.class_id == class_id).order_by(Attribute.order_index)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_board_element(self, board_id: str, class_id: str) -> Optional[BoardElement]:
        stmt = select(BoardElement).where(
            BoardElement.board_id == board_id,
            BoardElement.class_id == class_id,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_attribute_by_name(self, class_id: str, col_name: str) -> Optional[Attribute]:
        stmt = select(Attribute).where(
            Attribute.class_id == class_id,
            Attribute.name == col_name,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_parent_generalization(
        self, source_id: str, assoc_type: AssociationType
    ) -> Optional[Association]:
        stmt = select(Association).where(
            Association.source_class_id == source_id,
            Association.type == assoc_type,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_association_class_link(self, assoc_id: str) -> Optional[AssociationClassLink]:
        stmt = select(AssociationClassLink).where(AssociationClassLink.association_id == assoc_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_default_package_for_project(self, project_id: str) -> Optional[Package]:
        stmt = select(Package).where(Package.project_id == project_id).limit(1)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_project_by_owner(self, owner_id: str) -> Optional[Project]:
        stmt = select(Project).where(Project.owner_id == owner_id).limit(1)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
