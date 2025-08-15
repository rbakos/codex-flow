"""
Real-time monitoring dashboard for system activity.
Provides a web interface to see what the system is doing.
"""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json
from datetime import datetime

from .activity_tracker import tracker

# HTML template for the dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Codex Orchestrator - Activity Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: white;
            margin-bottom: 20px;
            text-align: center;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            animation: slideIn 0.3s ease-out;
        }
        .card h2 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.3em;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        .activity {
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            padding: 12px;
            margin-bottom: 10px;
            border-radius: 4px;
            transition: transform 0.2s;
        }
        .activity:hover {
            transform: translateX(5px);
        }
        .activity.in-progress {
            border-left-color: #28a745;
            background: #e8f5e9;
            animation: pulse 2s infinite;
        }
        .activity.completed {
            border-left-color: #17a2b8;
            background: #e3f2fd;
        }
        .activity.failed {
            border-left-color: #dc3545;
            background: #ffebee;
        }
        .activity-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .activity-name {
            font-weight: bold;
            color: #333;
        }
        .activity-status {
            font-size: 0.85em;
            padding: 2px 8px;
            border-radius: 12px;
            background: #667eea;
            color: white;
        }
        .activity-detail {
            color: #666;
            font-size: 0.9em;
            margin: 4px 0;
        }
        .activity-time {
            color: #999;
            font-size: 0.85em;
            font-style: italic;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }
        .stat {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
        }
        .stat-label {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }
        .decision {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 12px;
            margin-bottom: 10px;
            border-radius: 4px;
        }
        .thread-info {
            display: inline-block;
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.85em;
            margin-left: 10px;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.8; }
            100% { opacity: 1; }
        }
        .refresh-info {
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 0.9em;
        }
        .summary-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .summary-card h2 {
            color: white;
            border-bottom-color: rgba(255,255,255,0.3);
        }
        .websocket-status {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 10px 20px;
            background: #28a745;
            color: white;
            border-radius: 20px;
            font-size: 0.9em;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }
        .websocket-status.disconnected {
            background: #dc3545;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Codex Orchestrator Activity Monitor</h1>
        <div id="websocket-status" class="websocket-status disconnected">Connecting...</div>
        
        <div class="dashboard">
            <!-- System Summary -->
            <div class="card summary-card">
                <h2>📊 System Overview</h2>
                <div class="stats-grid">
                    <div class="stat">
                        <div class="stat-value" id="active-count">0</div>
                        <div class="stat-label">Active Tasks</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" id="total-count">0</div>
                        <div class="stat-label">Total Activities</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" id="success-rate">0%</div>
                        <div class="stat-label">Success Rate</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" id="avg-duration">0ms</div>
                        <div class="stat-label">Avg Duration</div>
                    </div>
                </div>
            </div>
            
            <!-- Active Activities -->
            <div class="card">
                <h2>⚡ Currently Active</h2>
                <div id="active-activities">
                    <div class="activity-detail">No active activities</div>
                </div>
            </div>
            
            <!-- Recent Decisions -->
            <div class="card">
                <h2>🧠 Recent Decisions</h2>
                <div id="recent-decisions">
                    <div class="activity-detail">No decisions yet</div>
                </div>
            </div>
            
            <!-- Recent Completions -->
            <div class="card">
                <h2>✅ Recent Completions</h2>
                <div id="recent-completions">
                    <div class="activity-detail">No completions yet</div>
                </div>
            </div>
            
            <!-- Failures -->
            <div class="card">
                <h2>❌ Recent Failures</h2>
                <div id="recent-failures">
                    <div class="activity-detail">No failures</div>
                </div>
            </div>
            
            <!-- Thread Activities -->
            <div class="card">
                <h2>🔄 Thread Activities</h2>
                <div id="thread-activities">
                    <div class="activity-detail">No thread activities</div>
                </div>
            </div>
        </div>
        
        <div class="refresh-info">
            Dashboard updates in real-time via WebSocket | Last update: <span id="last-update">Never</span>
        </div>
    </div>
    
    <script>
        let ws = null;
        const wsUrl = `ws://${window.location.host}/activity/stream`;
        
        function connectWebSocket() {
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                console.log('WebSocket connected');
                document.getElementById('websocket-status').textContent = '🟢 Connected';
                document.getElementById('websocket-status').classList.remove('disconnected');
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleActivityUpdate(data);
                updateLastUpdate();
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            ws.onclose = () => {
                console.log('WebSocket disconnected');
                document.getElementById('websocket-status').textContent = '🔴 Disconnected';
                document.getElementById('websocket-status').classList.add('disconnected');
                // Reconnect after 5 seconds
                setTimeout(connectWebSocket, 5000);
            };
        }
        
        function handleActivityUpdate(data) {
            if (data.event === 'connected') {
                // Initial state
                if (data.active_activities) {
                    updateActiveActivities(data.active_activities);
                }
            } else {
                // Activity update
                fetchAndUpdateDashboard();
            }
        }
        
        function formatActivity(activity) {
            const statusClass = activity.status.toLowerCase().replace('_', '-');
            const duration = activity.duration_ms ? `${Math.round(activity.duration_ms)}ms` : '';
            
            let detail = '';
            if (activity.status === 'planned') {
                detail = `<div class="activity-detail">📋 Will: ${activity.what_it_will_do}</div>`;
            } else if (activity.status === 'in_progress') {
                detail = `<div class="activity-detail">⏳ Doing: ${activity.what_its_doing}</div>`;
            } else if (activity.status === 'completed') {
                detail = `<div class="activity-detail">✅ Did: ${activity.what_it_did}</div>`;
                if (duration) detail += `<div class="activity-time">Duration: ${duration}</div>`;
            } else if (activity.status === 'failed') {
                detail = `<div class="activity-detail">❌ Error: ${activity.error}</div>`;
            }
            
            const threadInfo = activity.thread_id ? 
                `<span class="thread-info">Thread: ${activity.thread_id}</span>` : '';
            
            return `
                <div class="activity ${statusClass}">
                    <div class="activity-header">
                        <span class="activity-name">${activity.name}</span>
                        <span class="activity-status">${activity.status}</span>
                    </div>
                    ${detail}
                    ${threadInfo}
                </div>
            `;
        }
        
        function updateActiveActivities(activities) {
            const container = document.getElementById('active-activities');
            if (activities.length === 0) {
                container.innerHTML = '<div class="activity-detail">No active activities</div>';
            } else {
                container.innerHTML = activities.map(formatActivity).join('');
            }
            document.getElementById('active-count').textContent = activities.length;
        }
        
        async function fetchAndUpdateDashboard() {
            try {
                // Fetch stats
                const statsResponse = await fetch('/activity/stats');
                const stats = await statsResponse.json();
                
                document.getElementById('total-count').textContent = stats.total_activities;
                document.getElementById('success-rate').textContent = 
                    Math.round(100 - stats.failure_rate) + '%';
                document.getElementById('avg-duration').textContent = 
                    Math.round(stats.average_duration_ms) + 'ms';
                
                // Fetch active activities
                const activeResponse = await fetch('/activity/active');
                const active = await activeResponse.json();
                updateActiveActivities(active);
                
                // Fetch recent activities
                const allResponse = await fetch('/activity/all?limit=20');
                const all = await allResponse.json();
                
                // Update different sections
                const decisions = all.filter(a => a.type === 'decision').slice(0, 5);
                const completions = all.filter(a => a.status === 'completed').slice(0, 5);
                const failures = all.filter(a => a.status === 'failed').slice(0, 5);
                const threads = all.filter(a => a.type === 'thread').slice(0, 5);
                
                updateSection('recent-decisions', decisions);
                updateSection('recent-completions', completions);
                updateSection('recent-failures', failures);
                updateSection('thread-activities', threads);
                
            } catch (error) {
                console.error('Error fetching dashboard data:', error);
            }
        }
        
        function updateSection(sectionId, activities) {
            const container = document.getElementById(sectionId);
            if (activities.length === 0) {
                container.innerHTML = '<div class="activity-detail">None</div>';
            } else {
                container.innerHTML = activities.map(formatActivity).join('');
            }
        }
        
        function updateLastUpdate() {
            const now = new Date().toLocaleTimeString();
            document.getElementById('last-update').textContent = now;
        }
        
        // Initialize
        connectWebSocket();
        fetchAndUpdateDashboard();
        
        // Periodic refresh as backup
        setInterval(fetchAndUpdateDashboard, 5000);
    </script>
</body>
</html>
"""

def get_dashboard_html() -> str:
    """Return the dashboard HTML."""
    return DASHBOARD_HTML