# Programmatic API for GUI Integration

This document describes the new programmatic API for using spoolman2slicer from GUI applications or other Python code.

## Overview

The refactored code provides clean, reusable modules that separate business logic from CLI concerns:

- **`spoolman_core.py`**: Core logic for fetching from Spoolman and generating slicer configs
- **`template_core.py`**: Core logic for creating template files from existing configs
- **`example_usage.py`**: Examples showing how to use the API

The original CLI programs (`spoolman2slicer.py` and `create_template_files.py`) remain unchanged and fully functional.

## Key Classes

### SpoolmanConfig (spoolman_core)

Configuration dataclass for spoolman2slicer operations:

```python
from spoolman_core import SpoolmanConfig

config = SpoolmanConfig(
    output_dir="/path/to/slicer/filament/config",  # Required: Output directory
    slicer="superslicer",                          # Required: Slicer type
    spoolman_url="http://localhost:7912",          # Required: Spoolman URL
    template_path="/path/to/templates",            # Required: Template directory
    verbose=False,                                 # Optional: Verbose logging
    updates=False,                                 # Optional: Enable WebSocket updates
    variants="",                                   # Optional: Comma-separated variants
    delete_all=False,                              # Optional: Delete all configs first
    create_per_spool=None,                         # Optional: "all", "least-left", or "most-recent"
)
```

### SpoolmanProcessor (spoolman_core)

Main processor for generating slicer configurations:

```python
from spoolman_core import SpoolmanProcessor

# Create processor with optional custom logger
processor = SpoolmanProcessor(config, logger=my_logger_function)

# Run once to update configurations
processor.run_once()

# Or run with continuous WebSocket updates
processor.run_with_updates()
```

### TemplateConfig (template_core)

Configuration for template creation:

```python
from template_core import TemplateConfig

config = TemplateConfig(
    slicer="superslicer",                          # Required: Slicer type
    filament_path="/path/to/slicer/filament",      # Required: Existing config dir
    template_path="/path/to/output/templates",     # Required: Template output dir
    verbose=False,                                 # Optional: Verbose logging
    delete_all=False,                              # Optional: Delete all templates first
)
```

### TemplateProcessor (template_core)

Processor for creating template files:

```python
from template_core import TemplateProcessor

processor = TemplateProcessor(config, logger=my_logger_function)
processor.run(script_dir)
```

## Custom Logger

Both processors accept an optional `logger` parameter that should be a callable with this signature:

```python
def my_logger(message: str, level: str = "INFO"):
    """
    Custom logger function.
    
    Args:
        message: The log message
        level: Log level ("INFO", "DEBUG", "ERROR", etc.)
    """
    # Your logging implementation here
    pass
```

This allows you to integrate with any logging system, including GUI log widgets.

## Example: Basic Usage

```python
from spoolman_core import SpoolmanConfig, SpoolmanProcessor

# Configure
config = SpoolmanConfig(
    output_dir="/path/to/slicer/filament/config",
    slicer="superslicer",
    spoolman_url="http://localhost:7912",
    template_path="/path/to/templates",
    verbose=True,
)

# Process
processor = SpoolmanProcessor(config)
processor.run_once()
```

## Example: GUI Integration

```python
from spoolman_core import SpoolmanConfig, SpoolmanProcessor
import threading

class MyGUI:
    def __init__(self):
        self.log_widget = ...  # Your GUI log widget
    
    def log_message(self, message: str, level: str = "INFO"):
        """Logger that writes to GUI"""
        self.log_widget.append(f"[{level}] {message}")
    
    def start_sync(self):
        """Start syncing with Spoolman"""
        # Get settings from GUI
        config = SpoolmanConfig(
            output_dir=self.output_dir_entry.get(),
            slicer=self.slicer_combo.get(),
            spoolman_url=self.url_entry.get(),
            template_path=self.template_path_entry.get(),
            verbose=self.verbose_checkbox.get(),
        )
        
        # Create processor with GUI logger
        processor = SpoolmanProcessor(config, logger=self.log_message)
        
        # Run in background thread
        def run():
            try:
                processor.run_once()
                self.log_message("Sync complete!", "INFO")
            except Exception as e:
                self.log_message(f"Error: {e}", "ERROR")
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
```

## Example: Creating Templates

```python
from template_core import TemplateConfig, TemplateProcessor
import os

config = TemplateConfig(
    slicer="superslicer",
    filament_path="/path/to/existing/configs",
    template_path="/path/to/output/templates",
    verbose=True,
)

processor = TemplateProcessor(config)
script_dir = os.path.dirname(__file__)
processor.run(script_dir)
```

## Benefits of the New API

1. **No CLI Dependencies**: No dependency on `argparse` or global state
2. **Clean Configuration**: Configuration is explicit via dataclasses
3. **Flexible Logging**: Integrate with any logging system
4. **Thread-Safe**: Can be used in background threads without issues
5. **Testable**: Easy to test without mocking command-line arguments
6. **Reusable**: Can create multiple processor instances with different configs

## Backward Compatibility

The original CLI programs remain fully functional and unchanged:
- `spoolman2slicer.py` - Original CLI interface
- `create_template_files.py` - Original template creation CLI

All existing tests pass without modification.

## Further Examples

See `example_usage.py` for more detailed examples including:
- WebSocket updates mode
- Per-spool mode variations
- Multi-printer variants
- GUI integration patterns
