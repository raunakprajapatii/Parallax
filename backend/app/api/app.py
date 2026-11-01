"""FastAPI application factory; dependencies are supplied by the integrating modules."""

from fastapi import FastAPI

from .chat import router


def create_app(*, orchestrator=None) -> FastAPI:
    app = FastAPI(title="Live Data Intelligence API")
    app.include_router(router)
    if orchestrator is not None:
        app.state.agent_orchestrator = orchestrator
    return app


app = create_app()
