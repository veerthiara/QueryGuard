"""QueryGuard structural validation package.

Internal implementation modules:
- parsing: SQLGlot parse invocation, dialect mapping, empty/multi-statement checks
- statements: Statement-level checks (read-only, write/DDL rejection, wildcards, system schemas, dangerous functions)
- tables: Physical table resolution and catalog validation
- columns: Column resolution (qualified/unqualified) and catalog validation
- scopes: SQLGlot scope helpers (alias maps, CTE/derived identification)
- lineage: Expression-to-physical-source lineage computation
- metadata: LLM-reported vs SQLGlot-derived metadata comparison
- service: Orchestration (SqlValidationService)

Public API:
    SqlValidationService
"""

from queryguard.validation.service import SqlValidationService

__all__ = ["SqlValidationService"]
