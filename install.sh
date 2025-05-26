#!/bin/bash

# Function to check for updates
function check_for_updates() {
    echo "▶ Checking for updates..."
    if [ -d "$HOME/spoolman2slicer" ]; then
        cd $HOME/spoolman2slicer || exit 1
        git fetch
        LOCAL=$(git rev-parse @)
        REMOTE=$(git rev-parse @{u})
        if [ "$LOCAL" != "$REMOTE" ]; then
            echo "🔄 Updates available. Updating spoolman2slicer..."
            git pull
            source venv/bin/activate
            pip install -r requirements.txt --upgrade
            deactivate
            echo "✅ spoolman2slicer updated successfully."
        else
            echo "✅ spoolman2slicer is up to date."
        fi
    fi
}

# Function to select slicer and set variables
function choose_slicer() {
    while true; do
        # Prompt the user to select a slicer
        echo "Select your slicer (default: OrcaSlicer):"
        echo "1 - OrcaSlicer"
        echo "2 - PrusaSlicer"
        echo "3 - SuperSlicer"
        echo "b - Back"
        read -rp "Enter option [1-3 or b]: " slicer_option

        # Set slicer variables based on user input
        case ${slicer_option:-1} in  # Default to OrcaSlicer
            1)
                SLICER="orcaslicer"
                break
                ;;
            2)
                SLICER="prusaslicer"
                break
                ;;
            3)
                SLICER="superslicer"
                break
                ;;
            b|B)
                return 1
                ;;
            *)
                echo "❌ Invalid slicer selected. Please try again."
                ;;
        esac
    done

    # Prompt the user to enter the output directory
    echo "Enter the output directory (default: $HOME/slicers/$SLICER):"
    read -rp "Output directory: " output_dir
    OUTPUT_DIR=${output_dir:-$HOME/slicers/$SLICER} 
    echo "✅ Output directory set to: $OUTPUT_DIR"

    # Create the output directory if it doesn't exist
    if [ ! -d "$OUTPUT_DIR" ]; then
        echo "📁 Creating output directory: $OUTPUT_DIR"
        mkdir -p "$OUTPUT_DIR"
    fi

    # Prompt the user to enter the Spoolman URL
    echo "Enter the Spoolman URL (default: http://localhost:7912):"
    read -rp "Spoolman URL: " spoolman_url
    SPOOLMAN_URL=${spoolman_url:-http://localhost:7912}  # Default to localhost
    echo "✅ Spoolman URL set to: $SPOOLMAN_URL"

    # Activate the virtual environment and run the Python script
    source $HOME/spoolman2slicer/venv/bin/activate
    python $HOME/spoolman2slicer/spoolman2slicer.py -d "$OUTPUT_DIR" -s "$SLICER" -u "$SPOOLMAN_URL"
    deactivate

    echo "✅ Templates created successfully in $OUTPUT_DIR"
}

# Function to install spoolman2slicer and its dependencies
function install_spoolman2slicer() {
    echo "▶ Installing spoolman2slicer..."
    
    cd $HOME

    # Clone the repository if it doesn't already exist
    if [ ! -d "$HOME/spoolman2slicer" ]; then
        git clone https://github.com/bofh69/spoolman2slicer.git
    fi

    cd spoolman2slicer || exit 1

    # Create a virtual environment if it doesn't already exist
    if [ ! -d "$HOME/spoolman2slicer/venv" ]; then
        echo "🐍 Creating virtual environment..."
        python3 -m venv venv
    fi

    # Activate the virtual environment and install dependencies
    source $HOME/spoolman2slicer/venv/bin/activate
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
    echo "✅ Installation complete."
}

# Function to display the main menu
function show_menu() {
    clear
    echo "===== spoolman2slicer Setup ====="
    echo "1 - Install spoolman2slicer"
    echo "2 - Create templates"
    echo "0 - Exit"
    echo "================================="
    echo -n "Select an option: "
    read -r option

    # Handle user selection
    case $option in
        1)
            install_spoolman2slicer
            ;;
        2)
            choose_slicer
            ;;
        0)  
            echo "👋 Exiting..."
            exit 0
            ;;
        *)
            echo "❌ Invalid option."
            show_menu
            ;;
    esac
}

# Start the script by checking for updates and displaying the menu
check_for_updates
show_menu
