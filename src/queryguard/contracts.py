"""Generic schema and structural-validation contracts for QueryGuard."""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


class SqlColumnDefinition(BaseModel):
    """A single column in an approved schema catalog."""

    name: Annotated[str, Field(min_length=1, description="Column name")]
    description: Annotated[str, Field(min_length=1, description="Business-friendly description")]
    data_type: Annotated[str, Field(min_length=1, description="Database type")]
    nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_key_target: str | None = None
    is_user_scope: bool = False
    allowed_for_select: bool = True
    sensitive: bool = False

    @model_validator(mode="after")
    def _validate_fk_and_sensitive(self) -> "SqlColumnDefinition":
        if self.is_foreign_key and not self.foreign_key_target:
            raise ValueError("foreign_key_target required when is_foreign_key=True")
        if self.sensitive and self.allowed_for_select:
            object.__setattr__(self, "allowed_for_select", False)
        return self


class SqlTableDefinition(BaseModel):
    """A single approved table in a schema catalog."""

    name: Annotated[str, Field(min_length=1, description="Table name")]
    description: Annotated[str, Field(min_length=1, description="Business-friendly description")]
    columns: tuple[SqlColumnDefinition, ...]
    user_scoped: bool = False
    allowed_for_select: bool = True
    aliases: tuple[str, ...] = ()
    business_rules: tuple[str, ...] = ()
    scope_strategy: str = "direct"
    scope_description: str | None = None

    @property
    def primary_keys(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns if column.is_primary_key)

    @model_validator(mode="after")
    def _validate_table(self) -> "SqlTableDefinition":
        if not self.columns:
            raise ValueError("at least one column required")
        column_names = [column.name for column in self.columns]
        if len(column_names) != len(set(column_names)):
            raise ValueError("column names must be unique")
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("aliases must be unique")
        if self.user_scoped and self.scope_strategy == "direct":
            if not any(column.is_user_scope for column in self.columns):
                raise ValueError(
                    "user_scoped=True with direct strategy requires at least one is_user_scope=True column"
                )
        return self

    def get_column(self, name: str) -> SqlColumnDefinition | None:
        return next((column for column in self.columns if column.name == name), None)

    def selectable_columns(self) -> tuple[SqlColumnDefinition, ...]:
        return tuple(column for column in self.columns if column.allowed_for_select and not column.sensitive)

    def user_scope_columns(self) -> tuple[SqlColumnDefinition, ...]:
        return tuple(column for column in self.columns if column.is_user_scope)


class SqlRelationshipDefinition(BaseModel):
    """A relationship between two approved catalog columns."""

    left_table: Annotated[str, Field(min_length=1)]
    left_column: Annotated[str, Field(min_length=1)]
    right_table: Annotated[str, Field(min_length=1)]
    right_column: Annotated[str, Field(min_length=1)]
    relationship_type: Annotated[
        str,
        Field(pattern=r"^(one_to_one|one_to_many|many_to_one|many_to_many)$"),
    ]
    description: str | None = None

    @model_validator(mode="after")
    def _validate_refs(self) -> "SqlRelationshipDefinition":
        if self.left_table == self.right_table and self.left_column == self.right_column:
            raise ValueError("left and right references cannot be identical")
        return self


class SqlSchemaCatalog(BaseModel):
    """Complete application-supplied schema catalog."""

    catalog_name: Annotated[str, Field(min_length=1)]
    catalog_version: str
    dialect: str = "postgresql"
    tables: tuple[SqlTableDefinition, ...]
    relationships: tuple[SqlRelationshipDefinition, ...] = ()
    global_rules: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_catalog(self) -> "SqlSchemaCatalog":
        if not self.tables:
            raise ValueError("at least one table required")
        table_names = [table.name for table in self.tables]
        if len(table_names) != len(set(table_names)):
            raise ValueError("table names must be unique")
        table_map = {table.name: table for table in self.tables}
        seen_relationships = set()
        for relationship in self.relationships:
            if relationship.left_table not in table_map:
                raise ValueError(f"relationship references unknown left_table: {relationship.left_table}")
            if relationship.right_table not in table_map:
                raise ValueError(f"relationship references unknown right_table: {relationship.right_table}")
            left_table = table_map[relationship.left_table]
            right_table = table_map[relationship.right_table]
            if not left_table.get_column(relationship.left_column):
                raise ValueError(
                    f"left_column {relationship.left_column} not found in {relationship.left_table}"
                )
            if not right_table.get_column(relationship.right_column):
                raise ValueError(
                    f"right_column {relationship.right_column} not found in {relationship.right_table}"
                )
            key = (
                relationship.left_table,
                relationship.left_column,
                relationship.right_table,
                relationship.right_column,
            )
            if key in seen_relationships:
                raise ValueError(f"duplicate relationship: {key}")
            seen_relationships.add(key)
        return self

    def get_table(self, name: str) -> SqlTableDefinition:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(f"table not found: {name}")

    def allowed_table_names(self) -> frozenset[str]:
        return frozenset(table.name for table in self.tables if table.allowed_for_select)

    def allowed_columns(self, table_name: str) -> frozenset[str]:
        return frozenset(column.name for column in self.get_table(table_name).selectable_columns())

    def user_scope_columns(self, table_name: str) -> frozenset[str]:
        return frozenset(column.name for column in self.get_table(table_name).user_scope_columns())

    def get_relationships_for_table(self, table_name: str) -> tuple[SqlRelationshipDefinition, ...]:
        return tuple(
            relationship
            for relationship in self.relationships
            if relationship.left_table == table_name or relationship.right_table == table_name
        )


class GeneratedSql(BaseModel):
    """Generic SQL candidate metadata accepted by structural validation."""

    sql: Annotated[str, Field(min_length=1)]
    referenced_tables: tuple[str, ...] = ()
    referenced_columns: tuple[str, ...] = ()
    explanation: str | None = None
    confidence: float | None = None

    @field_validator("sql")
    @classmethod
    def validate_sql_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("sql must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_confidence(self) -> "GeneratedSql":
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return self


class SqlValidationError(BaseModel):
    """One structural validation error."""

    code: str
    message: str
    line: int | None = None
    column: int | None = None
    context: str | None = None


class SqlValidationResult(BaseModel):
    """Result of structural validation against an approved catalog."""

    valid: bool
    normalized_sql: str | None = None
    statement_type: str | None = None
    referenced_tables: tuple[str, ...] = ()
    referenced_columns: tuple[str, ...] = ()
    errors: tuple[SqlValidationError, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_consistency(self) -> "SqlValidationResult":
        if self.valid and self.errors:
            raise ValueError("valid=True requires no errors")
        if not self.valid and not self.errors:
            raise ValueError("valid=False requires at least one error")
        return self
