import numpy as np
from scipy.stats import spearmanr

from atenex_nova.infrastructure.db.models.tables import QuantizationProfileModel
from atenex_nova.infrastructure.vector_quantization.turboquant_adapter import TurboQuantAdapter


def test_turboquant_quantize_dequantize():
    profile = QuantizationProfileModel(
        id="test-profile",
        algorithm="turboquant_prod",
        embedding_model="embeddinggemma",
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
        embedding_model="embeddinggemma",
        dimension=384,
        bit_width=4,
        rotation_seed=42,
        qjl_seed=1337,
        codebook_version="v1"
    )

    adapter = TurboQuantAdapter()
    rng = np.random.default_rng(100)

    vec_a = rng.standard_normal(384)
    vec_a /= np.linalg.norm(vec_a)

    vec_b = rng.standard_normal(384)
    vec_b /= np.linalg.norm(vec_b)

    exact_ip = float(np.dot(vec_a, vec_b))
    code_b = adapter.quantize(vec_b.tolist(), profile)
    est_ip = adapter.estimate_inner_products(vec_a.tolist(), [code_b], profile)[0]

    error = abs(exact_ip - est_ip)
    assert error < 0.20


def test_inner_product_ranking_recall():
    profile = QuantizationProfileModel(
        id="test-profile",
        algorithm="turboquant_prod",
        embedding_model="embeddinggemma",
        dimension=384,
        bit_width=4,
        rotation_seed=42,
        qjl_seed=1337,
        codebook_version="v1",
    )

    adapter = TurboQuantAdapter()
    rng = np.random.default_rng(5)
    n_vectors = 1000
    d = 384

    database = rng.standard_normal((n_vectors, d)).astype(np.float32)
    database /= np.linalg.norm(database, axis=1, keepdims=True)
    codes = [adapter.quantize(database[i].tolist(), profile) for i in range(n_vectors)]

    query = rng.standard_normal(d).astype(np.float32)
    query /= np.linalg.norm(query)

    exact_ips = database @ query
    exact_top10 = set(np.argsort(-exact_ips)[:10].tolist())

    est_ips = np.array(adapter.estimate_inner_products(query.tolist(), codes, profile))
    est_top10 = set(np.argsort(-est_ips)[:10].tolist())

    recall_at_10 = len(exact_top10 & est_top10) / 10.0
    spearman_corr = float(spearmanr(exact_ips, est_ips).correlation)

    assert recall_at_10 >= 0.90
    assert spearman_corr >= 0.95


def test_estimator_unbiased():
    profile = QuantizationProfileModel(
        id="test-profile",
        algorithm="turboquant_prod",
        embedding_model="embeddinggemma",
        dimension=384,
        bit_width=4,
        rotation_seed=42,
        qjl_seed=1337,
        codebook_version="v1",
    )

    adapter = TurboQuantAdapter()
    rng = np.random.default_rng(777)
    n_pairs = 500
    d = 384
    errors: list[float] = []

    for _ in range(n_pairs):
        q = rng.standard_normal(d).astype(np.float32)
        q /= np.linalg.norm(q)
        k = rng.standard_normal(d).astype(np.float32)
        k /= np.linalg.norm(k)

        exact_ip = float(np.dot(q, k))
        code_k = adapter.quantize(k.tolist(), profile)
        est_ip = adapter.estimate_inner_products(q.tolist(), [code_k], profile)[0]
        errors.append(est_ip - exact_ip)

    mean_error = float(np.mean(errors))
    assert abs(mean_error) < 0.05
