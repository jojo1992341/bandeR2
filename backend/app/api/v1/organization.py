"""Studio-scoped organisation API. Every lookup includes studio_id (anti-IDOR)."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import get_current_user_payload
from app.models import (UserPreference, ProjectFolder, ProjectTag, StudioTeam, TeamMember, ProjectAssignment, StudioMembership)
router=APIRouter()
class PreferenceIn(BaseModel):
    theme:str='system'; language:str='fr'; shortcuts:dict=Field(default_factory=dict)
class NamedIn(BaseModel): name:str; description:str|None=None; color:str|None=None
class AssignmentIn(BaseModel): project_id:uuid.UUID; assignee_user_id:uuid.UUID|None=None; assignee_team_id:uuid.UUID|None=None; role:str='contributeur'
def uid(p):
    try:return uuid.UUID(str(p['sub']))
    except Exception: raise HTTPException(401,'Invalid user')
def access(db, studio, p):
    if not db.query(StudioMembership).filter_by(studio_id=studio,user_id=uid(p)).first(): raise HTTPException(404,'Organisation not found')
def out(x): return {k:str(v) if isinstance(v,uuid.UUID) else v for k,v in x.__dict__.items() if not k.startswith('_')}
@router.get('/studios/{studio_id}/preferences')
def get_preferences(studio_id:uuid.UUID,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
    access(db,studio_id,payload); x=db.query(UserPreference).filter_by(studio_id=studio_id,user_id=uid(payload)).first()
    return out(x) if x else {'studio_id':str(studio_id),'user_id':str(uid(payload)),'theme':'system','language':'fr','shortcuts':{}}
@router.put('/studios/{studio_id}/preferences')
def put_preferences(studio_id:uuid.UUID,data:PreferenceIn,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
    access(db,studio_id,payload); x=db.query(UserPreference).filter_by(studio_id=studio_id,user_id=uid(payload)).first()
    if not x:x=UserPreference(studio_id=studio_id,user_id=uid(payload));db.add(x)
    x.theme,x.language,x.shortcuts=data.theme,data.language,data.shortcuts;db.commit();db.refresh(x);return out(x)
def collection(model):
 @router.get('/studios/{studio_id}/'+model.__tablename__)
 def listing(studio_id:uuid.UUID,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
  access(db,studio_id,payload);return [out(x) for x in db.query(model).filter_by(studio_id=studio_id).all()]
 return listing
for _m in (ProjectFolder,ProjectTag,StudioTeam): collection(_m)
@router.post('/studios/{studio_id}/folders')
def create_folder(studio_id:uuid.UUID,data:NamedIn,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
 access(db,studio_id,payload); x=ProjectFolder(studio_id=studio_id,name=data.name); db.add(x); db.commit(); db.refresh(x); return out(x)
@router.post('/studios/{studio_id}/tags')
def create_tag(studio_id:uuid.UUID,data:NamedIn,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
 access(db,studio_id,payload); x=ProjectTag(studio_id=studio_id,name=data.name,color=data.color); db.add(x); db.commit(); db.refresh(x); return out(x)
@router.post('/studios/{studio_id}/teams')
def create_team(studio_id:uuid.UUID,data:NamedIn,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
 access(db,studio_id,payload);x=StudioTeam(studio_id=studio_id,name=data.name,description=data.description);db.add(x);db.commit();db.refresh(x);return out(x)
@router.post('/studios/{studio_id}/assignments')
def assign(studio_id:uuid.UUID,data:AssignmentIn,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
 access(db,studio_id,payload);x=ProjectAssignment(studio_id=studio_id,**data.model_dump());db.add(x);db.commit();db.refresh(x);return out(x)
@router.get('/studios/{studio_id}/assignments')
def assignments(studio_id:uuid.UUID,payload=Depends(get_current_user_payload),db:Session=Depends(get_db)):
 access(db,studio_id,payload);return [out(x) for x in db.query(ProjectAssignment).filter_by(studio_id=studio_id).all()]
