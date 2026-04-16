from pymongo import MongoClient
import json

MONGO_URI = "mongodb+srv://nia_user:viaindustrial1234@cluster0.xucn3sc.mongodb.net/nia?retryWrites=true&w=majority"

client = MongoClient(MONGO_URI)
db = client["nia"]
collection = db["products_catalog"]

# 📦 Cargar JSON
with open("productos.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# 🚀 Insertar por bloques
batch_size = 1000

for i in range(0, len(data), batch_size):
    batch = data[i:i + batch_size]
    collection.insert_many(batch)
    print(f"Insertados {i + len(batch)} registros")

print("✅ Datos cargados completamente")