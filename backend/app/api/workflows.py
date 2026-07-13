"""REST endpoints over `WorkflowSpec` (task 8's `save_workflow_spec`/
`load_workflow_spec`/`list_workflow_specs`/`delete_workflow_spec` helpers).

These helpers already back the inner agent's tools of the same name — this
router just exposes the same freeform-text data over HTTP so Dylan can
browse/edit workflow specs by hand from the frontend's Workflows page
(task 32), without any structured field-mapping logic layered on top (see
PRD.md's "Out of scope" note on why this stays a plain text editor).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent import workflow_specs
from app.auth import require_auth
from app.models import WorkflowSpec

router = APIRouter(prefix="/api/workflow-specs", tags=["workflow-specs"])


class UpsertWorkflowSpecRequest(BaseModel):
    spec: str


def _workflow_spec_to_dict(workflow_spec: WorkflowSpec) -> dict:
    return {
        "name": workflow_spec.name,
        "spec": workflow_spec.spec,
        "created_at": workflow_spec.created_at,
        "updated_at": workflow_spec.updated_at,
    }


@router.get("")
async def list_workflow_specs(email: str = Depends(require_auth)) -> list[dict]:
    return [_workflow_spec_to_dict(spec) for spec in workflow_specs.list_workflow_specs()]


@router.get("/{name}")
async def get_workflow_spec(name: str, email: str = Depends(require_auth)) -> dict:
    workflow_spec = workflow_specs.load_workflow_spec(name)
    if workflow_spec is None:
        raise HTTPException(status_code=404, detail="Workflow spec not found")
    return _workflow_spec_to_dict(workflow_spec)


@router.put("/{name}")
async def upsert_workflow_spec(
    name: str,
    body: UpsertWorkflowSpecRequest,
    email: str = Depends(require_auth),
) -> dict:
    workflow_spec = workflow_specs.save_workflow_spec(name, body.spec)
    return _workflow_spec_to_dict(workflow_spec)


@router.delete("/{name}")
async def delete_workflow_spec(name: str, email: str = Depends(require_auth)) -> dict:
    deleted = workflow_specs.delete_workflow_spec(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow spec not found")
    return {"deleted": True}
