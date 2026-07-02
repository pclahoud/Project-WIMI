"""
Shared helpers for the WIMI bridge layer.
Extracted from bridge.py during Layer 2 decomposition.
"""

import json
from datetime import date, datetime
from typing import Any


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects"""
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def serialize_response(success: bool, data: Any = None, error: str = None) -> str:
    """
    Create a standardized JSON response.

    Args:
        success: Whether the operation was successful
        data: The data to return (if successful)
        error: Error message (if failed)

    Returns:
        JSON string with response
    """
    response = {'success': success}
    if data is not None:
        response['data'] = data
    if error is not None:
        response['error'] = error
    return json.dumps(response, cls=DateTimeEncoder)
