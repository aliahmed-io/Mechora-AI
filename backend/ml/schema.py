"""The only permitted inference features. Outcome columns never enter a pipeline."""
import numpy as np
import pandas as pd

FEATURES = ['Type', 'Air temperature [K]', 'Process temperature [K]', 'Rotational speed [rpm]', 'Torque [Nm]', 'Tool wear [min]']
NUMERIC = FEATURES[1:]
ALIASES = {'type': FEATURES[0], 'air_temperature': FEATURES[1], 'process_temperature': FEATURES[2], 'rotational_speed': FEATURES[3], 'torque': FEATURES[4], 'tool_wear': FEATURES[5]}
LIMITS = [(150, 500), (150, 700), (1, 100000), (0, 10000), (0, 100000)]

def validate_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    frame = frame.rename(columns=lambda c: ALIASES.get(str(c).strip(), str(c).strip()))
    if frame.columns.duplicated().any():
        raise ValueError('Duplicate column names are not allowed.')
    missing = [c for c in FEATURES if c not in frame]
    if missing:
        raise ValueError('Missing required columns: ' + ', '.join(missing))
    if not 1 <= len(frame) <= 10000:
        raise ValueError('Upload between 1 and 10,000 observations.')
    clean = frame[FEATURES].copy()
    clean['Type'] = clean['Type'].astype(str).str.strip().str.upper()
    if not clean['Type'].isin(['L', 'M', 'H']).all():
        raise ValueError('Type must be L, M, or H for every observation.')
    for col, (low, high) in zip(NUMERIC, LIMITS):
        original = clean[col]
        clean[col] = pd.to_numeric(original, errors='coerce')
        if clean[col].isna().any() or not np.isfinite(clean[col]).all():
            raise ValueError(f'{col}: missing, nonnumeric, or infinite values. Complete every measurement before importing.')
        if not clean[col].between(low, high).all():
            raise ValueError(f'{col} must be between {low} and {high}. Check the measurement units.')
    if (clean[FEATURES[2]] < clean[FEATURES[1]]).any():
        raise ValueError('Process temperature must be at least air temperature.')
    return clean, {'row_count':len(clean), 'missing_values':0, 'ignored_columns':[c for c in frame if c not in FEATURES], 'duplicate_rows':int(clean.duplicated().sum())}

def risk_level(probability: float, watch: float, high: float) -> str:
    return 'High' if probability >= high else 'Watch' if probability >= watch else 'Low'
