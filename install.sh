#!/bin/bash
# =============================================================================
# spoolman2slicer-setup.sh
#
# Author: Jose Tomas Milla <jtomas1298@gmail.com>
# Year: 2025
#
# Description:
#   Interactive Bash script to install and configure spoolman2slicer.
#   - Installs or updates spoolman2slicer and its Python dependencies.
#   - Copies slicer templates to user config directory (~/.config/spoolman2slicer).
#   - Generates filament configuration files for OrcaSlicer, PrusaSlicer, or SuperSlicer.
#   - Stores user preferences for slicer, output folder, and Spoolman URL.
#
# Usage:
#   Run the script in a terminal: ./spoolman2slicer-setup.sh
#   Follow the interactive menu to install or create filament config files.
#
# License:
#   SPDX-License-Identifier: MIT
#
# Notes:
#   - Requires Python 3 and git installed.
#   - The script creates a virtual environment for spoolman2slicer dependencies.
#   - Before creating filament configs, ensure templates exist by installing spoolman2slicer.
# =============================================================================


# =========================
# Colors
# =========================
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No color

# =========================
# Directories
# =========================
CONFIG_DIR="$HOME/.config/spoolman2slicer"   # Stores user preferences
SP_DIR="$HOME/spoolman2slicer"               # spoolman2slicer source code directory

# Config file to save user preferences
CONFIG_FILE="$CONFIG_DIR/config.ini"
mkdir -p "$CONFIG_DIR"

# Load previous user settings if available
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

# =========================
# Function: Check for updates
# =========================
function check_for_updates() {
    echo -e "${BLUE}Checking for updates...${NC}"
    if [ -d "$SP_DIR" ]; then
        cd "$SP_DIR" || exit 1
        git fetch
        LOCAL=$(git rev-parse @)
        REMOTE=$(git rev-parse @{u})
        if [ "$LOCAL" != "$REMOTE" ]; then
            echo -e "${BLUE}Updates available. Resetting local changes and pulling latest version...${NC}"
            git reset --hard HEAD      
            git clean -fd              
            git pull --rebase
            source venv/bin/activate
            pip install -r requirements.txt --upgrade
            deactivate
            echo -e "${GREEN}spoolman2slicer updated successfully.${NC}"
        else
            echo -e "${GREEN}spoolman2slicer is up to date.${NC}"
        fi
    fi
}

# =========================
# Function: Install spoolman2slicer
# =========================
function install_spoolman2slicer() {
    echo -e "${BLUE}Installing or updating spoolman2slicer...${NC}"
    cd "$HOME"

    [ ! -d "$SP_DIR" ] && git clone https://github.com/bofh69/spoolman2slicer.git
    cd "$SP_DIR" || exit 1

    [ ! -d "$SP_DIR/venv" ] && python3 -m venv venv

    source "$SP_DIR/venv/bin/activate"
    echo -e "${BLUE}Installing dependencies...${NC}"
    pip install -r requirements.txt
    deactivate

    for slicer in orcaslicer prusaslicer superslicer; do
        mkdir -p "$CONFIG_DIR/templates-$slicer"
        cp -r "$SP_DIR/templates-$slicer/"* "$CONFIG_DIR/templates-$slicer/" 2>/dev/null || true
    done

    echo -e "${GREEN}spoolman2slicer installed successfully.${NC}"
    read -rp "Press Enter to return to the main menu..."
}

