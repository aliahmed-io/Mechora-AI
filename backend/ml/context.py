"""Optional equipment context is stored alongside rows, never used as model features."""
from datetime import datetime,timezone
import re
import pandas as pd

def machine_id(value):
    if value is None or pd.isna(value):raise ValueError('Machine IDs cannot be missing.')
    value=str(value).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}',value):raise ValueError('Machine IDs must be 1–80 letters, numbers, dots, colons, underscores, or hyphens.')
    return value

def timestamp(value):
    try:
        dt=datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError()
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError,TypeError):raise ValueError('Timestamps must be ISO 8601 with a timezone, for example 2026-10-31T09:00:00Z.')

def extract_context(frame):
    frame=frame.rename(columns=lambda c:{'Machine ID':'machine_id','Timestamp':'observed_at','timestamp':'observed_at'}.get(str(c).strip(),str(c).strip()))
    if frame.columns.duplicated().any():raise ValueError('Duplicate context columns are not allowed.')
    present=[c for c in ('machine_id','observed_at') if c in frame]
    if not present:return [{} for _ in range(len(frame))]
    if len(present)!=2:raise ValueError('Include both machine_id and observed_at to save equipment history, or omit both.')
    return [{'machine_id':machine_id(r['machine_id']),'observed_at':timestamp(r['observed_at'])} for r in frame.to_dict('records')]
