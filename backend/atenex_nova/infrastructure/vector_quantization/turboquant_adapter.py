"""Infrastructure: TurboQuantprod Quantizer Adapter."""
# ruff: noqa: N806

import logging
from typing import Any, cast

import numpy as np

from atenex_nova.domain.ports.quantizer import VectorQuantizerPort
from atenex_nova.infrastructure.vector_quantization.profile_registry import (
    TurboQuantProfileRegistry,
)

logger = logging.getLogger(__name__)

# Cache for rotation and projection matrices to avoid expensive recalculations
_MATRICES_CACHE: dict[tuple[str, int, int], np.ndarray] = {}


def get_orthogonal_matrix(dim: int, seed: int) -> np.ndarray:
    """Generate a deterministic random orthogonal matrix of shape (dim, dim) using QR decomposition."""
    key = ("rot", dim, seed)
    if key not in _MATRICES_CACHE:
        rng = np.random.default_rng(seed)
        H = rng.standard_normal((dim, dim))
        Q, R_mat = np.linalg.qr(H)
        # Ensure deterministic sign alignment for numerical stability
        d = np.diagonal(R_mat)
        ph = np.where(d >= 0, 1.0, -1.0)
        Q = Q * ph
        _MATRICES_CACHE[key] = Q
    return _MATRICES_CACHE[key]


def get_qjl_projection_matrix(dim: int, seed: int) -> np.ndarray:
    """Generate a deterministic random Gaussian projection matrix of shape (dim, dim)."""
    key = ("qjl", dim, seed)
    if key not in _MATRICES_CACHE:
        rng = np.random.default_rng(seed)
        # Normalise by sqrt(dim) to satisfy Johnson-Lindenstrauss properties
        P = rng.standard_normal((dim, dim)) / np.sqrt(dim)
        _MATRICES_CACHE[key] = P
    return _MATRICES_CACHE[key]


def pack_indices(idx: np.ndarray, bits: int) -> bytes:
    """Pack an array of small integers (0 to 2^bits - 1) into a byte array."""
    if bits == 8:
        return idx.astype(np.uint8).tobytes()
    packed = []
    current_byte = 0
    bit_offset = 0
    for val in idx:
        val = int(val) & ((1 << bits) - 1)
        current_byte |= (val << bit_offset)
        bit_offset += bits
        while bit_offset >= 8:
            packed.append(current_byte & 0xFF)
            current_byte >>= 8
            bit_offset -= 8
    if bit_offset > 0:
        packed.append(current_byte & 0xFF)
    return bytes(packed)


def unpack_indices(data: bytes, length: int, bits: int) -> np.ndarray:
    """Unpack a byte array back into an array of integers of size length."""
    if bits == 8:
        return np.frombuffer(data, dtype=np.uint8)[:length]
    unpacked = []
    current_byte = 0
    bit_offset = 0
    byte_index = 0
    mask = (1 << bits) - 1
    for _ in range(length):
        while bit_offset < bits and byte_index < len(data):
            current_byte |= (data[byte_index] << bit_offset)
            bit_offset += 8
            byte_index += 1
        val = current_byte & mask
        unpacked.append(val)
        current_byte >>= bits
        bit_offset -= bits
    return np.array(unpacked, dtype=np.int32)


