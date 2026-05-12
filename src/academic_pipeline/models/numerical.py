"""Typed numerical claim model for traceability.

Every number cited in a manuscript must be backed by a NumericalProduct in the
NumericalStore. Writers cite ⟨num:label⟩ tokens that resolve to entries here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from academic_pipeline.traceability.errors import StoreIntegrityError


class NumericalProduct(BaseModel):
    """One traceable numerical claim with full provenance."""
    model_config = ConfigDict(frozen=True)

    label: str
    value: str
    unit: str | None
    formula: str
    source_run_id: str
    source_step: str
    source_artifact: str
    source_code_line: str | None
    context: str


class NumericalStore(BaseModel):
    """Frozen registry of NumericalProducts keyed by label."""
    model_config = ConfigDict(frozen=True)

    products: dict[str, NumericalProduct] = Field(default_factory=dict)

    def add(self, product: NumericalProduct) -> NumericalStore:
        """Return a new store with `product` appended. Raises StoreIntegrityError on duplicate label."""
        if product.label in self.products:
            raise StoreIntegrityError(
                f"Duplicate label: {product.label}",
                invariant_name="unique_label",
                offending_label=product.label,
            )
        return self.model_copy(update={"products": {**self.products, product.label: product}})
