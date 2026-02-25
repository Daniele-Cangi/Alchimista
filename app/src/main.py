from fastapi import FastAPI

app = FastAPI(title="Alchimista API", version="0.1.0")


@app.get("/")
def root() -> dict:
    return {
        "service": "alchimista-api",
        "status": "ok",
        "message": "Recovered clean base is running"
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "healthy"}
