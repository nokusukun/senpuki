from datetime import datetime, timedelta
import re

def parse_duration(duration_str: str) -> timedelta:
    # Parse duration strings like "30s", "5m", "1h", "0.5s"
    match = re.match(r"^(\d+(\.\d*)?)([smhdw])$", duration_str)
    if not match:
        raise ValueError(f"Invalid duration string: {duration_str}")
    
    value_str = match.group(1)
    unit = match.group(3)
    
    value = float(value_str) # Allow float for seconds
    
    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    elif unit == 'w':
        return timedelta(weeks=value)
    
    return timedelta(seconds=value)

def now_utc() -> datetime:
    return datetime.now() # naive for simplicity, or use timezone.utc