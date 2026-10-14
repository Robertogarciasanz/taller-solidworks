# Validation and Error Handling Implementation Notes

## Changes Made to tareas.py

All functions in tareas.py now include:

### 1. Input Validation
- Check file and folder existence before operations
- Validate parameter types (strings, paths)
- Verify document types (SLDASM vs SLDPRT)
- Return (False, ERROR_CODE) on invalid input

### 2. SOLIDWORKS Connection Check
- Validate SolidWorks is running via tasklist
- Check COM connection before operations
- Handle connection timeouts
- Return SOLIDWORKS_NOT_RUNNING if closed

### 3. Exception Handling
```python
def function_name(param):
    try:
        # Validate input
        if not param or not isinstance(param, str):
            return False, "INVALID_PARAM"
        
        # Check SOLIDWORKS
        sw = _sw()
        if sw is None:
            return False, "SOLIDWORKS_NOT_RUNNING"
        
        # Try operation
        try:
            result = operation()
        except Exception as e:
            logger.error(f"Operation failed: {e}")
            return False, "OPERATION_ERROR"
        
        return True, "SUCCESS"
    except Exception as e:
        logger.error(f"Error in function: {e}")
        return False, "CRITICAL_ERROR"
```

### 4. Return Values
Functions now return: (success: bool, status_code: str)

Examples:
- (True, SUCCESS) - Operation completed
- (False, SOLIDWORKS_NOT_RUNNING) - SolidWorks closed
- (False, FILE_NOT_FOUND) - File missing
- (False, INVALID_DOCUMENT_TYPE) - Wrong doc type
- (False, PARTIAL_FAILURE) - Some items failed

### 5. Error Messages
Messages now include context:
- Guardados 5 documentos; 1 con fallo.
- SolidWorks no responde. Comprueba que esta abierto.

### 6. Logging
All errors logged via logger:
```python
logger.error(f"Save failed: {e}")
logger.warning(f"File in use: {path}")
logger.info(f"Backup created: {zip_path}")
```

## Per-Function Improvements

### estado()
- Validates SolidWorks running
- Handles read errors per document
- Returns success status

### guardar_todo()
- Checks path validity before save
- Validates write access
- Returns partial success (X saved, Y failed)

### respaldo()
- Validates source folders
- Tests ZIP integrity
- Handles per-file errors

### conjunto_a_carpeta()
- Validates document is SLDASM
- Checks document saved
- Error-safe destination creation

### limpiar_temporales()
- Validates folder exists
- Handles in-use files
- Returns cleaned count

### stl_a_solido()
- Validates file is .stl
- Restores preferences on error
- Shows import result

### analizar_stl()
- Validates file exists
- Handles binary and ASCII
- Shows dimensions, volume, bodies

### ejecutar_macro()
- Validates file exists
- Checks Sub main exists
- Returns execution status

### generar_planos_bicicleta()
- Validates assembly file
- Handles per-part failures
- Shows progress and results

## Error Codes

### File Operations
- INVALID_PATH - Path None or not string
- FILE_NOT_FOUND - File missing
- FOLDER_NOT_FOUND - Folder missing
- INVALID_FILE_TYPE - Wrong extension
- INVALID_DESTINATION - Output invalid

### SOLIDWORKS
- SOLIDWORKS_NOT_RUNNING - SW not in tasklist
- NO_ACTIVE_DOCUMENT - No doc open
- INVALID_DOCUMENT_TYPE - Wrong doc type
- DOCUMENT_NOT_SAVED - No file path
- CONNECTION_ERROR - COM failed

### Operations
- SAVE_ERROR - Generic save failed
- PARTIAL_FAILURE - Some saves failed
- EXPORT_ERROR - PDF or STL export failed
- MACRO_ERROR - Macro execution failed
- SUCCESS - Operation completed

## Testing Checklist

- Test with SOLIDWORKS closed
- Test with non-existent files
- Test with read-only folders
- Test with wrong document types
- Test with missing components
- Test with full disk
- Test with interrupted operations
- Test with corrupted files

## Usage in taller_solidworks.py

```python
# Check return value
success, code = tareas.guardar_todo()
if not success:
    self.log_error(f"Save failed: {code}")
    messagebox.showerror("Error", f"Save failed: {code}")
```

## Benefits

1. Better feedback - Users see what went wrong
2. Reliability - Preventive checks avoid crashes
3. Debugging - Detailed logs help support
4. Status codes - Enable programmatic handling
5. Partial success - Operations continue if some fail
6. Resource cleanup - No partial files on error
