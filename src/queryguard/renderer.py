"""Deterministic prompt rendering for approved schema catalogs."""

from queryguard.contracts import SqlSchemaCatalog


class SqlSchemaContextRenderer:
    """Render an approved schema catalog into a prompt-ready string."""

    def render(self, catalog: SqlSchemaCatalog) -> str:
        lines = [
            f"Database dialect: {catalog.dialect}",
            f"Catalog: {catalog.catalog_name} v{catalog.catalog_version}",
            "",
        ]

        for table in sorted(
            (table for table in catalog.tables if table.allowed_for_select),
            key=lambda table: table.name,
        ):
            lines.append(f"Table: {table.name}")
            if table.description:
                lines.append(f"Purpose: {table.description}.")
            lines.append("User scoped: yes" if table.user_scoped else "User scoped: no")
            for rule in table.business_rules:
                lines.append(f"Business rule: {rule}")

            lines.append("Columns:")
            for column in sorted(table.selectable_columns(), key=lambda column: column.name):
                parts = [f"- {column.name} ({column.data_type})"]
                if column.is_primary_key:
                    parts.append("primary key")
                if column.is_foreign_key and column.foreign_key_target:
                    target_name = column.foreign_key_target.split(".")[0]
                    try:
                        if catalog.get_table(target_name).allowed_for_select:
                            parts.append(f"foreign key -> {column.foreign_key_target}")
                    except KeyError:
                        pass
                if column.is_user_scope:
                    parts.append("user scope")
                if not column.nullable:
                    parts.append("not null")
                parts.append(f"{column.description}.")
                lines.append(" ".join(parts))
            lines.append("")

        if catalog.relationships:
            lines.append("Relationships:")
            for relationship in sorted(
                catalog.relationships,
                key=lambda relationship: (
                    relationship.left_table,
                    relationship.left_column,
                    relationship.right_table,
                    relationship.right_column,
                ),
            ):
                left = catalog.get_table(relationship.left_table)
                right = catalog.get_table(relationship.right_table)
                if not left.allowed_for_select or not right.allowed_for_select:
                    continue
                type_label = {
                    "one_to_one": "one-to-one",
                    "one_to_many": "one-to-many",
                    "many_to_one": "many-to-one",
                    "many_to_many": "many-to-many",
                }.get(relationship.relationship_type, relationship.relationship_type)
                lines.append(
                    f"- {relationship.left_table}.{relationship.left_column} -> "
                    f"{relationship.right_table}.{relationship.right_column} ({type_label})"
                )
                if relationship.description:
                    lines.append(f"  -- {relationship.description}")
            lines.append("")

        if catalog.global_rules:
            lines.append("Global rules:")
            lines.extend(f"- {rule}" for rule in catalog.global_rules)
            lines.append("")

        return "\n".join(lines).strip()


def render_catalog_for_prompt(catalog: SqlSchemaCatalog) -> str:
    """Render a catalog with the default deterministic renderer."""
    return SqlSchemaContextRenderer().render(catalog)
