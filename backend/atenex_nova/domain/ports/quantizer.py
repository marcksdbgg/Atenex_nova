"""Domain Port: VectorQuantizerPort protocol."""

from typing import Any, Protocol


class VectorQuantizerPort(Protocol):
    """Protocol for vector quantization and dequantization."""

    def quantize(self, vector: list[float], profile: Any) -> dict[str, Any]:
        """Quantize a high-dimensional vector into compressed code.

        Args:
            vector: The input float vector to quantize.
            profile: The QuantizationProfileModel containing settings (dimension, seeds, bit width).

        Returns:
            A dictionary containing idx_blob, qjl_blob, residual_norm, vector_norm.
        """
        ...

    def dequantize(self, code: dict[str, Any], profile: Any) -> list[float]:
        """Dequantize compressed codes back into the approximate original vector.

        Args:
            code: Dictionary with idx_blob, qjl_blob, residual_norm, vector_norm.
            profile: The QuantizationProfileModel containing settings.

        Returns:
            The reconstructed float vector.
        """
        ...

    def estimate_inner_products(
        self,
        query_vector: list[float],
        codes: list[dict[str, Any]],
        profile: Any,
    ) -> list[float]:
        """Estimate inner products between a query and quantized codes without dequantization.

        Args:
            query_vector: The query float vector.
            codes: List of quantized code dicts (idx_blob, qjl_blob, residual_norm, vector_norm).
            profile: The QuantizationProfileModel containing settings.

        Returns:
            Estimated inner products, one per code, in the same order as *codes*.
        """
        ...
