from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models import Contract, User
from app.schemas import ContractCreate, ContractOut

router = APIRouter(prefix="/contracts", tags=["contracts"])


async def find_or_create_contract(db: AsyncSession, user_id: int, vendor_name: str) -> Contract:
    """Return the user's contract for this vendor, or create it if it does not exist."""
    clean_name = vendor_name.strip()

    query = select(Contract).where(
        Contract.user_id == user_id,
        func.lower(Contract.vendor_name) == clean_name.lower(),
    )
    result = await db.execute(query)
    contract = result.scalars().first()
    if contract is not None:
        return contract

    contract = Contract(user_id=user_id, vendor_name=clean_name)
    db.add(contract)
    # flush gives the new contract an id. The caller commits.
    await db.flush()
    return contract


@router.get("", response_model=list[ContractOut])
async def list_contracts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all contracts of the logged-in user."""
    query = select(Contract).where(Contract.user_id == user.id).order_by(Contract.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=ContractOut)
async def create_contract(
    data: ContractCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a contract for a vendor (or return the existing one)."""
    contract = await find_or_create_contract(db, user.id, data.vendor_name)
    if data.title is not None:
        contract.title = data.title
    await db.commit()
    await db.refresh(contract)
    return contract