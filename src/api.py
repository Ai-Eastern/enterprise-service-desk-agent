"""FastAPI boundary for the multi-agent service-desk coordinator."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.agents.service_desk import ServiceDeskCoordinator


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    thread_id: str = Field(min_length=3, max_length=128)
    user_id: str = Field(min_length=3, max_length=64)
    query: str = Field(min_length=1, max_length=2000)
    product_id: str = Field(min_length=3, max_length=64)
    idempotency_key: str = Field(min_length=3, max_length=128)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(min_length=3, max_length=64)
    approved: bool


app = FastAPI(title="Enterprise Service Desk Agent", version="1.0.0")
_coordinator = ServiceDeskCoordinator()


def get_coordinator() -> ServiceDeskCoordinator:
    return _coordinator


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.post("/v1/tasks")
def create_task(
    request: TaskRequest,
    coordinator: ServiceDeskCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    try:
        return coordinator.handle(**request.model_dump())
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/v1/tasks/{thread_id}/approval")
def approve_task(
    thread_id: str,
    request: ApprovalRequest,
    coordinator: ServiceDeskCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    try:
        return coordinator.resume_ticket(thread_id=thread_id, **request.model_dump())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
