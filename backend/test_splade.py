import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("prithivida/Splade_PP_en_v1")
model = AutoModelForMaskedLM.from_pretrained("prithivida/Splade_PP_en_v1")
inputs = tokenizer("Hello world", return_tensors="pt")
with torch.no_grad():
    outputs = model(**inputs)
vec = torch.max(torch.log(1 + torch.relu(outputs.logits)) * inputs.attention_mask.unsqueeze(-1), dim=1)[0].squeeze()
idx = vec.nonzero().squeeze(-1)
print("SPLADE indices count:", len(idx))
