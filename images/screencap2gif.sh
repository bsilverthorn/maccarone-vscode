#!/bin/bash

# written by GPT-4

set -euxo pipefail

# Check if filename is provided
if [ $# -eq 0 ]
then
    echo "No arguments supplied. Please provide the input file path."
    exit 1
fi

INPUT_FILE="$1"
PALETTE=$(mktemp /tmp/palette.XXXXXX.png)
FILTERS="fps=10,scale=640:-1:flags=lanczos"
OUTPUT_GIF=$(mktemp /tmp/output.XXXXXX.gif)
FINAL_GIF="$(basename -- "$INPUT_FILE" .mkv).gif"

# Generate palette
ffmpeg -y -i "$INPUT_FILE" -vf "$FILTERS,palettegen" $PALETTE

# Generate gif using palette
ffmpeg -y -i "$INPUT_FILE" -i $PALETTE -filter_complex "[0:v]$FILTERS[x];[x][1:v]paletteuse" $OUTPUT_GIF

# Optimize gif using gifsicle
gifsicle --optimize=3 --delay=4 $OUTPUT_GIF > "$FINAL_GIF"

# Remove temporary files
rm $PALETTE
rm $OUTPUT_GIF

echo "Done. Output GIF is $FINAL_GIF"

