from fastapi import FastAPI, HTTPException, Path, Request

app = FastAPI(
    title="secure-delivery-pipeline",
    version="0.1.0",
    docs_url=None,  # don't expose Swagger/ReDoc by default
    redoc_url=None,
)

ITEMS = {1: "alpha", 2: "bravo", 3: "charlie"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "okz"}


@app.get("/items/{item_id}")
def get_item(item_id: int = Path(gt=0, lt=1000)) -> dict[str, str | int]:
    if item_id not in ITEMS:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"id": item_id, "name": ITEMS[item_id]}