# =========================
# Function: Create filament config files
# =========================
function choose_slicer() {

    while true; do
        echo -e "${BLUE}Select your slicer (default: ${last_slicer:-OrcaSlicer}):${NC}"
        echo "1 - OrcaSlicer"
        echo "2 - PrusaSlicer"
        echo "3 - SuperSlicer"
        echo "b - Back"
        read -rp "Enter option [1-3 or b]: " slicer_option

        case ${slicer_option:-1} in
            1) SLICER="orcaslicer"; break ;;
            2) SLICER="prusaslicer"; break ;;
            3) SLICER="superslicer"; break ;;
            b|B) return 1 ;;
            *) echo -e "${RED}Invalid slicer selected. Please try again.${NC}" ;;
        esac
    done

    # Check if templates exist
    TEMPLATE_DIR="$CONFIG_DIR/templates-$SLICER"
    if [ ! -d "$TEMPLATE_DIR" ] || [ -z "$(ls -A "$TEMPLATE_DIR" 2>/dev/null)" ]; then
        echo -e "${RED}No templates found for $SLICER.${NC}"
        echo -e "Please run option 1 (Install spoolman2slicer) first to install templates."
        read -rp "Press Enter to return to the main menu..."
        return 1
    fi

    # Output directory inside $HOME
    while true; do
        read -rp "Enter the output subfolder (inside your home, default: ${last_output_dir:-filament}): " folder
        SUBFOLDER=${folder:-${last_output_dir:-filament}}
        SUBFOLDER="${SUBFOLDER%/}"  # Remove trailing slash
        OUTPUT_DIR="$HOME/$SUBFOLDER"

        if mkdir -p "$OUTPUT_DIR" 2>/dev/null; then
            echo -e "${GREEN}Output directory set to: $OUTPUT_DIR${NC}"
            break
        else
            echo -e "\nCannot create directory '$OUTPUT_DIR'. Please choose another subfolder."
        fi
    done

    # Ask for Spoolman URL without validation
    read -rp "Enter the Spoolman URL (default: ${last_spoolman_url:-http://localhost:7912}): " spoolman_url
    SPOOLMAN_URL=${spoolman_url:-${last_spoolman_url:-http://localhost:7912}}
    echo -e "${GREEN}Spoolman URL set to: $SPOOLMAN_URL${NC}"

    # Save settings as defaults for next execution
    {
        echo "last_slicer=$SLICER"
        echo "last_output_dir=$SUBFOLDER"
        echo "last_spoolman_url=$SPOOLMAN_URL"
    } > "$CONFIG_FILE"

    # Run Python script
    source "$SP_DIR/venv/bin/activate"
    python "$SP_DIR/spoolman2slicer.py" -d "$OUTPUT_DIR" -s "$SLICER" -u "$SPOOLMAN_URL"
    PYTHON_EXIT_CODE=$?
    deactivate

    if [ $PYTHON_EXIT_CODE -eq 0 ]; then
        echo -e "\n${GREEN}Filament configuration files created successfully in $OUTPUT_DIR${NC}"
    else
        echo -e "\n${RED}Error: Python script failed. Filament configuration files were not created.${NC}"
    fi

    read -rp "Press Enter to return to the main menu..."
}

# =========================
# Function: Uninstall spoolman2slicer (clean everything)
# =========================
function uninstall_spoolman2slicer() {
    echo -e "${RED}WARNING:${NC} This will completely remove spoolman2slicer, including source code, dependencies, configuration and generated profiles."
    read -rp "Do you want to proceed with full uninstallation? (y/N): " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        
        # Remove spoolman2slicer source directory
        if [ -d "$SP_DIR" ]; then
            rm -rf "$SP_DIR"
            echo -e "${GREEN}spoolman2slicer source directory removed (${SP_DIR}).${NC}"
        else
            echo -e "${YELLOW}No spoolman2slicer found in ${SP_DIR}.${NC}"
        fi

        # Remove configuration directory
        if [ -d "$CONFIG_DIR" ]; then
            rm -rf "$CONFIG_DIR"
            echo -e "${GREEN}Configuration removed (${CONFIG_DIR}).${NC}"
        else
            echo -e "${YELLOW}No configuration found in ${CONFIG_DIR}.${NC}"
        fi

        # Remove last output directory if defined
        if [ -n "$last_output_dir" ] && [ -d "$HOME/$last_output_dir" ]; then
            rm -rf "$HOME/$last_output_dir"
            echo -e "${GREEN}Filament profiles removed (${HOME}/${last_output_dir}).${NC}"
        fi

        echo -e "\n${GREEN}Full uninstallation completed.${NC}"
    else
        echo -e "${YELLOW}Uninstallation canceled.${NC}"
    fi

    read -rp "Press Enter to exit..."
    exit 0
}

# =========================
# Function: Main menu
# =========================
/*************  ✨ Windsurf Command ⭐  *************/
# Show the main menu of spoolman2slicer setup script
#
# This function shows the main menu of the spoolman2slicer setup script.
# It will continue to show the menu until the user selects the "Exit" option.
#
# The menu options are:
#   1. Install spoolman2slicer
#   2. Create filament configuration files
#   3. Uninstall spoolman2slicer (clean everything)
/*******  c84b53e3-0ca4-4e7a-9079-8b6d54356309  *******/
function show_menu() {
    while true; do
        clear
        echo "===== spoolman2slicer Setup ====="
        echo "1 - Install spoolman2slicer"
        echo "2 - Create filament configuration files"
        echo "3 - Uninstall spoolman2slicer (clean everything)"
        echo "0 - Exit"
        echo "================================="
        read -rp "Select an option: " option

        case $option in
            1) install_spoolman2slicer ;;
            2) choose_slicer ;;
            3) uninstall_spoolman2slicer ;;
            0) echo "Exiting..."; exit 0 ;;
            *) echo -e "${RED}Invalid option.${NC}"; read -rp "Press Enter to continue..." ;;
        esac
    done
}

# =========================
# Script start
# =========================
check_for_updates
show_menu
