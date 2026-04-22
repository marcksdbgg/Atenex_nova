import json

from docling.document_converter import DocumentConverter

with open("test_sample.md", "w", encoding="utf-8") as f:
    f.write("# Hello\nThis is a test paragraph.\n\n| a | b |\n|---|---|\n| 1 | 2 |")

converter = DocumentConverter()
result = converter.convert("test_sample.md")
doc = result.document

print("Pages:", len(doc.pages))
# Use export_to_dict as it is stable
out = doc.export_to_dict()
with open("test_out.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print("Done")
