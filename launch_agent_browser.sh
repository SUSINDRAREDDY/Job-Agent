
SOURCE_PROFILE="$HOME/Library/Application Support/Google/Chrome"
AGENT_PROFILE_DIR="$HOME/job_agent_chrome_profile"

echo "Force-closing Google Chrome..."
pkill -9 -f "Google Chrome" 2>/dev/null
sleep 2

echo "Preparing agent profile..."
mkdir -p "$AGENT_PROFILE_DIR/Default"
cp "$SOURCE_PROFILE/Local State" "$AGENT_PROFILE_DIR/" 2>/dev/null

echo "Cloning 'Default' profile (this may take a moment)..."
rsync -av --delete \
  --exclude "Cache" \
  --exclude "Code Cache" \
  --exclude "Service Worker" \
  --exclude "GPUCache" \
  --exclude "DawnCache" \
  --exclude "SingletonLock" \
  --exclude "SingletonCookie" \
  --exclude "SingletonSocket" \
  "$SOURCE_PROFILE/Default/" "$AGENT_PROFILE_DIR/Default/" > /dev/null

echo "Launching Chrome (Cloned Profile) with remote debugging on port 9222..."

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$AGENT_PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check &

CHROME_PID=$!
echo "   Chrome PID: $CHROME_PID"

echo "Waiting for Chrome to be ready..."
MAX_WAIT=15
for i in $(seq 1 $MAX_WAIT); do
    if curl -s "http://127.0.0.1:9222/json/version" > /dev/null 2>&1; then
        echo ""
        echo "Chrome is ready! CDP endpoint available at http://127.0.0.1:9222"
        echo "Using cloned profile at: $AGENT_PROFILE_DIR"
        echo ""
        echo "You can now run the agent in another terminal:"
        echo "./venv/bin/python run_agent.py \"your search query\" \"https://www.indeed.com/\""
        echo ""
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo ""
echo "Warning: Chrome started but CDP endpoint not responding after ${MAX_WAIT}s."
echo "Chrome may still be loading. Wait a few more seconds before running the agent."
echo ""
echo "If problems persist, manually check: curl http://127.0.0.1:9222/json/version"
