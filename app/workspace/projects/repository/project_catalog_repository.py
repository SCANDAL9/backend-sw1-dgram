"""
Repositorio para operaciones del catálogo de clases UML en proyectos y tableros.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.modeling.diagram.entity.uml_entity import Package, ClassElement, Attribute
from app.modeling.diagram.entity.board_normalized_entity import BoardElement
from app.workspace.projects.dto.project_dto import AttributeSummary, ProjectClassResponse


class ProjectCatalogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_project_classes(self, project_id: str) -> list[ProjectClassResponse]:
        stmt = (
            select(ClassElement)
            .join(Package, ClassElement.package_id == Package.id)
            .where(Package.project_id == project_id)
            .order_by(ClassElement.name)
        )
        res = await self.db.execute(stmt)
        classes = res.scalars().all()

        result: list[ProjectClassResponse] = []
        for cls in classes:
            attr_stmt = select(Attribute).where(Attribute.class_id == cls.id).order_by(Attribute.order_index)
            attr_res = await self.db.execute(attr_stmt)
            attrs = attr_res.scalars().all()

            be_stmt = select(func.count(BoardElement.id)).where(BoardElement.class_id == cls.id)
            be_cnt_res = await self.db.execute(be_stmt)
            boards_cnt = be_cnt_res.scalar_one_or_none() or 0

            result.append(
                ProjectClassResponse(
                    id=cls.id,
                    name=cls.name,
                    package_id=cls.package_id,
                    element_type=cls.element_type.value if hasattr(cls.element_type, "value") else str(cls.element_type),
                    is_abstract=cls.is_abstract,
                    attributes=[
                        AttributeSummary(
                            id=a.id,
                            name=a.name,
                            data_type=a.data_type,
                            visibility=a.visibility.value if hasattr(a.visibility, "value") else str(a.visibility),
                            is_pkey=a.is_pkey,
                        )
                        for a in attrs
                    ],
                    boards_count=boards_cnt,
                    is_on_current_board=False,
                )
            )
        return result

    async def get_board_class_ids(self, board_id: str) -> set[str]:
        be_stmt = select(BoardElement.class_id).where(BoardElement.board_id == board_id)
        be_res = await self.db.execute(be_stmt)
        return set(be_res.scalars().all())

    async def get_class_with_package(self, class_id: str) -> tuple[ClassElement | None, Package | None]:
        cls = await self.db.get(ClassElement, class_id)
        if not cls:
            return None, None
        pkg = await self.db.get(Package, cls.package_id)
        return cls, pkg

    async def get_board_element(self, board_id: str, class_id: str) -> BoardElement | None:
        stmt = select(BoardElement).where(
            BoardElement.board_id == board_id,
            BoardElement.class_id == class_id,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def attach_class(self, board_id: str, class_id: str, x: float, y: float) -> BoardElement:
        be_id = str(uuid.uuid4())
        new_be = BoardElement(
            id=be_id,
            board_id=board_id,
            class_id=class_id,
            x=x,
            y=y,
            width=180.0,
            height=120.0,
        )
        self.db.add(new_be)
        await self.db.commit()
        return new_be

    async def detach_class(self, board_id: str, class_id: str) -> None:
        await self.db.execute(
            delete(BoardElement).where(
                BoardElement.board_id == board_id,
                BoardElement.class_id == class_id,
            )
        )
        await self.db.commit()

    async def delete_class_from_model(self, class_id: str) -> bool:
        cls = await self.db.get(ClassElement, class_id)
        if not cls:
            return False
        await self.db.execute(delete(BoardElement).where(BoardElement.class_id == class_id))
        await self.db.execute(delete(ClassElement).where(ClassElement.id == class_id))
        await self.db.commit()
        return True
