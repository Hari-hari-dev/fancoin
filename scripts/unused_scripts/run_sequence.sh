#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Enable debug mode (optional, uncomment for verbose output)
# set -x

# Define log file
LOG_FILE="batch_run_$(date +%Y%m%d_%H%M%S).log"

# Function to log messages
log() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Start Logging
log "Batch execution of Solana Python scripts started."

# Activate the virtual environment
#log "Activating virtual environment..."
#source ./venv/bin/activate
rm -rf ./player_keys
# Check if activation was successful
if [ $? -ne 0 ]; then
    log "Failed to activate virtual environment."
    exit 1
fi

# List of Python scripts to execute in order
SCRIPTS=(
    "1_val_pay_vals_from_localwallet.py"
    "2_scraper2.py"
    "3_val1_init.py"
    "4_val2_init.py"
    "5_mass_signup.py"
    "6_punch_in.py"
    "7_punch_in2.py"
    #"8_val1_player_scrape_and_post_mvp.py"
    #"9_val2_player_scrape_and_post_mvp.py"
    
)

# Iterate over each script and execute
for script in "${SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        log "Executing $script..."
        python3 "$script" 2>&1 | tee -a "$LOG_FILE"
        if [ ${PIPESTATUS[0]} -eq 0 ]; then
            log "$script executed successfully."
        else
            log "Error occurred while executing $script. Check the log for details."
            deactivate
            exit 1
        fi
    else
        log "Script $script not found. Skipping."
    fi
done

# Deactivate the virtual environment
deactivate
log "Virtual environment deactivated."

log "Batch execution of Solana Python scripts completed successfully."
