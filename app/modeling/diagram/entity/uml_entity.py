"""
Repositorio UML normalizado — fuente única de verdad.

Tables: package, class_element, attribute,
        association, association_class_link

Antes toda esta información vivía en boards.diagram_snapshot TEXT (un blob JSON).
Ahora cada entidad tiene su propia fila con FK tipadas, lo que permite:
- codegen tipado de Spring
- function-calling fiable para la IA (sin parsear JSON)
- undo/redo atómico contra filas reales
"""
import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Text, Boolean, Integer, Float, DateTime,
    Enum as SAEnum, ForeignKey, func, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


# ─── Enums ───────────────────────────────────────────────────────────────────

class ClassSource(str, enum.Enum):
    manual = "manual"
    archi_import = "archi_import"
    image_ocr = "image_ocr"


class ClassifierType(str, enum.Enum):
    class_ = "class"
    abstract_class = "abstract_class"
    interface = "interface"
    enumeration = "enumeration"
    datatype = "datatype"


class VisibilityEnum(str, enum.Enum):
    public = "public"
    private = "private"
    protected = "protected"
    package = "package"


class AssociationType(str, enum.Enum):
    association = "association"
    aggregation = "aggregation"
    composition = "composition"
    generalization = "generalization"
    realization = "realization"
    dependency = "dependency"


# ─── Package ─────────────────────────────────────────────────────────────────

class Package(Base):
    """
    Agrupa clases dentro de un proyecto (estructura plana).
    En backfill se crea un package 'default' por proyecto para albergar todas
    las clases migradas desde diagram_snapshot.
    """
    __tablename__ = "package"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)


# ─── ClassElement ─────────────────────────────────────────────────────────────

class ClassElement(Base):
    """
    Clase/tabla UML — su id es la referencia en attribute, association y board_element.
    Nunca se regenera ni reutiliza; es el «nombre real» de una clase en todo el sistema.
    """
    __tablename__ = "class_element"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    package_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("package.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    element_type: Mapped[ClassifierType] = mapped_column(
        SAEnum(ClassifierType, name="class_element_type", values_callable=lambda x: [e.value for e in x]),
        default=ClassifierType.class_,
        nullable=False,
    )
    # True = no tabla física; solo sus hijas concretas se mapean a @Entity
    is_abstract: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[ClassSource] = mapped_column(
        SAEnum(ClassSource, name="class_source"), default=ClassSource.manual, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


# ─── Attribute ────────────────────────────────────────────────────────────────

class Attribute(Base):
    """
    Campo de una clase. order_index garantiza orden determinístico para el
    generador y el renderer (sin él el orden varía entre cargas).
    """
    __tablename__ = "attribute"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Varchar libre: el catálogo de tipos SQL es amplio y varía por motor
    data_type: Mapped[str] = mapped_column(String(100), nullable=False, default="VARCHAR")
    visibility: Mapped[VisibilityEnum] = mapped_column(
        SAEnum(VisibilityEnum, name="visibility_enum"), default=VisibilityEnum.public, nullable=False
    )
    # Decide qué anotar con @Id en la Entity generada
    is_pkey: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Informativo — la relación real para @ManyToOne es association, no este flag
    is_fkey: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Si True, el generador omite la columna del @Entity y la genera como método calculado
    is_derived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Sin esto el orden de columnas queda no-determinístico entre cargas
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ─── Association ──────────────────────────────────────────────────────────────

class Association(Base):
    """
    Relación UML entre dos clases. El generador usa (type, multiplicity)
    para decidir qué anotación JPA emitir (@OneToMany, @ManyToOne, etc.).
    """
    __tablename__ = "association"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False
    )
    target_class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[AssociationType] = mapped_column(
        SAEnum(AssociationType, name="association_type"), nullable=False,
        default=AssociationType.association
    )
    # Nombre de la relación (ej. "realiza") — documentación visual
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Roles para nombrar campos en la Entity generada (evita ambigüedad en self-joins)
    source_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Cardinalidad UML ("1", "0..1", "0..*", "1..*") → decide @OneToOne/@OneToMany/etc.
    source_multiplicity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_multiplicity: Mapped[str | None] = mapped_column(String(20), nullable=True)


# ─── AssociationClassLink ─────────────────────────────────────────────────────

class AssociationClassLink(Base):
    """
    Clase de asociación N:M con atributos propios (ej. DetalleVenta).
    UNIQUE(association_id): una asociación no puede tener dos clases intermedias.
    """
    __tablename__ = "association_class_link"
    __table_args__ = (
        UniqueConstraint("association_id", name="uq_assoc_class_link_assoc"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    association_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("association.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("class_element.id", ondelete="RESTRICT"), nullable=False
    )
