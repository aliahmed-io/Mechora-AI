import os
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Text, ForeignKey, Float, Integer
from sqlalchemy.orm import declarative_base, sessionmaker

DATA=Path(__file__).resolve().parents[1]/'data'
DATA.mkdir(exist_ok=True)
engine=create_engine(os.getenv('MECHORA_DATABASE_URL',f'sqlite:///{DATA / "mechora.db"}'),connect_args={'check_same_thread':False})
Session=sessionmaker(bind=engine)
Base=declarative_base()
class Dataset(Base):
    __tablename__='datasets'
    id=Column(String,primary_key=True); name=Column(String); created_at=Column(String); records_json=Column(Text); summary_json=Column(Text)
class Analysis(Base):
    __tablename__='analyses'
    id=Column(String,primary_key=True); dataset_id=Column(String,ForeignKey('datasets.id')); created_at=Column(String); model_version=Column(String); watch=Column(String); high=Column(String); predictions_json=Column(Text)
class ModelMetadata(Base):
    __tablename__='model_metadata'
    id=Column(String,primary_key=True); metadata_json=Column(Text)
class Report(Base):
    __tablename__='reports'
    id=Column(String,primary_key=True); analysis_id=Column(String,ForeignKey('analyses.id')); created_at=Column(String); name=Column(String)
class Machine(Base):
    __tablename__='machines'
    id=Column(String,primary_key=True); name=Column(String,nullable=False); location=Column(String,default=''); created_at=Column(String)
class Reading(Base):
    __tablename__='readings'
    id=Column(String,primary_key=True); machine_id=Column(String,ForeignKey('machines.id'),index=True); observed_at=Column(String,index=True)
    measurements_json=Column(Text); probability=Column(Float); risk=Column(String); model_version=Column(String)
    source=Column(String); analysis_id=Column(String,nullable=True); record_id=Column(String,nullable=True); input_key=Column(String,unique=True)
class Replay(Base):
    __tablename__='replays'
    id=Column(String,primary_key=True); dataset_id=Column(String,ForeignKey('datasets.id')); machine_id=Column(String,ForeignKey('machines.id'))
    cursor=Column(Integer,default=0); status=Column(String,default='paused'); speed=Column(Float,default=1); started_at=Column(String); model_version=Column(String); error=Column(Text,default='')
class Investigation(Base):
    __tablename__='investigations'
    id=Column(String,primary_key=True); reading_id=Column(String,nullable=True); analysis_id=Column(String,nullable=True); record_id=Column(String,nullable=True)
    machine_id=Column(String,nullable=True,index=True); title=Column(String); status=Column(String,default='open'); outcome=Column(String,default='unconfirmed')
    created_at=Column(String); updated_at=Column(String); resolved_at=Column(String,nullable=True); snapshot_json=Column(Text); notes_json=Column(Text,default='[]')
class TrainingRun(Base):
    __tablename__='training_runs'
    id=Column(String,primary_key=True); name=Column(String); strategy=Column(String); status=Column(String); created_at=Column(String)
    summary_json=Column(Text); metrics_json=Column(Text,nullable=True); error=Column(Text,default='')
Base.metadata.create_all(engine)
