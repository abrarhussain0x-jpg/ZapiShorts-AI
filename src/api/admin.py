"""Admin UI — beautiful HTML dashboard served via FastAPI router."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from src.config.settings import settings

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_ui():
    """Returns the main HTML dashboard for ZAPI."""
    if not settings.admin_ui_enabled:
        return HTMLResponse(
            "<h1>Admin UI is disabled in settings.</h1>", status_code=403
        )

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ZAPI — Command Center</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #090a0f;
                --surface-raw: 15, 18, 26;
                --surface: rgba(var(--surface-raw), 0.7);
                --surface-hover: rgba(var(--surface-raw), 0.95);
                --border: rgba(255, 255, 255, 0.06);
                --border-focus: rgba(99, 102, 241, 0.4);
                --primary: #6366f1;
                --primary-glow: rgba(99, 102, 241, 0.15);
                --primary-hover: #4f46e5;
                --success: #10b981;
                --warning: #f59e0b;
                --danger: #ef4444;
                --text: #f3f4f6;
                --text-dim: #9ca3af;
                --text-muted: #6b7280;
                --font: 'Plus Jakarta Sans', 'Outfit', sans-serif;
            }}
            
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            
            body {{
                background-color: var(--bg);
                color: var(--text);
                font-family: var(--font);
                -webkit-font-smoothing: antialiased;
                padding: 2rem;
                max-width: 1400px;
                margin: 0 auto;
                min-height: 100vh;
                background-image: 
                    radial-gradient(circle at 80% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 40%),
                    radial-gradient(circle at 10% 80%, rgba(16, 185, 129, 0.08) 0%, transparent 40%);
                background-attachment: fixed;
            }}

            /* Scrollbar */
            ::-webkit-scrollbar {{
                width: 6px;
                height: 6px;
            }}
            ::-webkit-scrollbar-track {{
                background: rgba(0, 0, 0, 0.2);
            }}
            ::-webkit-scrollbar-thumb {{
                background: rgba(255, 255, 255, 0.1);
                border-radius: 99px;
            }}
            ::-webkit-scrollbar-thumb:hover {{
                background: rgba(255, 255, 255, 0.2);
            }}
            
            /* Header */
            header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 2.5rem;
                padding-bottom: 1.5rem;
                border-bottom: 1px solid var(--border);
            }}
            
            h1 {{
                font-size: 1.75rem;
                font-weight: 700;
                letter-spacing: -0.03em;
                background: linear-gradient(135deg, #fff 0%, #a5b4fc 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }}
            
            .logo-img {{
                width: 36px;
                height: 36px;
                object-fit: contain;
                border-radius: 8px;
                box-shadow: 0 0 15px rgba(99, 102, 241, 0.3);
            }}

            .header-actions {{
                display: flex;
                align-items: center;
                gap: 1rem;
            }}
            
            .status-badge {{
                background: rgba(16, 185, 129, 0.06);
                color: var(--success);
                padding: 0.375rem 1rem;
                border-radius: 999px;
                font-size: 0.85rem;
                font-weight: 600;
                border: 1px solid rgba(16, 185, 129, 0.15);
                display: flex;
                align-items: center;
                gap: 0.5rem;
                box-shadow: 0 0 10px rgba(16, 185, 129, 0.05);
            }}

            .status-badge::before {{
                content: "";
                display: inline-block;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: var(--success);
                box-shadow: 0 0 8px var(--success);
            }}
            
            /* Stats Grid */
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 1.25rem;
                margin-bottom: 2.5rem;
            }}
            
            .stat-card {{
                background: var(--surface);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 1.5rem;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                position: relative;
                overflow: hidden;
            }}
            
            .stat-card::before {{
                content: "";
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%);
                pointer-events: none;
            }}
            
            .stat-card:hover {{
                transform: translateY(-4px);
                border-color: var(--primary);
                box-shadow: 0 12px 30px rgba(99, 102, 241, 0.1);
            }}
            
            .stat-value {{
                font-size: 2.25rem;
                font-weight: 700;
                margin-bottom: 0.375rem;
                color: #ffffff;
                letter-spacing: -0.02em;
            }}
            
            .stat-label {{
                color: var(--text-dim);
                font-size: 0.8rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.08em;
            }}
            
            /* Navigation Tabs */
            .tabs {{
                display: flex;
                gap: 0.5rem;
                border-bottom: 1px solid var(--border);
                margin-bottom: 2rem;
                padding-bottom: 0.5rem;
            }}
            
            .tab-btn {{
                background: transparent;
                border: none;
                color: var(--text-dim);
                padding: 0.75rem 1.5rem;
                font-size: 0.95rem;
                font-weight: 600;
                cursor: pointer;
                border-radius: 8px;
                transition: all 0.2s ease;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}
            
            .tab-btn:hover {{
                color: #ffffff;
                background: rgba(255, 255, 255, 0.03);
            }}
            
            .tab-btn.active {{
                color: #ffffff;
                background: var(--primary-glow);
                box-shadow: inset 0 0 10px rgba(99, 102, 241, 0.1);
                border: 1px solid rgba(99, 102, 241, 0.2);
            }}

            .tab-content {{
                display: none;
                animation: fadeIn 0.4s ease-out;
            }}

            .tab-content.active {{
                display: block;
            }}

            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(10px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            
            /* Cards Panels */
            .panel {{
                background: var(--surface);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 2rem;
                margin-bottom: 2rem;
                position: relative;
            }}

            .panel-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1.5rem;
            }}

            .panel-title {{
                font-size: 1.25rem;
                font-weight: 600;
                color: #ffffff;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}
            
            /* Form inputs */
            .input-group-grid {{
                display: grid;
                grid-template-columns: 1fr auto;
                gap: 1rem;
                margin-bottom: 1.5rem;
            }}

            .form-row {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1.25rem;
                margin-bottom: 1.5rem;
            }}

            .field-container {{
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }}

            .field-container label {{
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--text-dim);
            }}
            
            input[type="url"], select, input[type="number"] {{
                width: 100%;
                background: rgba(0, 0, 0, 0.3);
                border: 1px solid var(--border);
                color: var(--text);
                padding: 0.85rem 1.2rem;
                border-radius: 10px;
                font-family: inherit;
                font-size: 0.95rem;
                outline: none;
                transition: all 0.2s ease;
            }}
            
            input[type="url"]:focus, select:focus, input[type="number"]:focus {{
                border-color: var(--primary);
                box-shadow: 0 0 0 3px var(--primary-glow);
                background: rgba(0, 0, 0, 0.5);
            }}
            
            /* Buttons */
            button.btn-primary {{
                background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover) 100%);
                color: white;
                border: none;
                padding: 0.85rem 1.75rem;
                border-radius: 10px;
                font-weight: 600;
                font-size: 0.95rem;
                cursor: pointer;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
            }}
            
            button.btn-primary:hover {{
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
            }}

            button.btn-primary:active {{
                transform: translateY(0);
            }}
            
            button:disabled {{
                opacity: 0.5;
                cursor: not-allowed;
                transform: none !important;
                box-shadow: none !important;
            }}

            button.btn-secondary {{
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--border);
                color: var(--text);
                padding: 0.6rem 1.2rem;
                border-radius: 8px;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s ease;
            }}

            button.btn-secondary:hover {{
                background: rgba(255, 255, 255, 0.1);
                border-color: rgba(255, 255, 255, 0.2);
            }}
            
            /* Tables */
            .table-container {{
                overflow-x: auto;
                border-radius: 12px;
                border: 1px solid var(--border);
                background: rgba(0, 0, 0, 0.2);
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                text-align: left;
            }}
            
            th {{
                padding: 1rem 1.5rem;
                color: var(--text-dim);
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                font-weight: 600;
                border-bottom: 1px solid var(--border);
                background: rgba(0, 0, 0, 0.3);
            }}
            
            td {{
                padding: 1rem 1.5rem;
                border-bottom: 1px solid var(--border);
                font-size: 0.9rem;
                color: var(--text);
            }}
            
            tr:last-child td {{
                border-bottom: none;
            }}
            
            tr:hover td {{
                background: rgba(255, 255, 255, 0.02);
            }}
            
            /* Badges & Dots */
            .badge {{
                display: inline-flex;
                align-items: center;
                gap: 0.375rem;
                padding: 0.25rem 0.75rem;
                border-radius: 999px;
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}

            .badge-running {{
                background: rgba(99, 102, 241, 0.1);
                color: var(--primary);
                border: 1px solid rgba(99, 102, 241, 0.2);
            }}

            .badge-completed {{
                background: rgba(16, 185, 129, 0.1);
                color: var(--success);
                border: 1px solid rgba(16, 185, 129, 0.2);
            }}

            .badge-failed {{
                background: rgba(239, 68, 68, 0.1);
                color: var(--danger);
                border: 1px solid rgba(239, 68, 68, 0.2);
            }}

            .badge-pending {{
                background: rgba(245, 158, 11, 0.1);
                color: var(--warning);
                border: 1px solid rgba(245, 158, 11, 0.2);
            }}

            .dot {{
                width: 6px;
                height: 6px;
                border-radius: 50%;
                display: inline-block;
            }}
            .dot-running {{ background: var(--primary); box-shadow: 0 0 6px var(--primary); }}
            .dot-completed {{ background: var(--success); }}
            .dot-failed {{ background: var(--danger); }}
            .dot-pending {{ background: var(--warning); }}

            /* Progress Bar */
            .progress-container {{
                margin-top: 1.5rem;
                padding: 1.5rem;
                border-radius: 12px;
                background: rgba(0, 0, 0, 0.3);
                border: 1px solid var(--border);
            }}
            .progress-header {{
                display: flex;
                justify-content: space-between;
                font-size: 0.875rem;
                margin-bottom: 0.75rem;
            }}
            .progress-bg {{
                background: rgba(255, 255, 255, 0.08);
                height: 8px;
                border-radius: 4px;
                overflow: hidden;
            }}
            .progress-fill {{
                background: linear-gradient(90deg, var(--primary) 0%, #818cf8 100%);
                height: 100%;
                width: 0%;
                transition: width 0.4s cubic-bezier(0.1, 0.8, 0.2, 1);
                box-shadow: 0 0 10px rgba(99, 102, 241, 0.5);
            }}
            
            /* Short Grid Gallery */
            .shorts-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 1.5rem;
            }}

            .short-card {{
                background: rgba(var(--surface-raw), 0.4);
                border: 1px solid var(--border);
                border-radius: 16px;
                overflow: hidden;
                transition: all 0.3s ease;
                display: flex;
                flex-direction: column;
            }}

            .short-card:hover {{
                transform: translateY(-5px);
                border-color: rgba(99, 102, 241, 0.3);
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
            }}

            .short-thumb {{
                width: 100%;
                height: 180px;
                object-fit: cover;
                background: #11131c;
                border-bottom: 1px solid var(--border);
            }}

            .short-body {{
                padding: 1.25rem;
                flex-grow: 1;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }}

            .short-title {{
                font-size: 0.95rem;
                font-weight: 600;
                margin-bottom: 0.5rem;
                color: #ffffff;
                line-height: 1.4;
            }}

            .short-meta {{
                font-size: 0.8rem;
                color: var(--text-dim);
                display: flex;
                justify-content: space-between;
                margin-bottom: 1rem;
            }}

            .short-actions {{
                display: flex;
                gap: 0.5rem;
            }}
            
            /* Toast Notifications */
            #toast {{
                position: fixed;
                bottom: 2rem;
                right: 2rem;
                background: rgba(15, 18, 26, 0.9);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid var(--border);
                padding: 1.25rem 2rem;
                border-radius: 12px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.6);
                transform: translateY(150%);
                transition: transform 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                z-index: 9999;
                display: flex;
                align-items: center;
                gap: 0.75rem;
                font-weight: 500;
            }}
            #toast.show {{
                transform: translateY(0);
            }}

            /* Utils */
            .text-center {{ text-align: center; }}
            .py-8 {{ padding-top: 2rem; padding-bottom: 2rem; }}
        </style>
    </head>
    <body>
        <header>
            <h1>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="url(#logoGrad)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 6px rgba(99, 102, 241, 0.5))">
                    <defs>
                        <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#818cf8"/>
                            <stop offset="100%" stop-color="#4f46e5"/>
                        </linearGradient>
                    </defs>
                    <polygon points="23 7 16 12 23 17 23 7"></polygon>
                    <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
                </svg>
                ZAPI Command Center
            </h1>
            <div class="header-actions">
                <div class="status-badge" id="conn-status">API Connected</div>
            </div>
        </header>

        <!-- Stats Grid -->
        <div class="stats-grid" id="stats">
            <div class="stat-card">
                <div class="stat-value" id="stat-src-vids">--</div>
                <div class="stat-label">Source Videos</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-proc-shorts">--</div>
                <div class="stat-label">Processed Shorts</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-uploads">--</div>
                <div class="stat-label">Successful Uploads</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-views">--</div>
                <div class="stat-label">Total Views</div>
            </div>
        </div>

        <!-- Tab Navigation -->
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('tab-dashboard')">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9"></rect><rect x="14" y="3" width="7" height="5"></rect><rect x="14" y="12" width="7" height="9"></rect><rect x="3" y="16" width="7" height="5"></rect></svg>
                Dashboard
            </button>
            <button class="tab-btn" onclick="switchTab('tab-videos'); fetchSourceVideos();">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 7l-7 5 7 5V7z"></path><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
                Source Videos
            </button>
            <button class="tab-btn" onclick="switchTab('tab-shorts'); fetchShorts();">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"></path><path d="M2 17l10 5 10-5"></path><path d="M2 12l10 5 10-5"></path></svg>
                Processed Shorts
            </button>
        </div>

        <!-- Dashboard Tab -->
        <div id="tab-dashboard" class="tab-content active">
            <div class="panel">
                <h3 class="panel-title">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3z"></path><path d="M9 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3z"></path></svg>
                    Dispatch Automation Job
                </h3>
                <form id="process-form" style="margin-top: 1.5rem;">
                    <div class="form-row">
                        <div class="field-container" style="grid-column: span 2;">
                            <label for="yt-url">YouTube Video or Channel URL</label>
                            <input type="url" id="yt-url" placeholder="https://www.youtube.com/watch?v=..." required>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="field-container">
                            <label for="shorts-count">Shorts count</label>
                            <input type="number" id="shorts-count" min="1" max="10" value="3">
                        </div>
                        <div class="field-container">
                            <label for="upload-option">Facebook Upload</label>
                            <select id="upload-option">
                                <option value="true">Enable Auto Upload</option>
                                <option value="false">Download & Clip Only</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="btn-primary" id="submit-btn" style="width: 100%; margin-top: 0.5rem;">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                        Initiate Pipeline
                    </button>
                </form>

                <div id="live-progress" class="progress-container" style="display: none;">
                    <div class="progress-header">
                        <span id="lp-msg" style="color: var(--text-dim); font-weight: 500;">Initializing...</span>
                        <span id="lp-pct" style="font-weight: 700; color: var(--primary);">0%</span>
                    </div>
                    <div class="progress-bg">
                        <div class="progress-fill" id="lp-fill"></div>
                    </div>
                </div>
            </div>

            <!-- Recent Jobs -->
            <div class="panel">
                <div class="panel-header">
                    <h3 class="panel-title">Recent Jobs</h3>
                    <button class="btn-secondary" onclick="fetchJobs()">Refresh</button>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Job ID</th>
                                <th>Type</th>
                                <th>Status</th>
                                <th>Progress</th>
                                <th>Started At</th>
                                <th>Duration</th>
                            </tr>
                        </thead>
                        <tbody id="jobs-body">
                            <tr><td colspan="6" class="text-center py-8" style="color: var(--text-dim);">Loading active jobs...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Source Videos Tab -->
        <div id="tab-videos" class="tab-content">
            <div class="panel">
                <div class="panel-header">
                    <h3 class="panel-title">Downloaded Source Videos</h3>
                    <button class="btn-secondary" onclick="fetchSourceVideos()">Refresh</button>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Video Details</th>
                                <th>Duration</th>
                                <th>File Size</th>
                                <th>Status</th>
                                <th>Retries</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody id="videos-body">
                            <tr><td colspan="6" class="text-center py-8" style="color: var(--text-dim);">Loading source videos...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Processed Shorts Tab -->
        <div id="tab-shorts" class="tab-content">
            <div class="panel">
                <div class="panel-header">
                    <h3 class="panel-title">Generated Shorts Gallery</h3>
                    <button class="btn-secondary" onclick="fetchShorts()">Refresh</button>
                </div>
                <div class="shorts-grid" id="shorts-body">
                    <div style="grid-column: span 3; text-align: center; color: var(--text-dim);" class="py-8">Loading shorts...</div>
                </div>
            </div>
        </div>

        <div id="toast"></div>

        <script>
            function showToast(msg, isError=false) {{
                const toast = document.getElementById('toast');
                toast.innerHTML = `<span style="color: ${{isError ? 'var(--danger)' : 'var(--success)'}}">●</span> ${{msg}}`;
                toast.classList.add('show');
                setTimeout(() => toast.classList.remove('show'), 4000);
            }}

            function switchTab(tabId) {{
                document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                
                const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(btn => btn.getAttribute('onclick').includes(tabId));
                if (activeBtn) activeBtn.classList.add('active');
                
                document.getElementById(tabId).classList.add('active');
            }}

            async function fetchStats() {{
                try {{
                    const res = await fetch('/api/analytics/dashboard');
                    if (!res.ok) return;
                    const data = await res.json();
                    if (data.pipeline) {{
                        document.getElementById('stat-src-vids').textContent = data.pipeline.source_videos || '0';
                        document.getElementById('stat-proc-shorts').textContent = data.pipeline.processed_shorts || '0';
                        document.getElementById('stat-uploads').textContent = data.pipeline.successful_uploads || '0';
                        document.getElementById('stat-views').textContent = (data.engagement?.total_views || 0).toLocaleString();
                    }}
                }} catch (e) {{ console.error('Stats fetch failed', e); }}
            }}

            async function fetchJobs() {{
                try {{
                    const res = await fetch('/api/jobs?size=10');
                    if (!res.ok) return;
                    const data = await res.json();
                    const tbody = document.getElementById('jobs-body');
                    if (!data.jobs || data.jobs.length === 0) {{
                        tbody.innerHTML = '<tr><td colspan="6" class="text-center py-8" style="color: var(--text-dim);">No active jobs found.</td></tr>';
                        return;
                    }}
                    tbody.innerHTML = data.jobs.map(j => {{
                        const statusClass = `badge-${{j.status}}`;
                        return `
                            <tr>
                                <td style="font-family: monospace; color: var(--text-dim); font-size: 0.85rem;">${{j.id}}</td>
                                <td style="text-transform: capitalize; font-weight: 500;">${{j.job_type}}</td>
                                <td><span class="badge ${{statusClass}}"><span class="dot dot-${{j.status}}"></span>${{j.status}}</span></td>
                                <td style="font-weight: 600; color: var(--primary);">${{j.progress}}%</td>
                                <td style="color: var(--text-dim);">${{j.started_at ? new Date(j.started_at).toLocaleString() : '-'}}</td>
                                <td>${{j.duration_seconds ? j.duration_seconds.toFixed(1) + 's' : '-'}}</td>
                            </tr>
                        `;
                    }}).join('');
                }} catch (e) {{ console.error('Jobs fetch failed', e); }}
            }}

            async function fetchSourceVideos() {{
                try {{
                    const res = await fetch('/api/videos/videos');
                    if (!res.ok) return;
                    const data = await res.json();
                    const tbody = document.getElementById('videos-body');
                    if (!data.videos || data.videos.length === 0) {{
                        tbody.innerHTML = '<tr><td colspan="6" class="text-center py-8" style="color: var(--text-dim);">No source videos found.</td></tr>';
                        return;
                    }}
                    tbody.innerHTML = data.videos.map(v => {{
                        const statusClass = `badge-${{v.status}}`;
                        const sizeMB = v.file_size_bytes ? (v.file_size_bytes / 1048576).toFixed(1) + ' MB' : '-';
                        return `
                            <tr>
                                <td>
                                    <div style="font-weight: 600; color: #fff; margin-bottom: 0.25rem;">${{v.title}}</div>
                                    <div style="font-size: 0.75rem; color: var(--text-dim); font-family: monospace;">ID: ${{v.id}} | Channel: ${{v.channel_name || '-'}}</div>
                                </td>
                                <td>${{v.duration_seconds ? Math.floor(v.duration_seconds/60) + 'm ' + (v.duration_seconds%60) + 's' : '-'}}</td>
                                <td>${{sizeMB}}</td>
                                <td><span class="badge ${{statusClass}}"><span class="dot dot-${{v.status}}"></span>${{v.status}}</span></td>
                                <td>${{v.retry_count || 0}}</td>
                                <td>
                                    <button class="btn-secondary" onclick="retryVideo('${{v.id}}')" style="padding: 0.4rem 0.8rem; font-size: 0.8rem;">Retry</button>
                                </td>
                            </tr>
                        `;
                    }}).join('');
                }} catch (e) {{ console.error('Videos fetch failed', e); }}
            }}

            async function retryVideo(videoId) {{
                try {{
                    const res = await fetch(`/api/videos/retry/${{videoId}}`, {{ method: 'POST' }});
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Retry failed');
                    showToast('Retry job dispatched successfully');
                    switchTab('tab-dashboard');
                    setupWebSocket(data.websocket_url);
                }} catch (err) {{
                    showToast(err.message, true);
                }}
            }}

            async function fetchShorts() {{
                try {{
                    const res = await fetch('/api/videos/shorts');
                    if (!res.ok) return;
                    const data = await res.json();
                    const grid = document.getElementById('shorts-body');
                    if (!data.shorts || data.shorts.length === 0) {{
                        grid.innerHTML = '<div style="grid-column: span 3; text-align: center; color: var(--text-dim);" class="py-8">No processed shorts found.</div>';
                        return;
                    }}
                    grid.innerHTML = data.shorts.map(s => {{
                        const sizeMB = s.file_size_bytes ? (s.file_size_bytes / 1048576).toFixed(1) + ' MB' : '-';
                        return `
                            <div class="short-card">
                                <div style="position: relative;">
                                    <div class="short-thumb" style="display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-weight: 500;">
                                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>
                                    </div>
                                    <span class="badge badge-completed" style="position: absolute; top: 10px; right: 10px; font-size: 0.7rem;">${{s.platform_profile}}</span>
                                </div>
                                <div class="short-body">
                                    <div class="short-title">${{s.output_filename || 'Clip Short'}}</div>
                                    <div class="short-meta">
                                        <span>${{s.duration_seconds}}s | ${{s.resolution}}</span>
                                        <span>${{sizeMB}}</span>
                                    </div>
                                </div>
                            </div>
                        `;
                    }}).join('');
                }} catch (e) {{ console.error('Shorts fetch failed', e); }}
            }}

            function setupWebSocket(websocketUrl) {{
                const lp = document.getElementById('live-progress');
                lp.style.display = 'block';
                
                const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${{wsProto}}//${{window.location.host}}${{websocketUrl}}`;
                const ws = new WebSocket(wsUrl);
                
                ws.onmessage = (event) => {{
                    const msg = JSON.parse(event.data);
                    if (msg.type === 'ping') return;
                    
                    document.getElementById('lp-msg').textContent = `[${{msg.stage}}] ${{msg.message}}`;
                    document.getElementById('lp-pct').textContent = `${{Math.round(msg.progress)}}%`;
                    document.getElementById('lp-fill').style.width = `${{msg.progress}}%`;
                    
                    if (msg.progress >= 100 || msg.stage === 'failed') {{
                        ws.close();
                        setTimeout(() => {{ 
                            lp.style.display = 'none'; 
                            fetchStats(); 
                            fetchJobs(); 
                        }}, 3000);
                    }}
                }};
            }}

            document.getElementById('process-form').addEventListener('submit', async (e) => {{
                e.preventDefault();
                const btn = document.getElementById('submit-btn');
                const url = document.getElementById('yt-url').value;
                const count = parseInt(document.getElementById('shorts-count').value);
                const upload = document.getElementById('upload-option').value === 'true';
                btn.disabled = true;
                
                try {{
                    const res = await fetch('/api/videos/process', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ 
                            youtube_url: url, 
                            create_shorts: true, 
                            upload_to_facebook: upload,
                            num_shorts: count
                        }})
                    }});
                    const data = await res.json();
                    
                    if (!res.ok) throw new Error(data.error?.message || 'Processing failed');
                    
                    document.getElementById('yt-url').value = '';
                    showToast('Pipeline job dispatched successfully!');
                    
                    setupWebSocket(data.websocket_url);
                    
                }} catch (err) {{
                    showToast(err.message, true);
                }} finally {{
                    btn.disabled = false;
                }}
            }});

            // Initial load
            fetchStats();
            fetchJobs();
            
            // Auto refresh stats and jobs table
            setInterval(() => {{
                if (document.visibilityState === 'visible') {{
                    fetchStats();
                    fetchJobs();
                }}
            }}, 8000);
        </script>
    </body>
    </html>
    """
