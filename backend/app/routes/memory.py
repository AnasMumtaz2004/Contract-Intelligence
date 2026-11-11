from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import memory as memory_store
from app.deps import get_current_user, get_db
from app.models import Memory, User
from app.schemas import MemoryCreate, MemoryOut

router = APIRouter(prefix="/memory", tags=["memory"])

MEMORY_KINDS = ["alias", "preference"]


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the aliases and preferences of the logged-in user."""
    query = select(Memory).where(Memory.user_id == user.id).order_by(Memory.id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=MemoryOut)
async def create_memory(
    data: MemoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save an alias (a nickname for a vendor) or a preference (a note about how you work)."""
    if data.kind not in MEMORY_KINDS:
        raise HTTPException(status_code=400, detail="The kind must be alias or preference")

    value = data.value.strip()
    if data.kind == "alias":
        # An alias must point at a vendor that exists
        contracts = await memory_store.load_contract_list(db, user.id)
        vendor_name = ""
        for contract in contracts:
            if contract["vendor_name"].lower() == value.lower():
                vendor_name = contract["vendor_name"]
        if vendor_name == "":
            raise HTTPException(status_code=400, detail="No contract has this vendor name")
        value = vendor_name

    return await memory_store.save_memory(db, user.id, data.kind, data.key.strip(), value)


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete one memory."""
    memory = await db.get(Memory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(status_code=404, detail="Memory not found")

    await db.delete(memory)
    await db.commit()
    return {"message": "Memory deleted"}