/**
 * BoardRoom Dashboard Controller
 * Vanilla ES6 JavaScript implementation with custom canvas force-directed graph.
 */

(function () {
  // --- STATE MANAGEMENT ---
  let reviewData = null;
  let activeView = 'blast-radius';
  let selectedNode = null;
  let selectedDebateFindingId = null;
  let selectedBoardFindingId = null;

  // Custom Graph State
  let graphNodes = [];
  let graphLinks = [];
  let graphHoveredNode = null;
  let graphSelectedNode = null;
  let graphZoom = 1.0;
  let graphPan = { x: 0, y: 0 };
  let graphIsPanning = false;
  let graphStartPan = { x: 0, y: 0 };
  let graphDragNode = null;
  let graphCanvas = null;
  let graphCtx = null;
  let animationFrameId = null;

  // Board Overlay State
  let boardImage = new Image();
  let boardCanvas = null;
  let boardCtx = null;
  let boardHoveredFinding = null;

  // Pricing constants (USD per 1000 tokens)
  const PRICING = {
    'qwen3-max': { prompt: 0.02, completion: 0.06 },      // Moderator
    'qwen-flash': { prompt: 0.001, completion: 0.002 },   // PI, SI, ERC
    'qwen3-vl': { prompt: 0.003, completion: 0.009 },      // DFM Layout
    'qwen3-coder': { prompt: 0.002, completion: 0.006 },   // FW Bringup
    'default': { prompt: 0.002, completion: 0.005 }
  };

  // --- INITIALIZATION ---
  window.addEventListener('DOMContentLoaded', () => {
    initUIEvents();
    
    // Load default sample data if present
    if (window.BOARDROOM_SAMPLE_REVIEW) {
      loadReview(window.BOARDROOM_SAMPLE_REVIEW);
    } else {
      showErrorPlaceholder("No data loaded. Use the file selector to upload a review.json file.");
    }
  });

  // --- UI EVENTS SETUP ---
  function initUIEvents() {
    // Navigation Tabs
    const navButtons = document.querySelectorAll('.nav-btn');
    navButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetView = btn.getAttribute('data-view');
        switchView(targetView);
      });
    });

    // File Input Uploader
    const fileInput = document.getElementById('fileInput');
    const dropzone = document.getElementById('dropzone');

    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) handleFile(file);
    });

    // Drag and Drop
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('drop', (e) => e.preventDefault());

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
      dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      const file = e.dataTransfer.files[0];
      if (file && file.name.endsWith('.json')) {
        handleFile(file);
      }
    });

    // Graph Filters
    const severityFilter = document.getElementById('graphFilterSeverity');
    severityFilter.addEventListener('change', () => {
      buildGraphData();
    });

    // Table Filters
    document.getElementById('tableFilterAgent').addEventListener('change', updateFindingsTable);
    document.getElementById('tableFilterStatus').addEventListener('change', updateFindingsTable);
    document.getElementById('tableSortBy').addEventListener('change', updateFindingsTable);
  }

  // --- TAB NAVIGATION SYSTEM ---
  function switchView(viewId) {
    activeView = viewId;
    
    // Update active nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
      if (btn.getAttribute('data-view') === viewId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Toggle panels
    document.querySelectorAll('.view-panel').forEach(panel => {
      if (panel.id === `view-${viewId}`) {
        panel.classList.add('active');
      } else {
        panel.classList.remove('active');
      }
    });

    // Cancel physics loop if not in graph view to conserve CPU
    if (viewId === 'blast-radius') {
      startGraphPhysics();
    } else {
      cancelAnimationFrame(animationFrameId);
    }

    // Trigger specific view setups
    if (viewId === 'board-overlay') {
      initBoardOverlay();
    }
  }

  // --- LOAD & VALIDATE REVIEW JSON ---
  function handleFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target.result);
        if (!data.findings || !Array.isArray(data.findings)) {
          alert("Invalid review file: missing 'findings' array.");
          return;
        }
        loadReview(data);
      } catch (err) {
        alert("Failed to parse JSON file: " + err.message);
      }
    };
    reader.readAsText(file);
  }

  function loadReview(data) {
    reviewData = data;
    
    // Update Sidebar details
    document.getElementById('projectName').textContent = data.project_name || "Unknown Project";
    document.getElementById('sessionId').textContent = data.session_id || "N/A";
    document.getElementById('findingCounts').textContent = `${data.findings.length} Filed`;

    // Populate debate badge
    const contestedCount = data.findings.filter(f => f.status === 'contested' || f.debate).length;
    const badge = document.getElementById('debateCountBadge');
    if (contestedCount > 0) {
      badge.textContent = contestedCount;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }

    // Populate views
    buildGraphData();
    populateDebates();
    initBoardOverlay();
    updateFindingsTable();
    populateTokenAccounting();

    // Default view
    switchView('blast-radius');
  }

  function showErrorPlaceholder(message) {
    document.getElementById('projectName').textContent = "No Session Active";
    document.getElementById('sessionId').textContent = "-";
    document.getElementById('findingCounts').textContent = "-";
  }

  // --- VIEW 1: BLAST-RADIUS GRAPH PHYSICS SIMULATION ---
  function buildGraphData() {
    if (!reviewData) return;

    const severityFilter = document.getElementById('graphFilterSeverity').value;
    
    // Reset graph nodes and links
    const newNodes = [];
    const newLinks = [];
    const nodeMap = new Map(); // Keep track of duplicates for nets & comps

    // Filter findings
    const findings = reviewData.findings.filter(f => {
      if (severityFilter === 'all') return true;
      return f.severity === severityFilter;
    });

    // 1. Generate Finding Nodes
    findings.forEach(finding => {
      const id = `finding-${finding.id}`;
      const node = {
        id: id,
        type: 'finding',
        label: finding.id,
        severity: finding.severity,
        radius: 14,
        x: Math.random() * 400 + 200,
        y: Math.random() * 300 + 150,
        vx: 0,
        vy: 0,
        details: finding
      };
      newNodes.push(node);
      nodeMap.set(id, node);

      // 2. Generate Affected Nets Nodes
      if (finding.affected_nets) {
        finding.affected_nets.forEach(net => {
          const netId = `net-${net}`;
          let netNode = nodeMap.get(netId);
          if (!netNode) {
            netNode = {
              id: netId,
              type: 'net',
              label: net,
              radius: 9,
              x: Math.random() * 400 + 200,
              y: Math.random() * 300 + 150,
              vx: 0,
              vy: 0
            };
            newNodes.push(netNode);
            nodeMap.set(netId, netNode);
          }
          // Link Finding -> Net
          newLinks.push({ source: id, target: netId });
        });
      }

      // 3. Generate Affected Components Nodes
      if (finding.affected_components) {
        finding.affected_components.forEach(comp => {
          const compId = `comp-${comp}`;
          let compNode = nodeMap.get(compId);
          if (!compNode) {
            compNode = {
              id: compId,
              type: 'component',
              label: comp,
              radius: 10,
              x: Math.random() * 400 + 200,
              y: Math.random() * 300 + 150,
              vx: 0,
              vy: 0
            };
            newNodes.push(compNode);
            nodeMap.set(compId, compNode);
          }
          // Link Finding -> Component
          newLinks.push({ source: id, target: compId });
        });
      }
    });

    // Re-bind links to node objects rather than ID strings
    graphLinks = newLinks.map(link => {
      return {
        sourceNode: nodeMap.get(link.source),
        targetNode: nodeMap.get(link.target)
      };
    }).filter(link => link.sourceNode && link.targetNode);

    // Keep positions if nodes existed already, to prevent jarring resets
    newNodes.forEach(node => {
      const existing = graphNodes.find(n => n.id === node.id);
      if (existing) {
        node.x = existing.x;
        node.y = existing.y;
        node.vx = existing.vx;
        node.vy = existing.vy;
      }
    });

    graphNodes = newNodes;

    // Reset layout zoom/pan
    graphZoom = 1.0;
    graphPan = { x: 0, y: 0 };
    graphHoveredNode = null;
    
    // Set up canvas and click listeners once
    initGraphCanvas();
  }

  function initGraphCanvas() {
    graphCanvas = document.getElementById('blastRadiusCanvas');
    if (!graphCanvas) return;
    graphCtx = graphCanvas.getContext('2d');

    // Resize listener
    function resizeCanvas() {
      const rect = graphCanvas.parentElement.getBoundingClientRect();
      graphCanvas.width = rect.width;
      graphCanvas.height = rect.height;
    }
    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    // Mouse Listeners
    graphCanvas.addEventListener('mousedown', (e) => {
      const rect = graphCanvas.getBoundingClientRect();
      const mouseX = (e.clientX - rect.left - graphPan.x) / graphZoom;
      const mouseY = (e.clientY - rect.top - graphPan.y) / graphZoom;

      // Check if clicking a node
      let clickedNode = null;
      for (let node of graphNodes) {
        const dist = Math.hypot(node.x - mouseX, node.y - mouseY);
        if (dist <= node.radius + 5) {
          clickedNode = node;
          break;
        }
      }

      if (clickedNode) {
        graphDragNode = clickedNode;
      } else {
        graphIsPanning = true;
        graphStartPan = { x: e.clientX - graphPan.x, y: e.clientY - graphPan.y };
      }
    });

    graphCanvas.addEventListener('mousemove', (e) => {
      const rect = graphCanvas.getBoundingClientRect();
      const mouseX = (e.clientX - rect.left - graphPan.x) / graphZoom;
      const mouseY = (e.clientY - rect.top - graphPan.y) / graphZoom;

      if (graphDragNode) {
        graphDragNode.x = mouseX;
        graphDragNode.y = mouseY;
        graphDragNode.vx = 0;
        graphDragNode.vy = 0;
      } else if (graphIsPanning) {
        graphPan.x = e.clientX - graphStartPan.x;
        graphPan.y = e.clientY - graphStartPan.y;
      } else {
        // Detect Hover
        let hoverNode = null;
        for (let node of graphNodes) {
          const dist = Math.hypot(node.x - mouseX, node.y - mouseY);
          if (dist <= node.radius + 5) {
            hoverNode = node;
            break;
          }
        }
        graphHoveredNode = hoverNode;
      }
    });

    window.addEventListener('mouseup', () => {
      if (graphDragNode && graphDragNode.type === 'finding') {
        selectGraphNode(graphDragNode);
      }
      graphDragNode = null;
      graphIsPanning = false;
    });

    graphCanvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = 1.1;
      const rect = graphCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      // Zoom towards mouse pointer
      const prevZoom = graphZoom;
      if (e.deltaY < 0) {
        graphZoom = Math.min(graphZoom * zoomFactor, 4.0);
      } else {
        graphZoom = Math.max(graphZoom / zoomFactor, 0.4);
      }

      graphPan.x = mouseX - (mouseX - graphPan.x) * (graphZoom / prevZoom);
      graphPan.y = mouseY - (mouseY - graphPan.y) * (graphZoom / prevZoom);
    });

    startGraphPhysics();
  }

  // Simulated-annealing "temperature". Starts hot, cools to rest so the layout
  // SETTLES instead of jittering forever (a permanently vibrating graph is
  // unreadable — and unusable as a demo visual). Dragging re-heats it.
  let graphAlpha = 1;
  const ALPHA_DECAY = 0.035;   // how fast it cools (~2.5s to rest at 60fps)
  const ALPHA_MIN = 0.004;     // below this we consider it at rest

  function reheatGraph(amount = 0.45) {
    graphAlpha = Math.max(graphAlpha, amount);
  }

  function startGraphPhysics() {
    cancelAnimationFrame(animationFrameId);
    graphAlpha = 1; // fresh layout starts hot

    function tick() {
      if (activeView !== 'blast-radius') return;
      // Once settled we stop integrating but keep drawing, so hover/selection
      // highlights still respond while the layout stays perfectly still.
      if (graphAlpha > ALPHA_MIN) {
        updatePhysics();
        graphAlpha -= graphAlpha * ALPHA_DECAY;
      }
      drawGraph();
      animationFrameId = requestAnimationFrame(tick);
    }

    animationFrameId = requestAnimationFrame(tick);
  }

  // Core Force-Directed Layout Physics
  function updatePhysics() {
    const kRepulsion = 5200;   // stronger, so nodes spread instead of clumping
    const kAttraction = 0.035; // gentler springs -> longer, readable edges
    const kGravity = 0.012;    // softer pull to center (less oscillation)
    const friction = 0.78;     // more damping -> calmer motion
    const LABEL_PAD = 26;      // extra separation so text labels don't overlap
    const MAX_SPEED = 12;      // clamp: prevents the "explosive" jitter

    const centerX = graphCanvas.width / 2;
    const centerY = graphCanvas.height / 2;

    if (graphDragNode) reheatGraph(0.3);

    // 1. Center Gravity
    graphNodes.forEach(node => {
      if (node === graphDragNode) return;
      node.vx += (centerX - node.x) * kGravity;
      node.vy += (centerY - node.y) * kGravity;
    });

    // 2. Repulsion between all nodes
    for (let i = 0; i < graphNodes.length; i++) {
      const n1 = graphNodes[i];
      for (let j = i + 1; j < graphNodes.length; j++) {
        const n2 = graphNodes[j];
        let dx = n2.x - n1.x;
        let dy = n2.y - n1.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) { // identical positions: nudge deterministically
          dx = (i - j) || 1; dy = 1; dist = Math.hypot(dx, dy);
        }
        // Clamp the effective distance so the 1/d^2 term can't explode.
        const eff = Math.max(dist, 24);
        const force = kRepulsion / (eff * eff);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;

        if (n1 !== graphDragNode) { n1.vx -= fx; n1.vy -= fy; }
        if (n2 !== graphDragNode) { n2.vx += fx; n2.vy += fy; }
      }
    }

    // 3. Attraction along links
    graphLinks.forEach(link => {
      const n1 = link.sourceNode;
      const n2 = link.targetNode;
      const dx = n2.x - n1.x;
      const dy = n2.y - n1.y;
      const dist = Math.hypot(dx, dy) || 1.0;

      const force = dist * kAttraction;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;

      if (n1 !== graphDragNode) { n1.vx += fx; n1.vy += fy; }
      if (n2 !== graphDragNode) { n2.vx -= fx; n2.vy -= fy; }
    });

    // 4. Update positions — displacement scaled by the cooling temperature.
    graphNodes.forEach(node => {
      if (node === graphDragNode) return;
      node.vx *= friction;
      node.vy *= friction;

      // Clamp speed, then scale by alpha so motion fades to a standstill.
      const speed = Math.hypot(node.vx, node.vy);
      if (speed > MAX_SPEED) {
        node.vx = (node.vx / speed) * MAX_SPEED;
        node.vy = (node.vy / speed) * MAX_SPEED;
      }
      node.x += node.vx * graphAlpha;
      node.y += node.vy * graphAlpha;

      node.x = Math.max(50, Math.min(graphCanvas.width - 50, node.x));
      node.y = Math.max(50, Math.min(graphCanvas.height - 50, node.y));
    });

    // 5. Hard collision separation — guarantees labels never sit on top of each
    // other, which pure force-based repulsion does not.
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 0; i < graphNodes.length; i++) {
        const n1 = graphNodes[i];
        for (let j = i + 1; j < graphNodes.length; j++) {
          const n2 = graphNodes[j];
          const dx = n2.x - n1.x;
          const dy = n2.y - n1.y;
          const dist = Math.hypot(dx, dy) || 0.01;
          const minDist = n1.radius + n2.radius + LABEL_PAD;
          if (dist >= minDist) continue;
          const push = (minDist - dist) / 2;
          const ux = dx / dist, uy = dy / dist;
          if (n1 !== graphDragNode) { n1.x -= ux * push; n1.y -= uy * push; }
          if (n2 !== graphDragNode) { n2.x += ux * push; n2.y += uy * push; }
        }
      }
    }
  }

  // Draw Graph onto Canvas with Rich Dark Glow Aesthetics
  function drawGraph() {
    if (!graphCtx) return;
    const ctx = graphCtx;
    ctx.clearRect(0, 0, graphCanvas.width, graphCanvas.height);

    // Draw grid background
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.015)';
    ctx.lineWidth = 1;
    const gridSize = 40;
    for (let x = graphPan.x % gridSize; x < graphCanvas.width; x += gridSize) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, graphCanvas.height); ctx.stroke();
    }
    for (let y = graphPan.y % gridSize; y < graphCanvas.height; y += gridSize) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(graphCanvas.width, y); ctx.stroke();
    }
    ctx.restore();

    ctx.save();
    ctx.translate(graphPan.x, graphPan.y);
    ctx.scale(graphZoom, graphZoom);

    // Determine highlighting context
    const highlightNode = graphHoveredNode || graphSelectedNode;
    const isNodeConnected = (node) => {
      if (!highlightNode) return true;
      if (node.id === highlightNode.id) return true;
      // Check if there's a link between highlightNode and node
      return graphLinks.some(link => 
        (link.sourceNode.id === highlightNode.id && link.targetNode.id === node.id) ||
        (link.targetNode.id === highlightNode.id && link.sourceNode.id === node.id)
      );
    };

    // 1. Draw Links
    graphLinks.forEach(link => {
      const isHighlighted = highlightNode && 
        (link.sourceNode.id === highlightNode.id || link.targetNode.id === highlightNode.id);

      ctx.beginPath();
      ctx.moveTo(link.sourceNode.x, link.sourceNode.y);
      ctx.lineTo(link.targetNode.x, link.targetNode.y);
      
      if (isHighlighted) {
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 2.5;
        ctx.shadowBlur = 8;
        ctx.shadowColor = '#3b82f6';
      } else {
        ctx.strokeStyle = highlightNode ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.07)';
        ctx.lineWidth = 1;
        ctx.shadowBlur = 0;
      }
      ctx.stroke();
      ctx.shadowBlur = 0; // Reset shadow
    });

    // 2. Draw Nodes
    graphNodes.forEach(node => {
      const isHighlightContext = highlightNode !== null;
      const isNodeActive = isNodeConnected(node);
      const isDirectlyTargeted = highlightNode && node.id === highlightNode.id;

      ctx.save();
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, 2 * Math.PI);

      let nodeColor = '#94a3b8';
      let shadowColor = 'transparent';
      let showGlow = false;

      // Color scheme based on type/severity
      if (node.type === 'finding') {
        showGlow = true;
        if (node.severity === 'critical') {
          nodeColor = '#ef4444';
          shadowColor = '#ef4444';
        } else if (node.severity === 'major') {
          nodeColor = '#f97316';
          shadowColor = '#f97316';
        } else if (node.severity === 'minor') {
          nodeColor = '#eab308';
          shadowColor = '#eab308';
        } else {
          nodeColor = '#64748b';
          shadowColor = '#64748b';
        }
      } else if (node.type === 'net') {
        nodeColor = '#06b6d4';
        shadowColor = '#06b6d4';
        showGlow = isDirectlyTargeted;
      } else if (node.type === 'component') {
        nodeColor = '#a855f7';
        shadowColor = '#a855f7';
        showGlow = isDirectlyTargeted;
      }

      // Draw shadow glow for important elements
      if (showGlow && (!isHighlightContext || isNodeActive)) {
        ctx.shadowBlur = isDirectlyTargeted ? 15 : 8;
        ctx.shadowColor = shadowColor;
      }

      ctx.fillStyle = nodeColor;
      // Dim inactive nodes
      if (isHighlightContext && !isNodeActive) {
        ctx.globalAlpha = 0.15;
      }

      ctx.fill();
      
      // Node border
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#ffffff';
      if (isDirectlyTargeted) {
        ctx.strokeStyle = '#3b82f6';
      }
      ctx.stroke();
      ctx.restore();

      // 3. Node Labels
      ctx.save();
      if (isHighlightContext && !isNodeActive) {
        ctx.globalAlpha = 0.15;
      }
      
      ctx.fillStyle = '#ffffff';
      ctx.font = node.type === 'finding' ? 'bold 10px monospace' : '9px sans-serif';
      ctx.textAlign = 'center';
      
      if (node.type === 'finding') {
        // Draw inside circle
        ctx.fillText(node.label, node.x, node.y + 3);
      } else {
        // Draw below circle with backdrop fill for readability
        const textY = node.y + node.radius + 12;
        ctx.fillText(node.label, node.x, textY);
      }
      ctx.restore();
    });

    ctx.restore();
  }

  function selectGraphNode(node) {
    graphSelectedNode = node;
    
    const placeholder = document.querySelector('.detail-sidebar .detail-placeholder');
    const content = document.getElementById('graphDetailContent');
    
    if (!node || node.type !== 'finding') {
      placeholder.classList.remove('hidden');
      content.classList.add('hidden');
      return;
    }

    placeholder.classList.add('hidden');
    content.classList.remove('hidden');

    const f = node.details;
    
    // Severity CSS Class
    let sevClass = 'sev-info';
    if (f.severity === 'critical') sevClass = 'sev-critical';
    else if (f.severity === 'major') sevClass = 'sev-major';
    else if (f.severity === 'minor') sevClass = 'sev-minor';

    let netBadges = f.affected_nets ? f.affected_nets.map(n => `<span class="tag-badge net-tag">${n}</span>`).join('') : 'None';
    let compBadges = f.affected_components ? f.affected_components.map(c => `<span class="tag-badge comp-tag">${c}</span>`).join('') : 'None';

    let evidenceHtml = f.evidence.map(e => `
      <div class="evidence-card">
        <span class="evidence-tool">${e.tool}</span>
        <p>${e.summary}</p>
        <span class="node-type-label" style="font-size:0.65rem; margin-top: 0.25rem; display:block;">Evidence ID: ${e.evidence_id}</span>
      </div>
    `).join('');

    content.innerHTML = `
      <div class="detail-header">
        <div class="detail-title-row">
          <span class="node-type-label">Finding Details</span>
          <span class="severity-badge ${sevClass}">${f.severity}</span>
        </div>
        <span class="detail-id">${f.id}</span>
        <h3 class="detail-claim">${f.claim}</h3>
      </div>

      <div class="detail-section">
        <h4>Status</h4>
        <span class="status-badge status-${f.status}">${f.status}</span>
      </div>

      <div class="detail-section">
        <h4>Recommendation</h4>
        <p style="font-size: 0.85rem; font-weight:500; background: rgba(59, 130, 246, 0.05); padding: 0.6rem; border-left: 3px solid #3b82f6; border-radius: 4px;">
          ${f.recommendation}
        </p>
      </div>

      <div class="detail-section">
        <h4>Affected Nets</h4>
        <div class="badge-row">${netBadges}</div>
      </div>

      <div class="detail-section">
        <h4>Affected Components</h4>
        <div class="badge-row">${compBadges}</div>
      </div>

      <div class="detail-section">
        <h4>CITED EVIDENCE</h4>
        ${evidenceHtml}
      </div>
    `;
  }

  // --- VIEW 2: DEBATE VIEWER ---
  function populateDebates() {
    const listContainer = document.getElementById('debateList');
    const placeholder = document.getElementById('debateTranscriptPlaceholder');
    const content = document.getElementById('debateTranscriptContent');

    if (!reviewData) return;

    // Filter findings that entered debate
    const debatedFindings = reviewData.findings.filter(f => f.status === 'contested' || f.debate || f.ruling);

    listContainer.innerHTML = '';

    if (debatedFindings.length === 0) {
      listContainer.innerHTML = '<p class="sidebar-help">No contested findings in this session review.</p>';
      placeholder.classList.remove('hidden');
      content.classList.add('hidden');
      return;
    }

    debatedFindings.forEach(f => {
      const btn = document.createElement('button');
      btn.className = `debate-item-btn ${selectedDebateFindingId === f.id ? 'active' : ''}`;
      
      let sevClass = 'sev-info';
      if (f.severity === 'critical') sevClass = 'sev-critical';
      else if (f.severity === 'major') sevClass = 'sev-major';

      btn.innerHTML = `
        <div class="debate-item-header">
          <span class="debate-item-id">${f.id}</span>
          <span class="severity-badge ${sevClass}" style="transform: scale(0.85);">${f.severity}</span>
        </div>
        <div class="debate-item-title">${f.claim}</div>
      `;

      btn.addEventListener('click', () => {
        document.querySelectorAll('.debate-item-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderDebate(f);
      });

      listContainer.appendChild(btn);
    });

    // Auto-select first debate if nothing selected
    if (debatedFindings.length > 0 && !selectedDebateFindingId) {
      listContainer.children[0].click();
    } else if (selectedDebateFindingId) {
      const activeBtn = Array.from(listContainer.children).find(b => b.querySelector('.debate-item-id').textContent === selectedDebateFindingId);
      if (activeBtn) activeBtn.click();
    }
  }

  function renderDebate(finding) {
    selectedDebateFindingId = finding.id;

    document.getElementById('debateTranscriptPlaceholder').classList.add('hidden');
    const content = document.getElementById('debateTranscriptContent');
    content.classList.remove('hidden');

    document.getElementById('debateFindingId').textContent = finding.id;
    document.getElementById('debateClaim').textContent = finding.claim;
    document.getElementById('debateSeverity').className = `severity-${finding.severity}`;
    document.getElementById('debateSeverity').textContent = finding.severity;
    document.getElementById('debateComponents').textContent = finding.affected_components ? finding.affected_components.join(', ') : 'None';

    const roundsContainer = document.getElementById('debateRounds');
    roundsContainer.innerHTML = '';

    if (!finding.debate || finding.debate.length === 0) {
      roundsContainer.innerHTML = '<div class="detail-placeholder"><p>No round transcripts available for this finding.</p></div>';
      return;
    }

    // Organize by rounds
    const rounds = {};
    finding.debate.forEach(item => {
      if (!rounds[item.round]) rounds[item.round] = [];
      rounds[item.round].push(item);
    });

    Object.keys(rounds).forEach(roundNum => {
      // Round Header Divider
      const div = document.createElement('div');
      div.className = 'debate-round-divider';
      div.textContent = `Round ${roundNum}`;
      roundsContainer.appendChild(div);

      // Statements in this round
      rounds[roundNum].forEach(msg => {
        const bubbleRow = document.createElement('div');
        
        // Style depending on sender
        let bubbleType = 'si-bubble';
        let initials = 'A';
        if (msg.agent === 'signal_integrity') { bubbleType = 'si-bubble'; initials = 'SI'; }
        else if (msg.agent === 'power_integrity') { bubbleType = 'pi-bubble'; initials = 'PI'; }
        else if (msg.agent === 'dfm_layout') { bubbleType = 'dfm-bubble'; initials = 'DF'; }
        else if (msg.agent === 'connectivity_erc') { bubbleType = 'si-bubble'; initials = 'ER'; }
        else if (msg.agent === 'firmware_bringup') { bubbleType = 'dfm-bubble'; initials = 'FW'; }

        bubbleRow.className = `chat-bubble-row ${bubbleType}`;

        let evidenceHtml = '';
        if (msg.new_evidence_id) {
          // Find detail summary from original finding if it matches
          const matchEv = finding.evidence.find(e => e.evidence_id === msg.new_evidence_id);
          const evSummary = matchEv ? matchEv.summary : "Retrieved fresh MCP tools simulation run.";
          evidenceHtml = `
            <div class="bubble-evidence">
              <span>${msg.new_evidence_id}</span>${evSummary}
            </div>
          `;
        }

        bubbleRow.innerHTML = `
          <div class="agent-icon">${initials}</div>
          <div class="chat-bubble">
            <span class="bubble-sender">${msg.agent.toUpperCase().replace('_', ' ')}</span>
            <p class="bubble-text">${msg.position}</p>
            ${evidenceHtml}
          </div>
        `;
        roundsContainer.appendChild(bubbleRow);
      });
    });

    // Adjudication Ruling
    const rulingPanel = document.getElementById('moderatorRulingPanel');
    if (finding.ruling) {
      rulingPanel.style.display = 'block';
      const decBadge = document.getElementById('rulingDecisionBadge');
      decBadge.className = `ruling-decision-badge status-${finding.ruling.decision}`;
      decBadge.textContent = finding.ruling.decision.toUpperCase();

      document.getElementById('rulingRationale').textContent = finding.ruling.rationale;
      
      const citationsContainer = document.getElementById('rulingCitedEvidence');
      citationsContainer.innerHTML = finding.ruling.cited_evidence_ids.map(id => `
        <span class="citation-badge">${id}</span>
      `).join('');
    } else {
      rulingPanel.style.display = 'none';
    }

    // Scroll to bottom of chat
    setTimeout(() => {
      roundsContainer.scrollTop = roundsContainer.scrollHeight;
    }, 10);
  }

  // --- VIEW 3: BOARD OVERLAY ---
  function initBoardOverlay() {
    boardCanvas = document.getElementById('boardOverlayCanvas');
    if (!boardCanvas || !reviewData) return;
    boardCtx = boardCanvas.getContext('2d');

    // Load sample image
    boardImage.src = 'board.png';
    boardImage.onload = () => {
      // Resize canvas to match image natural aspect ratio
      boardCanvas.width = boardImage.naturalWidth;
      boardCanvas.height = boardImage.naturalHeight;
      drawBoardOverlay();
    };

    // Build sidebar overlay items
    populateBoardSidebarList();

    // Mouse interaction for board highlights
    boardCanvas.addEventListener('mousemove', (e) => {
      if (!reviewData) return;
      const rect = boardCanvas.getBoundingClientRect();
      // Translate screen coordinates to canvas pixels
      const scaleX = boardCanvas.width / rect.width;
      const scaleY = boardCanvas.height / rect.height;
      const canvasX = (e.clientX - rect.left) * scaleX;
      const canvasY = (e.clientY - rect.top) * scaleY;

      // Find if hovering a bounding box
      let hovered = null;
      const boardFindings = reviewData.findings.filter(f => f.board_region);
      for (let f of boardFindings) {
        const box = f.board_region;
        if (canvasX >= box.x && canvasX <= box.x + box.w &&
            canvasY >= box.y && canvasY <= box.y + box.h) {
          hovered = f;
          break;
        }
      }

      if (boardHoveredFinding !== hovered) {
        boardHoveredFinding = hovered;
        drawBoardOverlay();
      }
    });

    boardCanvas.addEventListener('click', () => {
      if (boardHoveredFinding) {
        selectBoardFinding(boardHoveredFinding);
      }
    });
  }

  function populateBoardSidebarList() {
    const list = document.getElementById('boardFindingList');
    list.innerHTML = '';
    
    const boardFindings = reviewData.findings.filter(f => f.board_region);

    if (boardFindings.length === 0) {
      list.innerHTML = '<p class="sidebar-help">No board render overlay annotations in this review.</p>';
      return;
    }

    boardFindings.forEach(f => {
      const btn = document.createElement('button');
      btn.className = `board-finding-btn ${selectedBoardFindingId === f.id ? 'active' : ''}`;
      btn.innerHTML = `
        <div class="board-finding-btn-title">
          <span>${f.id}</span>
          <span class="severity-badge sev-${f.severity}">${f.severity}</span>
        </div>
        <div class="board-finding-btn-claim">${f.claim}</div>
      `;

      btn.addEventListener('click', () => {
        document.querySelectorAll('.board-finding-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        selectedBoardFindingId = f.id;
        boardHoveredFinding = f;
        drawBoardOverlay();
      });

      list.appendChild(btn);
    });
  }

  function selectBoardFinding(finding) {
    selectedBoardFindingId = finding.id;
    // Highlight button in sidebar list
    document.querySelectorAll('.board-finding-btn').forEach(b => {
      const idText = b.querySelector('.board-finding-btn-title span').textContent;
      if (idText === finding.id) {
        b.classList.add('active');
        b.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        b.classList.remove('active');
      }
    });
  }

  function drawBoardOverlay() {
    if (!boardCtx || !boardImage.complete) return;
    const ctx = boardCtx;
    ctx.clearRect(0, 0, boardCanvas.width, boardCanvas.height);
    
    // 1. Draw Board Image
    ctx.drawImage(boardImage, 0, 0);

    // 2. Draw annotations
    if (!reviewData) return;
    const boardFindings = reviewData.findings.filter(f => f.board_region);

    boardFindings.forEach(f => {
      const box = f.board_region;
      const isHovered = boardHoveredFinding && boardHoveredFinding.id === f.id;
      const isSelected = selectedBoardFindingId === f.id;

      // Color scheme based on severity
      let color = 'rgba(239, 68, 68, 0.5)'; // default critical red
      let strokeColor = '#ef4444';
      if (f.severity === 'major') { color = 'rgba(249, 115, 22, 0.4)'; strokeColor = '#f97316'; }
      else if (f.severity === 'minor') { color = 'rgba(234, 179, 8, 0.4)'; strokeColor = '#eab308'; }

      ctx.save();
      
      // Bounding Box background fill
      ctx.fillStyle = isHovered ? color.replace('0.4', '0.25').replace('0.5', '0.35') : color.replace('0.4', '0.1').replace('0.5', '0.15');
      ctx.fillRect(box.x, box.y, box.w, box.h);

      // Bounding Box Borders
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = isSelected ? 4 : (isHovered ? 3 : 2);
      
      // Draw neon glow for active elements
      if (isHovered || isSelected) {
        ctx.shadowBlur = 10;
        ctx.shadowColor = strokeColor;
      }
      ctx.strokeRect(box.x, box.y, box.w, box.h);
      ctx.restore();

      // Bounding box label
      if (isHovered || isSelected) {
        ctx.save();
        ctx.fillStyle = strokeColor;
        ctx.font = 'bold 12px sans-serif';
        const txt = `${f.id}: ${f.severity.toUpperCase()}`;
        const padding = 4;
        const textWidth = ctx.measureText(txt).width;
        
        // draw background box for text
        ctx.fillStyle = '#0f1322';
        ctx.fillRect(box.x, box.y - 20, textWidth + padding * 2, 18);
        ctx.strokeStyle = strokeColor;
        ctx.strokeRect(box.x, box.y - 20, textWidth + padding * 2, 18);

        ctx.fillStyle = '#ffffff';
        ctx.fillText(txt, box.x + padding, box.y - 6);
        ctx.restore();
      }
    });
  }

  // --- VIEW 4: FINDINGS TABLE ---
  function updateFindingsTable() {
    const tableBody = document.getElementById('findingsTableBody');
    if (!tableBody || !reviewData) return;

    const agentFilter = document.getElementById('tableFilterAgent').value;
    const statusFilter = document.getElementById('tableFilterStatus').value;
    const sortBy = document.getElementById('tableSortBy').value;

    let findings = [...reviewData.findings];

    // 1. Filtering
    if (agentFilter !== 'all') {
      findings = findings.filter(f => f.agent === agentFilter);
    }
    if (statusFilter !== 'all') {
      findings = findings.filter(f => f.status === statusFilter);
    }

    // 2. Sorting
    const severityValues = { 'critical': 4, 'major': 3, 'minor': 2, 'info': 1 };
    findings.sort((a, b) => {
      if (sortBy === 'severity') {
        return (severityValues[b.severity] || 0) - (severityValues[a.severity] || 0);
      } else if (sortBy === 'agent') {
        return a.agent.localeCompare(b.agent);
      } else if (sortBy === 'status') {
        return a.status.localeCompare(b.status);
      } else {
        // default ID sort alphanumeric
        return a.id.localeCompare(b.id, undefined, { numeric: true, sensitivity: 'base' });
      }
    });

    tableBody.innerHTML = '';

    if (findings.length === 0) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; color: var(--text-dark); padding: 3rem;">
            No findings match the selected filters.
          </td>
        </tr>
      `;
      return;
    }

    findings.forEach(f => {
      // Main row
      const trMain = document.createElement('tr');
      trMain.className = 'row-main';
      trMain.setAttribute('data-id', f.id);

      let sevClass = 'sev-info';
      if (f.severity === 'critical') sevClass = 'sev-critical';
      else if (f.severity === 'major') sevClass = 'sev-major';
      else if (f.severity === 'minor') sevClass = 'sev-minor';

      const scopeText = f.affected_components && f.affected_components.length > 0 
        ? f.affected_components.join(', ') 
        : 'Board';

      trMain.innerHTML = `
        <td>
          <svg class="expander-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M9 18l6-6-6-6"/>
          </svg>
        </td>
        <td class="table-finding-id">${f.id}</td>
        <td class="agent-text">${f.agent.replace('_', ' ')}</td>
        <td style="font-weight: 500;">${f.claim}</td>
        <td><span class="severity-badge ${sevClass}">${f.severity}</span></td>
        <td><span class="status-badge status-${f.status}">${f.status}</span></td>
        <td style="font-family: monospace; color: var(--text-muted);">${scopeText}</td>
      `;

      // Details row (initially hidden)
      const trDetails = document.createElement('tr');
      trDetails.className = 'row-details hidden';
      
      let netBadges = f.affected_nets && f.affected_nets.length > 0 
        ? f.affected_nets.map(n => `<span class="tag-badge net-tag">${n}</span>`).join('') 
        : '<span style="color:var(--text-dark)">None</span>';

      let evidenceHtml = f.evidence.map(e => `
        <div class="table-evidence-item">
          <span class="evidence-id-label">${e.evidence_id}</span>
          <strong style="color:#60a5fa">${e.tool}</strong>: ${e.summary}
        </div>
      `).join('');

      // Add conflict indicator if applicable
      let conflictHtml = '';
      if (f.conflicts_with && f.conflicts_with.length > 0) {
        conflictHtml = `
          <div class="details-block">
            <h4>Conflict Details</h4>
            <div style="font-size:0.8rem; background:rgba(239,68,68,0.05); border-left:3px solid #ef4444; padding:0.5rem; border-radius:4px;">
              Conflicts with finding: <strong style="font-family:monospace; color:#f87171">${f.conflicts_with.join(', ')}</strong>
              ${f.ruling ? `<br/><span style="color:var(--text-muted)">Resolved by Moderator: <strong>${f.ruling.decision.toUpperCase()}</strong></span>` : ''}
            </div>
          </div>
        `;
      }

      trDetails.innerHTML = `
        <td colspan="7">
          <div class="details-content-grid">
            <div>
              <div class="details-block">
                <h4>Recommendation</h4>
                <p class="details-recommendation">${f.recommendation}</p>
              </div>
              <div class="details-block">
                <h4>Evidence Citations</h4>
                <div class="table-evidence-list">${evidenceHtml}</div>
              </div>
            </div>
            <div>
              <div class="details-block">
                <h4>Impacted Nets</h4>
                <div class="badge-row" style="margin-top:0.25rem">${netBadges}</div>
              </div>
              ${conflictHtml}
            </div>
          </div>
        </td>
      `;

      // Toggle functionality
      trMain.addEventListener('click', () => {
        const isExpanded = trMain.classList.contains('expanded');
        
        // Collapse all others
        document.querySelectorAll('.row-main').forEach(r => r.classList.remove('expanded'));
        document.querySelectorAll('.row-details').forEach(r => r.classList.add('hidden'));

        if (!isExpanded) {
          trMain.classList.add('expanded');
          trDetails.classList.remove('hidden');
        }
      });

      tableBody.appendChild(trMain);
      tableBody.appendChild(trDetails);
    });
  }

  // --- VIEW 5: TOKEN PANEL METRICS & BILLING ---
  function populateTokenAccounting() {
    if (!reviewData || !reviewData.token_accounting) return;

    let totalPrompt = 0;
    let totalCompletion = 0;
    let totalEstimatedCost = 0.0;
    
    // Sum tokens and calculate costs
    reviewData.token_accounting.forEach(acc => {
      totalPrompt += acc.prompt_tokens;
      totalCompletion += acc.completion_tokens;
      
      // Determine rate
      const rate = PRICING[acc.model] || PRICING[acc.agent] || PRICING['default'];
      const pCost = (acc.prompt_tokens / 1000) * rate.prompt;
      const cCost = (acc.completion_tokens / 1000) * rate.completion;
      totalEstimatedCost += (pCost + cCost);
    });

    const totalTokens = totalPrompt + totalCompletion;
    document.getElementById('totalTokens').textContent = totalTokens.toLocaleString();
    document.getElementById('totalCost').textContent = `$${totalEstimatedCost.toFixed(3)}`;

    // Stacked Bar Chart per agent
    const chartContainer = document.getElementById('tokenBarChart');
    chartContainer.innerHTML = '';

    // Find maximum tokens per agent to scale the bars correctly
    const maxAgentTokens = Math.max(...reviewData.token_accounting.map(a => a.prompt_tokens + a.completion_tokens));

    reviewData.token_accounting.forEach(acc => {
      const agentTotal = acc.prompt_tokens + acc.completion_tokens;
      const promptPct = (acc.prompt_tokens / maxAgentTokens) * 100;
      const compPct = (acc.completion_tokens / maxAgentTokens) * 100;

      const row = document.createElement('div');
      row.className = 'bar-chart-row';
      row.innerHTML = `
        <div class="bar-label">
          <strong>${acc.agent.replace('_', ' ')}</strong>
          <span style="font-size:0.7rem; color:var(--text-dark); display:block; font-family:monospace">${acc.model}</span>
        </div>
        <div class="bar-wrapper">
          <div class="bar-prompt" style="width: ${promptPct}%" title="Prompt: ${acc.prompt_tokens.toLocaleString()}"></div>
          <div class="bar-completion" style="width: ${compPct}%" title="Completion: ${acc.completion_tokens.toLocaleString()}"></div>
        </div>
        <div class="bar-value">${agentTotal.toLocaleString()}</div>
      `;
      chartContainer.appendChild(row);
    });

    // Populate coverage notes list
    const notesContainer = document.getElementById('coverageNotesList');
    notesContainer.innerHTML = '';
    
    if (reviewData.coverage_notes && reviewData.coverage_notes.length > 0) {
      reviewData.coverage_notes.forEach(note => {
        const item = document.createElement('div');
        item.className = 'coverage-note-item';
        
        // Guess heading from prefix if formatted like "Agent: Note"
        const parts = note.split(':');
        let title = 'General Note';
        let body = note;
        if (parts.length > 1 && parts[0].length < 25) {
          title = parts[0];
          body = parts.slice(1).join(':').trim();
        }

        item.innerHTML = `
          <h5>${title}</h5>
          <p>${body}</p>
        `;
        notesContainer.appendChild(item);
      });
    } else {
      notesContainer.innerHTML = '<p class="sidebar-help">No coverage notes filed for this session.</p>';
    }
  }

})();
