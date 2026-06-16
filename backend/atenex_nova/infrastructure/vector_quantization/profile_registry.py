"""Infrastructure: TurboQuant Profile Registry."""

from typing import Any, ClassVar


class TurboQuantProfileRegistry:
    """Registry for TurboQuant profile configurations (Lite, Standard, Advanced)."""

    # Precomputed standard normal N(0, 1) Lloyd-Max centroids for b-1 bits:
    # 1-bit quantization (M=2 centroids):
    CENTROIDS_1_BIT: ClassVar[list[float]] = [-0.79788, 0.79788]

    # 2-bit quantization (M=4 centroids):
    CENTROIDS_2_BIT: ClassVar[list[float]] = [-1.5101, -0.4528, 0.4528, 1.5101]

    # 3-bit quantization (M=8 centroids):
    CENTROIDS_3_BIT: ClassVar[list[float]] = [-2.1519, -1.3439, -0.7560, -0.2451, 0.2451, 0.7560, 1.3439, 2.1519]

    @classmethod
    def get_centroids(cls, bits: int) -> list[float]:
        """Get precomputed Lloyd-Max centroids for b - 1 bits.

        Args:
            bits: The number of bits for Lloyd-Max quantizer (b - 1).

        Returns:
            List of float centroids.
        """
        centroids_map = {
            1: cls.CENTROIDS_1_BIT,
            2: cls.CENTROIDS_2_BIT,
            3: cls.CENTROIDS_3_BIT,
        }
        return centroids_map.get(bits, cls.CENTROIDS_3_BIT)

    @classmethod
    def get_profile_defaults(cls, bit_width: int) -> dict[str, Any]:
        """Get default parameters for a given target bit width (b).

        Args:
            bit_width: The total target bit width (2, 3, or 4).

        Returns:
            Dictionary containing rotation_seed, qjl_seed, and centroids_bits.
        """
        # Centroids bit-width is b - 1.
        centroids_bits = max(1, bit_width - 1)
        return {
            "rotation_seed": 42,
            "qjl_seed": 1337,
            "centroids_bits": centroids_bits,
            "codebook_version": f"v1-b{bit_width}",
        }
