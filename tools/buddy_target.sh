#!/bin/bash
# Toggle or set the Buddy hook target.
# Usage:
#   ./tools/buddy_target.sh          # show current target
#   ./tools/buddy_target.sh sim       # route hooks to simulator (TCP)
#   ./tools/buddy_target.sh hardware  # route hooks to real device (BLE)
#   ./tools/buddy_target.sh off       # disable hooks silently

TARGET_FILE="$HOME/.buddy_target"

if [ -z "$1" ]; then
    current=$(cat "$TARGET_FILE" 2>/dev/null || echo "sim")
    echo "Current Buddy target: $current"
    echo "Options: sim | hardware | off"
else
    case "$1" in
        sim|hardware|off)
            echo "$1" > "$TARGET_FILE"
            echo "Buddy target set to: $1"
            ;;
        *)
            echo "Unknown target: $1  (use: sim | hardware | off)"
            exit 1
            ;;
    esac
fi
