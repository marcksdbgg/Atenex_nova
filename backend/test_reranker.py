from sentence_transformers import CrossEncoder

try:
    model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
    scores = model.predict([("query 1", "passage 1"), ("query 1", "passage 2")])
    print("Scores:", scores)
except Exception as exc:
    print("Error:", exc)
