import numpy as np

from atenex_nova.infrastructure.db.models.tables import QuantizationProfileModel
from atenex_nova.infrastructure.vector_quantization.turboquant_adapter import TurboQuantAdapter


def test_turboquant_quantize_dequantize():
    profile = QuantizationProfileModel(
        id="test-profile",
        algorithm="turboquant_prod",
        embedding_model="google/embeddinggemma-300m",
        dimension=384,
        bit_width=4,
        rotation_seed=42,
        qjl_seed=1337,
        codebook_version="v1"
    )

    adapter = TurboQuantAdapter()

    # Generate a random unit-ish vector
    rng = np.random.default_rng(42)
    original_vector = rng.standard_normal(384).tolist()

    # Quantize
    code = adapter.quantize(original_vector, profile)
    assert "idx_blob" in code
    assert "qjl_blob" in code
    assert "residual_norm" in code
    assert "vector_norm" in code

    # Dequantize
    reconstructed_vector = adapter.dequantize(code, profile)

    # Verify shape and type
    assert len(reconstructed_vector) == 384

    # Verify cosine similarity is high (since we quantize residual with QJL, similarity should be > 0.8)
    v_orig = np.array(original_vector)
    v_recon = np.array(reconstructed_vector)
    cos_sim = np.dot(v_orig, v_recon) / (np.linalg.norm(v_orig) * np.linalg.norm(v_recon))
    assert cos_sim > 0.75


def test_turboquant_inner_product_estimation():
    profile = QuantizationProfileModel(
        id="test-profile",
        algorithm="turboquant_prod",
        embedding_model="google/embeddinggemma-300m",
        dimension=384,
        bit_width=4,
        rotation_seed=42,
        qjl_seed=1337,
        codebook_version="v1"
    )

    adapter = TurboQuantAdapter()
    rng = np.random.default_rng(100)

    # Generate random normalized vectors
    vec_a = rng.standard_normal(384)
    vec_a /= np.linalg.norm(vec_a)

    vec_b = rng.standard_normal(384)
    vec_b /= np.linalg.norm(vec_b)

    # Exact inner product
    exact_ip = float(np.dot(vec_a, vec_b))

    # Quantize B
    code_b = adapter.quantize(vec_b.tolist(), profile)

    # Dequantize B
    recon_b = adapter.dequantize(code_b, profile)

    # Estimated inner product via dequantized vector
    est_ip = float(np.dot(vec_a, recon_b))

    # Difference should be small (usually within 0.15 for 4-bit)
    error = abs(exact_ip - est_ip)
    assert error < 0.20
