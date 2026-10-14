from pydantic import BaseModel


class ColumnData(BaseModel):
    name: str
    type: str
    pk: bool = False
    fk: bool = False
    nullable: bool = True
    references: str | None = None
    visibility: str = "public"
    is_derived: bool = False
    default_value: str | None = None
    order_index: int = 0


class Position(BaseModel):
    x: float
    y: float


class CommandPayload(BaseModel):
    entity_id: str | None = None
    entity_name: str | None = None
    source: str | None = None
    columns: list[ColumnData] | None = None
    column_name: str | None = None
    column_changes: dict | None = None
    position: Position | None = None
    source_entity_id: str | None = None
    target_entity_id: str | None = None
    relation_type: str | None = None
    source_column: str | None = None
    target_column: str | None = None
    relation_id: str | None = None
    # UML aliases — map to same fields
    class_id: str | None = None
    class_name: str | None = None
    attributes: list[ColumnData] | None = None
    attribute_name: str | None = None
    attribute_changes: dict | None = None
    source_class_id: str | None = None
    target_class_id: str | None = None
    association_type: str | None = None
    source_attribute: str | None = None
    target_attribute: str | None = None
    association_id: str | None = None
    # Resize fields
    width: float | None = None
    height: float | None = None
    # Package fields
    package_id: str | None = None
    package_name: str | None = None
    # Role and multiplicity fields
    source_role: str | None = None
    target_role: str | None = None
    source_multiplicity: str | None = None
    target_multiplicity: str | None = None
    # Classifier metadata
    is_abstract: bool | None = None
    is_visible: bool | None = None
    element_type: str | None = None
    ordered_attribute_names: list[str] | None = None

    model_config = {"extra": "allow"}
