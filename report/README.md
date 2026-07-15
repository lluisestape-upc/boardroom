# BoardRoom Review Viewer (`report/` Frontend Dashboard)

This directory contains the self-contained, static, interactive review viewer dashboard for the BoardRoom multi-agent PCB design review system.

## Folder Structure

```
report/
├── README.md                 # This documentation
├── QUESTIONS.md              # Feedback on schema contracts & suggestions
├── dist/                     # Production-ready static site files (served by backend)
│   ├── index.html            # Dashboard HTML structure & templates
│   ├── style.css             # Premium glassmorphism dark-theme layout rules
│   ├── app.js                # Core controller, physics graph engine, & overlay math
│   ├── sample_data.js        # Offline wrapper binding sample review to global variable
│   └── board.png             # Bounding-box background board image render
└── sample/                   # Standalone developer/test sample files
    ├── review.sample.json    # Standard JSON complying with finding.schema.json
    └── board.png             # Copy of the sample PCB board image render
```

## How to Run & Preview

This viewer is built with pure Vanilla HTML5/CSS3/ES6 and **zero external dependencies or runtime CDN connections**. This guarantees it functions 100% offline and is fast to load.

### Option 1: Standalone (Double-click `file://`)
Simply open `report/dist/index.html` directly in any web browser. 
- **Bypassing CORS**: The browser blocks `fetch('review.json')` when run on the `file://` protocol. We resolved this by pre-compiling `review.sample.json` as a local script (`sample_data.js`) which binds to a global variable. The dashboard detects and boots from this data automatically.
- **Viewing custom sessions**: If you have a different `review.json` output file from a backend run, simply drag and drop it onto the dashboard's sidebar uploader or click the uploader block to select it. The page will dynamically re-parse and refresh all 5 views instantly.

### Option 2: Local Dev Server
If you prefer to run it using a local HTTP server, execute one of the following commands in this directory:
```bash
# Using Python
python -m http.server -d report/dist 8000

# Using Node.js
npx serve report/dist
```
Then navigate to [http://localhost:8000](http://localhost:8000).

### Option 3: FastAPI Backend Mounting
The backend server mounts `report/dist/` to serve the review viewer on top-level session requests. Ensure the FastAPI application has the following directory mount set up:
```python
from fastapi.staticfiles import StaticFiles

# Mount the static site under report/dist/
app.mount("/report", StaticFiles(directory="report/dist", html=True), name="report")
```

---

## Architectural Implementation Details

1. **Custom Force-Directed Graph**:
   - Instead of pulling in heavy layout packages like D3.js or Vis.js (which can fail/timeout offline or when loaded via `file://`), we implemented a high-performance **2D Physics Force-Directed Layout Engine** using HTML5 `<canvas>`.
   - It calculates repulsion (Coulomb's Law) and link attraction (Hooke's Law) on every frame.
   - Designed with futuristic glow shadows, responsive panning/zooming, and physics-aware node-dragging.

2. **Debate Transcript Viewer**:
   - Renders contested findings in a rounded chat-like thread view.
   - Highlights rounds of debate, extra evidence cited during negotiation rounds, and shows the Moderator's final adjudication ruling with cited evidence metrics.

3. **Responsive Bounding Box Overlay**:
   - The DFM layout critic annotations contain pixel bounding boxes relative to `board.png`.
   - The **Board Overlay Inspector** draws the board render and maps the bounding boxes onto an interactive canvas coordinate layout, enabling hover previews, tooltips, and click-to-select cross-linking with the sidebar panel.

4. **Token Society Panel & Billing**:
   - Sums the prompt/completion tokens consumed by each specialized agent.
   - Computes realistic cost metrics based on the pricing tier of Qwen models (`qwen3-max` vs. `qwen-flash` vs. `qwen3-vl`).
   - Renders custom horizontal stacked bar charts in pure HTML/CSS.
