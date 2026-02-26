#!/usr/bin/env bash
# Strip audio from all existing videos in the uploads directory.
# Always runs ffmpeg -an on every video (safe — no-op if no audio present).

UPLOADS_DIR="/opt/skylight-photos/uploads"
VIDEO_EXTS=("mp4" "mov" "mkv" "webm")

strip_audio() {
    local file="$1"
    tmp="${file%.*}.tmp.${file##*.}"
    ffmpeg -y -i "$file" -c:v copy -an "$tmp" 2>/dev/null </dev/null
    if [ $? -eq 0 ]; then
        mv "$tmp" "$file"
        echo "  STRIPPED: $file"
    else
        rm -f "$tmp"
        echo "  FAILED: $file"
    fi
}

echo "=== Stripping audio from existing videos in $UPLOADS_DIR ==="
found=0
for ext in "${VIDEO_EXTS[@]}"; do
    while IFS= read -r -d '' f; do
        found=$((found + 1))
        strip_audio "$f"
    done < <(find "$UPLOADS_DIR" -maxdepth 1 -name "*.${ext}" -print0 2>/dev/null)
done

if [ $found -eq 0 ]; then
    echo "No video files found."
else
    echo "=== Done. Processed $found video(s). ==="
fi
