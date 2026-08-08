from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str


class ProjectRead(BaseModel):
    id: int
    title: str

    class Config:
        from_attributes = True
