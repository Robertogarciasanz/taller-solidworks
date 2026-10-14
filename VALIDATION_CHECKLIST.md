# SOLIDWORKS Automation Tool - Validation Checklist

## Input Validation Checklist

### For all file path parameters:
- [ ] Check if parameter is not None
- [ ] Check if parameter is a string type
- [ ] Check if file exists using os.path.isfile()
- [ ] Check if file is readable
- [ ] Check file extension is correct (.stl, .sldasm, .sldprt, etc.)

### For all folder path parameters:
- [ ] Check if parameter is not None
- [ ] Check if parameter is a string type
- [ ] Check if folder exists using os.path.isdir()
- [ ] Check if folder is accessible
- [ ] Check parent folder exists if creating new folder

### For all object parameters:
- [ ] Check if parameter is not None
- [ ] Check if object is of correct type
- [ ] Validate object properties before use

## SOLIDWORKS Pre-condition Checks

### Before any operation:
- [ ] Check SOLIDWORKS is running (use _sw_abierto())
- [ ] Check COM connection successful (sw = _sw() is not None)
- [ ] Check active document exists if needed
- [ ] Check document type matches operation (SLDASM vs SLDPRT)
- [ ] Check document is saved if needed

## Exception Handling Checklist

### For all functions:
- [ ] Wrap main logic in try-except
- [ ] Catch specific exceptions (OSError, IOError, Exception)
- [ ] Log errors with logger.error()
- [ ] Print user-friendly error messages
- [ ] Return error code instead of raising

### For SOLIDWORKS operations:
- [ ] Catch COM access errors
- [ ] Handle document closed errors
- [ ] Handle permission denied errors
- [ ] Log COM error codes

### For file operations:
- [ ] Catch FileNotFoundError
- [ ] Catch PermissionError
- [ ] Catch IOError (disk full)
- [ ] Handle locked files

## Return Value Checklist

### All functions should:
- [ ] Return (bool, str) tuple
- [ ] True/"SUCCESS" on success
- [ ] False/error_code on failure
- [ ] Include meaningful error codes
- [ ] Never silently fail

## Logging Checklist

### For all operations:
- [ ] Log successful operations at INFO level
- [ ] Log errors at ERROR level
- [ ] Log warnings at WARNING level
- [ ] Include context in log messages
- [ ] Include file paths and error codes

## User Feedback Checklist

### Print messages should:
- [ ] Be clear and descriptive
- [ ] Suggest remedial action if needed
- [ ] Include file paths
- [ ] Show counts/results
- [ ] Use consistent format

## Testing Checklist

### Test scenarios:
- [ ] SOLIDWORKS closed
- [ ] Non-existent file paths
- [ ] Non-existent folder paths
- [ ] Read-only files/folders
- [ ] Invalid document types
- [ ] Missing assembly components
- [ ] Full disk (ZIP creation)
- [ ] File permission errors
- [ ] Corrupted files
- [ ] Very long file paths
- [ ] Special characters in names
- [ ] Concurrent operations

## Function-by-Function Checklist

### estado()
- [ ] Check SOLIDWORKS running
- [ ] Handle per-document errors
- [ ] Return success status

### guardar_todo()
- [ ] Check SOLIDWORKS running
- [ ] Validate document paths
- [ ] Check write permissions
- [ ] Handle per-document errors
- [ ] Return partial success info

### respaldo()
- [ ] Validate source folders exist
- [ ] Validate destination folder
- [ ] Check write permission to destination
- [ ] Test ZIP integrity
- [ ] Return integrity status

### conjunto_a_carpeta()
- [ ] Check SOLIDWORKS running
- [ ] Validate active document
- [ ] Check document type is SLDASM
- [ ] Check document is saved
- [ ] Validate destination path
- [ ] Handle copy errors
- [ ] Handle reference errors
- [ ] Return copy/redirect status

### limpiar_temporales()
- [ ] Validate folder exists
- [ ] Handle in-use files gracefully
- [ ] Return cleaned file count
- [ ] Log in-use files

### stl_a_solido()
- [ ] Validate file exists and is .stl
- [ ] Check SOLIDWORKS running
- [ ] Save original preferences
- [ ] Restore preferences on error
- [ ] Validate import result
- [ ] Return import status

### analizar_stl()
- [ ] Validate file exists and is .stl
- [ ] Handle binary and ASCII formats
- [ ] Calculate dimensions correctly
- [ ] Group bodies by connectivity
- [ ] Return analysis with status

### ejecutar_macro()
- [ ] Validate file exists
- [ ] Convert .bas/.vba if needed
- [ ] Check for Sub main routine
- [ ] Check SOLIDWORKS running
- [ ] Return execution status
- [ ] Log error codes

### generar_planos_bicicleta()
- [ ] Validate assembly file and type
- [ ] Check SOLIDWORKS running
- [ ] Create destination safely
- [ ] Handle per-part errors
- [ ] Show progress
- [ ] Return partial success info

## Documentation Checklist

- [ ] Add docstring to each function
- [ ] Document return tuple format
- [ ] List possible error codes
- [ ] Provide usage examples
- [ ] Document exceptions that may be raised
- [ ] Include validation requirements

## Code Review Checklist

Before committing changes:
- [ ] All functions have try-except
- [ ] All errors are logged
- [ ] All paths are validated
- [ ] All SOLIDWORKS checks present
- [ ] All return values typed correctly
- [ ] No silent failures
- [ ] No hard-coded error messages
- [ ] Consistent error handling pattern
- [ ] Logger properly configured
- [ ] Tests for error cases written

