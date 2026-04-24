"""
Data normalizer helper to handle both old and new lot data structures.

Supports:
- Old format: loteGeo (camelCase), optional nested 'info' object
- New format: lote_geo (snake_case), nested 'metadata' object, 'bounds_utm', etc.
"""

def normalize_lot_data(lot_obj):
    """
    Normalize a lot object to a consistent format.
    
    Handles both old and new data structures:
    - Old: {zona, setor, loteGeo, quadra, lote, info: {...}}
    - New: {inscricao, metadata: {...}, zona, setor, lote_geo, bounds_utm: {...}}
    
    Args:
        lot_obj (dict): Raw lot data in either format
        
    Returns:
        dict: Normalized data with keys: zona, setor, loteGeo, quadra, lote
              Returns None values for missing fields
    """
    normalized = {}
    
    # Helper to safely get nested values
    def get_nested(obj, *keys):
        """Safely navigate nested dictionary keys."""
        current = obj
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
        return current
    
    # Extract zona - try multiple sources
    normalized['zona'] = (
        lot_obj.get('zona') or 
        get_nested(lot_obj, 'metadata', 'zona') or
        get_nested(lot_obj, 'info', 'zona')
    )
    
    # Extract setor - try multiple sources
    normalized['setor'] = (
        lot_obj.get('setor') or 
        get_nested(lot_obj, 'metadata', 'setor') or
        get_nested(lot_obj, 'info', 'setor')
    )
    
    # Extract loteGeo - handle both camelCase and snake_case
    # Priority: top-level, then metadata, then info
    normalized['loteGeo'] = (
        lot_obj.get('loteGeo') or  # Old format
        lot_obj.get('lote_geo') or  # New format
        get_nested(lot_obj, 'metadata', 'lote') or  # New format nested
        get_nested(lot_obj, 'metadata', 'lote_geo') or
        get_nested(lot_obj, 'info', 'loteGeo') or  # Old format nested
        get_nested(lot_obj, 'info', 'lote_geo')
    )
    
    # Extract quadra
    normalized['quadra'] = (
        lot_obj.get('quadra') or 
        get_nested(lot_obj, 'metadata', 'quadra') or
        get_nested(lot_obj, 'info', 'quadra') or
        ''  # Default to empty string if not found
    )
    
    # Extract lote (display name)
    normalized['lote'] = (
        lot_obj.get('lote') or 
        get_nested(lot_obj, 'metadata', 'lote') or
        get_nested(lot_obj, 'info', 'lote') or
        normalized['loteGeo'] or  # Fallback to loteGeo if lote name not found
        '?'
    )
    
    # Extract inscricao if available (useful for some operations)
    normalized['inscricao'] = (
        lot_obj.get('inscricao') or
        get_nested(lot_obj, 'metadata', 'inscricao')
    )
    
    return normalized


def is_valid_lot(lot_obj):
    """
    Check if a lot object has the minimum required fields for processing.
    
    Args:
        lot_obj (dict): Raw lot data
        
    Returns:
        bool: True if lot has zona, setor, and loteGeo
    """
    normalized = normalize_lot_data(lot_obj)
    return bool(normalized['zona'] and normalized['setor'] and normalized['loteGeo'])
