import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from . import demo
from . import push  # noqa: F401  (registers the timetable-change listener)
from .config import settings
from .routers import auth, crud, imports, platform, schedule, school, share, templates
from .services import integrity_message

log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    demo.start()  # no-op unless DEMO_MODE is on
    yield


app = FastAPI(title="SHS Class Scheduling and Teacher Loading API", version="0.1.0", lifespan=lifespan)


# Registered before CORS so it sits inside it: an unexpected error still reaches the browser with the
# CORS headers, and the user sees "something went wrong" instead of "cannot reach the server".
@app.middleware("http")
async def unexpected_errors_as_json(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Something went wrong on the server. Please try again."}, status_code=500)


print(f"Accepting requests from: {', '.join(settings.allowed_origins)}", flush=True)  # visible in the host's log
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IntegrityError)
def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse({"detail": integrity_message(exc)}, status_code=status.HTTP_409_CONFLICT)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/demo")
def demo_accounts() -> dict:
    """The public demo's test accounts and student link, when DEMO_MODE is on."""
    return demo.info()


app.include_router(auth.router)
app.include_router(school.router)
app.include_router(templates.router)
app.include_router(imports.router)
app.include_router(schedule.router)
app.include_router(share.router)
app.include_router(platform.router)
for router in crud.routers:
    app.include_router(router)
