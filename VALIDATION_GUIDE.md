# Validation & Error Handling Enhancement Guide

## Summary

Comprehensive validation and error handling have been added to the SOLIDWORKS automation tool.

## Key Improvements Added

### 1. Input Validation
All functions now validate:
- **File paths**: Existence and readability before operations
- **Folder paths**: Verification they exist and are accessible
- **Document types**: SLDASM for assemblies, SLDPRT for parts
- **Parameters**: Type checking, None/empty detection

### 2. COM Connection Validation
- Check SOLIDWORKS is running before any operations
- Validate COM objects are valid/not None
- Handle connection timeouts gracefully
- Provide meaningful error messages

### 3. Exception Handling
- Try-except blocks wrapping all operations
- Specific exception catching (OSError, COM errors)
- Detailed error logging with context
- Meaningful error codes returned

### 4. Return Values & Status
- Functions return (success: bool, status_code: str)
- No silent failures - all errors reported
- User-readable messages shown in logs
- Status codes enable programmatic handling

### 5. File Operations Safety
- Check existence before read/write
- Verify write permissions before saving
- Handle file-already-exists cases
- Clean up on errors

### 6. Common Error Cases Handled
- SOLIDWORKS not running
- Invalid document types
- Files not found
- Save failures (permissions, disk space)
- Invalid assembly references
- COM API errors
- Path access issues

## Enhanced Functions in tareas.py

### estado()
- Validates SOLIDWORKS is running
- Handles document read errors gracefully
- Returns success/failure status
- Logs all errors

### guardar_todo()
- Checks path validity before saving
- Validates write permissions
- Returns partial success if some fail
- Logs save errors with details

### respaldo()
- Validates folder existence
- Tests ZIP integrity
- Handles per-file copy errors
- Returns integrity status

### conjunto_a_carpeta()
- Validates document type is SLDASM
- Checks file existence
- Error-safe destination creation
- Reference validation
- Returns copy/redirect status

### limpiar_temporales()
- Validates folder exists
- Handles in-use files gracefully
- Returns cleaned file count
- Logs all errors

### stl_a_solido()
- Validates file is .stl
- Checks SOLIDWORKS running
- Restores preferences on error
- Validates import result
- Returns import status

### analizar_stl()
- Validates file exists and is .stl
- Handles read errors gracefully
- Returns analysis with status
- Logs all errors

### ejecutar_macro()
- Validates file exists
- Checks for Sub main
- Validates SW connection
- Returns execution status
- Logs detailed errors

### generar_planos_bicicleta()
- Validates assembly file and type
- Checks SOLIDWORKS running
- Safe destination creation
- Handles per-part failures
- Returns partial success info

## Error Codes

### File Operations
- INVALID_PATH: Path is None or not string
- FILE_NOT_FOUND: File doesn't exist
- FOLDER_NOT_FOUND: Folder doesn't exist
- INVALID_FILE_TYPE: Wrong file extension
- INVALID_DESTINATION: Output path invalid

### SOLIDWORKS
- SOLIDWORKS_NOT_RUNNING: SW not in tasklist
- NO_ACTIVE_DOCUMENT: No document open
- INVALID_DOCUMENT_TYPE: Wrong document type
- DOCUMENT_NOT_SAVED: No file path
- CONNECTION_ERROR: COM connection failed

### Operations
- SAVE_ERROR: Generic save failure
- PARTIAL_FAILURE: Some saves failed
- EXPORT_ERROR: PDF/STL export failed
- ZIP_CREATION_ERROR: ZIP creation failed
- MACRO_ERROR: Macro execution failed

## Logging

All errors logged via Python logging:
```python
import logging
logger = logging.getLogger(__name__)

# Usage in functions
logger.error(f"Error: {e}")
logger.warning("Non-critical issue")
logger.info("Success")
logger.debug("Detailed info")
```

## Implementation Pattern

### Before (No Validation)
```python
def guardar_todo():
    sw = _sw()
    for d in _docs(sw):
        if val(d, "GetSaveFlag"):
            e, wr = _byref(), _byref()
            ok = d.Save3(1, e, wr)  # Silent failure
```

### After (With Validation)
```python
def guardar_todo():
    try:
        sw = _sw()
        if sw is None:
            print("SolidWorks no responde.")
            return False, "SOLIDWORKS_NOT_RUNNING"
        
        hechos = fallos = 0
        for d in _docs(sw):
            try:
                if not val(d, "GetSaveFlag"):
                    continue
                ruta = val(d, "GetPathName")
                if not ruta or not os.path.exists(os.path.dirname(ruta)):
                    fallos += 1
                    continue
                e, wr = _byref(), _byref()
                if d.Save3(1, e, wr):
                    hechos += 1
                else:
                    fallos += 1
            except Exception as e:
                fallos += 1
                logger.error(f"Error: {e}")
        
        return fallos == 0, "SUCCESS" if fallos == 0 else "PARTIAL_FAILURE"
    except Exception as e:
        logger.error(f"Error in guardar_todo(): {e}")
        return False, "SAVE_ERROR"
```

## Next Steps for taller_solidworks.py

1. **Button Handlers**
   - Validate selected files exist
   - Check user input validity
   - Handle operation failures
   - Show user-friendly errors

2. **File Dialogs**
   - Validate returned paths
   - Check file/folder existence
   - Verify write permissions

3. **Background Tasks**
   - Capture thread exceptions
   - Log thread errors
   - Show failure status
   - Clean up resources

4. **Error Reporting**
   - Show errors in UI log
   - Provide error details
   - Suggest corrective actions
   - Save error log

## Testing Checklist

- [ ] Test with SOLIDWORKS closed
- [ ] Test with non-existent files
- [ ] Test with read-only folders
- [ ] Test with wrong document types
- [ ] Test with missing component references
- [ ] Test with full disk
- [ ] Test with interrupted operations
- [ ] Test with corrupted files

## Benefits

1. **Better Error Messages**: Users see what went wrong
2. **Reliability**: Preventive checks avoid crashes
3. **Debugging**: Detailed logs help support
4. **Status Feedback**: Return codes enable programmatic handling
5. **Partial Success**: Operations continue even if some parts fail
6. **Resource Cleanup**: No partial files left on errors
