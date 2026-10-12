import sys
print("exe:", sys.executable)
print("version:", sys.version)
import importlib
for m in ["bcrypt", "jose", "fastapi", "uvicorn"]:
    try:
        mod = importlib.import_module(m)
        print(m, "OK", getattr(mod, "__version__", "?"))
    except Exception as e:
        print(m, "MISSING", str(e)[:100])
