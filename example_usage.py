#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Example demonstrating how to use spoolman_core from a GUI or other application.
This shows the new, cleaner API for programmatic use of spoolman2slicer.
"""

import os
from spoolman_core import SpoolmanConfig, SpoolmanProcessor


def custom_logger(message: str, level: str = "INFO"):
    """
    Custom logger function that could integrate with a GUI's logging system.
    
    Args:
        message: The message to log
        level: Log level (INFO, DEBUG, ERROR, etc.)
    """
    print(f"[{level}] {message}")


def example_basic_usage():
    """Example of basic usage - run once to update filaments"""
    
    # Create configuration
    config = SpoolmanConfig(
        output_dir="/path/to/slicer/filament/config",
        slicer="superslicer",  # or "orcaslicer", "prusaslicer", "slic3r"
        spoolman_url="http://localhost:7912",
        template_path="/path/to/templates",
        verbose=True,
    )
    
    # Create processor with custom logger
    processor = SpoolmanProcessor(config, logger=custom_logger)
    
    # Run once to update all filaments
    try:
        processor.run_once()
        print("Successfully updated filament configurations!")
    except Exception as e:
        print(f"Error: {e}")


def example_with_updates():
    """Example of running with WebSocket updates"""
    
    config = SpoolmanConfig(
        output_dir="/path/to/slicer/filament/config",
        slicer="orcaslicer",
        spoolman_url="http://localhost:7912",
        template_path="/path/to/templates",
        verbose=False,
        updates=True,  # Enable WebSocket updates
    )
    
    processor = SpoolmanProcessor(config, logger=custom_logger)
    
    # Run with continuous updates (this will block)
    try:
        processor.run_with_updates()
    except KeyboardInterrupt:
        print("Shutting down...")


def example_per_spool_mode():
    """Example of creating one file per spool"""
    
    config = SpoolmanConfig(
        output_dir="/path/to/slicer/filament/config",
        slicer="superslicer",
        spoolman_url="http://localhost:7912",
        template_path="/path/to/templates",
        create_per_spool="all",  # Create one file per spool
        # Other options: "least-left", "most-recent"
    )
    
    processor = SpoolmanProcessor(config, logger=custom_logger)
    processor.run_once()


def example_with_variants():
    """Example of generating configs for multiple printer variants"""
    
    config = SpoolmanConfig(
        output_dir="/path/to/slicer/filament/config",
        slicer="superslicer",
        spoolman_url="http://localhost:7912",
        template_path="/path/to/templates",
        variants="printer1,printer2",  # Generate separate files for each variant
    )
    
    processor = SpoolmanProcessor(config, logger=custom_logger)
    processor.run_once()


def example_gui_integration():
    """
    Example showing how a GUI might integrate with the processor.
    
    A GUI could:
    1. Use a configuration dialog to collect settings
    2. Create SpoolmanConfig from the settings
    3. Provide a custom logger that writes to a GUI log window
    4. Run the processor in a background thread
    5. Update a progress bar or status indicator
    """
    
    class GUILogger:
        """Example GUI logger class"""
        
        def __init__(self, gui_log_widget):
            self.log_widget = gui_log_widget
        
        def __call__(self, message: str, level: str = "INFO"):
            """Log to GUI widget"""
            # self.log_widget.append(f"[{level}] {message}")
            print(f"[GUI-{level}] {message}")
    
    # Simulate GUI settings
    gui_settings = {
        "output_dir": "/path/to/slicer/filament/config",
        "slicer": "orcaslicer",
        "spoolman_url": "http://localhost:7912",
        "template_path": "/path/to/templates",
        "verbose": True,
    }
    
    # Create config from GUI settings
    config = SpoolmanConfig(**gui_settings)
    
    # Create processor with GUI logger
    gui_logger = GUILogger(None)  # Pass actual GUI widget
    processor = SpoolmanProcessor(config, logger=gui_logger)
    
    # In a real GUI, this would run in a background thread
    try:
        processor.run_once()
    except Exception as e:
        gui_logger(f"Error: {e}", "ERROR")


def example_template_creation():
    """Example of using template_core to create templates from existing configs"""
    
    from template_core import TemplateConfig, TemplateProcessor
    
    # Create configuration
    config = TemplateConfig(
        slicer="superslicer",
        filament_path="/path/to/slicer/filament/config",
        template_path="/path/to/output/templates",
        verbose=True,
    )
    
    # Create processor
    processor = TemplateProcessor(config, logger=custom_logger)
    
    # Run to create templates
    script_dir = os.path.dirname(__file__)
    processor.run(script_dir)


if __name__ == "__main__":
    print("Spoolman Core API Examples")
    print("=" * 50)
    print("\nThese are examples showing how to use the new programmatic API.")
    print("See the function definitions for usage patterns.\n")
    
    # Uncomment to run examples (make sure to update paths first):
    # example_basic_usage()
    # example_with_updates()
    # example_per_spool_mode()
    # example_with_variants()
    # example_gui_integration()
    # example_template_creation()
