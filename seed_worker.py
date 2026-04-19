import asyncio
import json
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core.database import AsyncSessionLocal, init_db
from app.models.worker import WorkerProfile

async def seed():
    # Ensure tables exist
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # Check if WORKER_01 exists
        statement = select(WorkerProfile).where(WorkerProfile.worker_id == "WORKER_01")
        result = await session.exec(statement)
        worker = result.first()
        
        if not worker:
            print("Creating WORKER_01 for the demo...")
            worker = WorkerProfile(
                worker_id="WORKER_01",
                locale="en-US",
                mappings=json.dumps({"CAMERA": "CAMERA"}),
                enrollment_status="none"
            )
            session.add(worker)
            await session.commit()
            print("SUCCESS: WORKER_01 created.")
        else:
            print("WORKER_01 already exists.")

if __name__ == "__main__":
    asyncio.run(seed())
