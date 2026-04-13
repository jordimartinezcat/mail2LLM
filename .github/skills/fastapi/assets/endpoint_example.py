from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class User(BaseModel):
    id: int
    name: str
    email: str

# In-memory storage for example
users_db = {}

@router.get("/users", response_model=list[User])
async def get_users():
    """Get all users"""
    return list(users_db.values())

@router.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int):
    """Get a specific user by ID"""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    return users_db[user_id]

@router.post("/users", response_model=User)
async def create_user(user: User):
    """Create a new user"""
    if user.id in users_db:
        raise HTTPException(status_code=400, detail="User already exists")
    users_db[user.id] = user
    return user

@router.put("/users/{user_id}", response_model=User)
async def update_user(user_id: int, updated_user: User):
    """Update an existing user"""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    users_db[user_id] = updated_user
    return updated_user

@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    """Delete a user"""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    del users_db[user_id]
    return {"message": "User deleted"}