class TurboQuantAdapter(VectorQuantizerPort):
    """Adapter implementing TurboQuantprod (Two-stage quantization: TurboQuantmse + QJL sign residual)."""

    def quantize(self, vector: list[float], profile: Any) -> dict[str, Any]:
        """Quantize a high-dimensional vector into index centroids and residual sign bits.

        Args:
            vector: Float vector of shape (d,).
            profile: Object containing dimension, bit_width, rotation_seed, and qjl_seed.
        """
        d = profile.dimension
        bit_width = profile.bit_width
        rotation_seed = profile.rotation_seed
        qjl_seed = profile.qjl_seed

        # 1. Normalization
        v = np.array(vector, dtype=np.float32)
        v_norm = float(np.linalg.norm(v))
        v_unit = v / v_norm if v_norm > 0 else v

        # 2. Random Rotation
        R = get_orthogonal_matrix(d, rotation_seed)
        v_rot = R @ v_unit

        # 3. Lloyd-Max Quantization (TurboQuantmse) on b - 1 bits
        centroids_bits = max(1, bit_width - 1)
        centroids = np.array(
            TurboQuantProfileRegistry.get_centroids(centroids_bits), dtype=np.float32
        )

        # Scale rotated coordinates to standard normal N(0, 1)
        u = v_rot * np.sqrt(d)

        # Vectorized closest centroid lookup
        diffs = np.abs(u[:, np.newaxis] - centroids[np.newaxis, :])
        idx = np.argmin(diffs, axis=1)

        # Reconstructed coordinates
        hat_u = centroids[idx]
        hat_v_rot = hat_u / np.sqrt(d)

        # 4. Residual 1-bit QJL Projection
        r_rot = v_rot - hat_v_rot
        residual_norm = float(np.linalg.norm(r_rot))

        P = get_qjl_projection_matrix(d, qjl_seed)
        r_proj = P @ r_rot

        # 1-bit sign packing (1 for >= 0, 0 for < 0)
        qjl_bits = (r_proj >= 0).astype(np.uint8)
        qjl_bytes = np.packbits(qjl_bits).tobytes()

        # Pack centroids
        idx_bytes = pack_indices(idx, centroids_bits)

        return {
            "idx_blob": idx_bytes,
            "qjl_blob": qjl_bytes,
            "residual_norm": residual_norm,
            "vector_norm": v_norm,
        }

    def estimate_inner_products(
        self,
        query_vector: list[float],
        codes: list[dict[str, Any]],
        profile: Any,
    ) -> list[float]:
        """Estimate inner products using the TurboQuantprod unbiased IP estimator.

        IP(q, k) ≈ ‖q‖·‖k‖·(⟨q_rot, k̂_v_rot⟩ + r_norm·√(π/(2·d))·⟨P·q_rot, signs⟩)

        where q_rot = R·(q/‖q‖), k̂_v_rot = centroids[idx]/√d, and signs ∈ {±1} from qjl_blob.
        q_rot and P·q_rot are precomputed once per query; scoring is vectorized over *codes*.
        """
        if not codes:
            return []

        d = profile.dimension
        bit_width = profile.bit_width
        rotation_seed = profile.rotation_seed
        qjl_seed = profile.qjl_seed
        centroids_bits = max(1, bit_width - 1)

        q = np.array(query_vector, dtype=np.float32)
        q_norm = float(np.linalg.norm(q))
        q_unit = q / q_norm if q_norm > 0 else np.zeros(d, dtype=np.float32)

        R = get_orthogonal_matrix(d, rotation_seed)
        P = get_qjl_projection_matrix(d, qjl_seed)
        q_rot = R @ q_unit
        p_q_rot = P @ q_rot
        qjl_scale = np.sqrt(np.pi / (2 * d))

        centroids = np.array(
            TurboQuantProfileRegistry.get_centroids(centroids_bits), dtype=np.float32
        )

        batch_size = len(codes)
        idx_matrix = np.empty((batch_size, d), dtype=np.int32)
        signs_matrix = np.empty((batch_size, d), dtype=np.float32)
        residual_norms = np.empty(batch_size, dtype=np.float32)
        vector_norms = np.empty(batch_size, dtype=np.float32)

        for i, code in enumerate(codes):
            idx_matrix[i] = unpack_indices(code["idx_blob"], d, centroids_bits)
            qjl_bits = np.unpackbits(np.frombuffer(code["qjl_blob"], dtype=np.uint8))[:d]
            signs_matrix[i] = np.where(qjl_bits == 1, 1.0, -1.0)
            residual_norms[i] = code["residual_norm"]
            vector_norms[i] = code["vector_norm"]

        hat_v_rot = centroids[idx_matrix] / np.sqrt(d)
        centroid_terms = np.einsum("ij,j->i", hat_v_rot, q_rot)
        signs_terms = signs_matrix @ p_q_rot
        rotated_ips = centroid_terms + residual_norms * qjl_scale * signs_terms
        estimated = q_norm * vector_norms * rotated_ips
        return cast(list[float], estimated.tolist())

    def dequantize(self, code: dict[str, Any], profile: Any) -> list[float]:
        """Diagnostic utility: reconstruct an approximate vector from quantized codes.

        Not used for retrieval scoring — use :meth:`estimate_inner_products` instead.
        """
        d = profile.dimension
        bit_width = profile.bit_width
        rotation_seed = profile.rotation_seed
        qjl_seed = profile.qjl_seed

        idx_blob = code["idx_blob"]
        qjl_blob = code["qjl_blob"]
        residual_norm = code["residual_norm"]
        vector_norm = code["vector_norm"]

        # 1. Reconstruct rotated centroids
        centroids_bits = max(1, bit_width - 1)
        centroids = np.array(
            TurboQuantProfileRegistry.get_centroids(centroids_bits), dtype=np.float32
        )
        idx = unpack_indices(idx_blob, d, centroids_bits)
        hat_u = centroids[idx]
        hat_v_rot = hat_u / np.sqrt(d)

        # 2. Reconstruct residual from signs using QJL transpose projection
        P = get_qjl_projection_matrix(d, qjl_seed)
        qjl_bits = np.unpackbits(np.frombuffer(qjl_blob, dtype=np.uint8))[:d]
        s = np.where(qjl_bits == 1, 1.0, -1.0)

        # Scale by target variance mapping: residual_norm * sqrt(pi / (2 * d)) * P^T @ signs
        scale = residual_norm * np.sqrt(np.pi / (2 * d))
        hat_r_rot = scale * (P.T @ s)

        # 3. Sum rotated vectors and inverse rotate using R^T
        v_rot_recon = hat_v_rot + hat_r_rot
        R = get_orthogonal_matrix(d, rotation_seed)
        v_unit_recon = R.T @ v_rot_recon

        # 4. Scale back by original norm
        v_recon = v_unit_recon * vector_norm
        return cast(list[float], v_recon.tolist())
