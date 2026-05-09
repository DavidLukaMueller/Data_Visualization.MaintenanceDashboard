import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.gridspec as gridspec
from matplotlib.patches import Polygon, Patch
from matplotlib.widgets import Button, RectangleSelector
import numpy as np
from collections import deque
import sys
import os
import warnings

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# Load Data
df = pd.read_csv(resource_path('ai4i2020.csv'))

# Cumulative Failures calculation
for col in ['TWF', 'HDF', 'PWF', 'OSF', 'RNF']:
    df[f'cum_{col}'] = df[col].cumsum()

# Globals & Configuration
UPDATE_INTERVAL_MS = 200  
WINDOW_SIZE = 60          
MA_WINDOW = 10            

x_time = deque(maxlen=WINDOW_SIZE)
y_wear = deque(maxlen=WINDOW_SIZE)
y_torque = deque(maxlen=WINDOW_SIZE)

# Control Memory Log: Only saves the last 50 tool swaps for the report
tool_swaps_log = deque(maxlen=50)

system_state = {
    'step': 0, 'wear': 0, 'torque': 0, 'load': 0, 'osf_status': 'Normal',
    'twf_mean': -1, 'twf_early': -1, 'twf_late': -1, 'osf_pred': -1,
    'failures': {'TWF': 0, 'HDF': 0, 'PWF': 0, 'OSF': 0, 'RNF': 0}
}
anim_running = True

# Colors
BG_COLOR = '#2c3545'         
PANEL_COLOR = '#16213e'      
GRID_COLOR = '#3b475e'       
TEXT_COLOR = '#e0e0e0'       
LINE_WEAR = '#ffffff'        
LINE_PRED = '#f9a826'        
COLOR_DANGER = '#e63946'     
COLOR_WARN = '#f4a261'       
COLOR_SAFE = '#2a9d8f'       
BAR_COLORS = ['#3a86ff', '#fb5607', '#ffbe0b', '#ff006e', '#9ca3af'] 
HIGHLIGHT_COLOR = '#ffbe0b'

# ==========================================
# REPORT GENERATION FUNCTION
# ==========================================
def generate_printable_report():
    fig_rep = plt.figure(figsize=(16, 9))
    fig_rep.canvas.manager.set_window_title('Executive Summary')
    fig_rep.patch.set_facecolor(BG_COLOR)
    
    gs_rep = gridspec.GridSpec(4, 3, width_ratios=[0.8, 1.2, 2.0], height_ratios=[1.0, 0.4, 1.2, 0.8], wspace=0.35, hspace=0.6)
    
    curr_wear = system_state['wear']
    curr_load = system_state['load']
    
    is_critical = curr_load >= 11000 or curr_wear >= 200
    is_warn = curr_wear > 150 and not is_critical
    
    if is_critical:
        sys_status = "CRITICAL RISK - SWAP TOOL IMMEDIATELY"
        status_color = '#ff4d4d' 
        text_bg = '#4a0a10'      
    elif is_warn:
        sys_status = "AT RISK - PREPARE FOR SWAP"
        status_color = COLOR_WARN
        text_bg = '#422811'      
    else:
        sys_status = "OPERATIONAL (HEALTHY)"
        status_color = COLOR_SAFE
        text_bg = PANEL_COLOR

    fig_rep.suptitle(f"PLANT OPERATIONS: EXECUTIVE SUMMARY", fontsize=20, fontweight='bold', color=TEXT_COLOR, y=0.96)
    
    # 1. Failures Plot
    ax_fails = fig_rep.add_subplot(gs_rep[0:4, 0])
    ax_fails.set_facecolor(PANEL_COLOR)
    f = system_state['failures']
    
    w = 0.28
    x_mach = [1 - w, 1, 1 + w]
    x_tool = [3 - w/2, 3 + w/2]
    
    b_pwf = ax_fails.bar(x_mach[0], f['PWF'], width=w, color=BAR_COLORS[2])
    b_hdf = ax_fails.bar(x_mach[1], f['HDF'], width=w, color=BAR_COLORS[1])
    b_rnf = ax_fails.bar(x_mach[2], f['RNF'], width=w, color=BAR_COLORS[4])
    b_twf = ax_fails.bar(x_tool[0], f['TWF'], width=w, color=BAR_COLORS[0])
    b_osf = ax_fails.bar(x_tool[1], f['OSF'], width=w, color=BAR_COLORS[3])
    
    max_val = max(f.values()) if f else 0
    upper_limit = max(5, max_val * 1.2)
    ax_fails.set_ylim(0, upper_limit) 
    ax_fails.set_xlim(0, 4)  
    
    for bars in [b_pwf, b_hdf, b_rnf, b_twf, b_osf]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax_fails.text(bar.get_x() + bar.get_width()/2., height + (upper_limit*0.02),
                              f'{int(height)}', ha='center', va='bottom', color=TEXT_COLOR, fontsize=9, fontweight='bold')

    ax_fails.set_xticks([1, 3])
    ax_fails.set_xticklabels(['Machine\nFailures', 'Tool\nFailures'], fontweight='bold', color=TEXT_COLOR, fontsize=11)
    ax_fails.spines['top'].set_visible(False)
    ax_fails.spines['right'].set_visible(False)
    ax_fails.grid(axis='y', linestyle='--', color=GRID_COLOR, alpha=0.5)
    ax_fails.set_title("", fontweight='bold', color=TEXT_COLOR, pad=75)
    
    leg_handles = [b_pwf[0], b_rnf[0], b_hdf[0], b_osf[0], b_twf[0]]
    leg_labels = ['Power (PWF)', 'Random (RNF)', 'Heat (HDF)', 'Strain (OSF)', 'Wear (TWF)']
    ax_fails.legend(handles=leg_handles, labels=leg_labels, loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=2, 
                    facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9, columnspacing=0.8)

    # 2. Text Summary
    ax_text = fig_rep.add_subplot(gs_rep[0, 1])
    ax_text.axis('off')
    maint_txt = f"Next Maint: ~{int(system_state['twf_mean'])} cycles" if system_state['twf_mean'] != -1 else "Next Maint: Optimal/Stable"
    osf_txt = f"Stress Trajectory: {system_state['osf_status']}"
    report_text = f"SYSTEM STATUS:\n{sys_status}\n\n{maint_txt}\n{osf_txt}"
    ax_text.text(0.5, 0.5, report_text, fontsize=11, family='sans-serif', color=status_color, fontweight='bold',
                 ha='center', va='center', bbox=dict(facecolor=text_bg, edgecolor=status_color, pad=12, linewidth=3))

    # 3. Tool Wear Bar
    ax_load = fig_rep.add_subplot(gs_rep[1, 1])
    ax_load.set_facecolor(PANEL_COLOR)
    ax_load.barh([0], [250], color=PANEL_COLOR, edgecolor=GRID_COLOR, height=0.5) 
    ax_load.barh([0], [curr_wear], color=status_color, height=0.5) 
    ax_load.axvspan(200, 250, color=COLOR_DANGER, alpha=0.2)
    ax_load.axvline(200, color=COLOR_DANGER, linestyle=':', linewidth=2)
    ax_load.set_xlim(0, 250); ax_load.set_yticks([])
    ax_load.set_title("Current Tool Progress to Failure", fontweight='bold', fontsize=10, color=TEXT_COLOR)
    ax_load.spines['left'].set_visible(False); ax_load.spines['right'].set_visible(False); ax_load.spines['top'].set_visible(False)
    ax_load.tick_params(colors=TEXT_COLOR)

    # Process Historical Swaps from Memory (Max 50)
    swaps_eol_wear, swaps_eol_reason, swaps_eol_color = [], [], []
    premature_counts = {'HDF': 0, 'PWF': 0, 'OSF': 0, 'RNF': 0, 'TWF': 0}
    
    for swap in tool_swaps_log:
        if swap['wear'] >= 150:
            swaps_eol_wear.append(swap['wear'])
            swaps_eol_reason.append(swap['reason'])
            swaps_eol_color.append(swap['color'])
        else:
            if swap['reason'] != 'Proactive':
                premature_counts[swap['reason']] += 1

    swaps_eol_wear = swaps_eol_wear[-6:]
    swaps_eol_reason = swaps_eol_reason[-6:]
    swaps_eol_color = swaps_eol_color[-6:]

    # 4. Swaps EOL Plot
    ax_swaps = fig_rep.add_subplot(gs_rep[2, 1])
    ax_swaps.set_facecolor(PANEL_COLOR)
    if len(swaps_eol_wear) > 0:
        y_pos = np.arange(len(swaps_eol_wear))
        widths = [w - 150 for w in swaps_eol_wear]
        ax_swaps.barh(y_pos, widths, left=150, color=swaps_eol_color, height=0.6, edgecolor=BG_COLOR)
        for y, w, r in zip(y_pos, swaps_eol_wear, swaps_eol_reason):
            if r != 'Proactive':
                ax_swaps.text(w + 2, y, r, color=COLOR_DANGER, va='center', fontweight='bold', fontsize=9)
        ax_swaps.set_yticks(y_pos)
        ax_swaps.set_yticklabels([f"#{i+1}" for i in range(len(swaps_eol_wear))], color=TEXT_COLOR)
    else:
        ax_swaps.text(205, 0, "No End-of-Life Swaps Recorded", ha='center', va='center', color=TEXT_COLOR)
        ax_swaps.set_yticks([])
        
    ax_swaps.axvline(200, color=COLOR_DANGER, linestyle=':', linewidth=2, zorder=1)
    ax_swaps.axvspan(200, 260, color=COLOR_DANGER, alpha=0.1, zorder=0)
    ax_swaps.set_title("End-of-Life Swaps (Zoomed >150 Wear)", fontweight='bold', fontsize=10, color=TEXT_COLOR, pad=20)
    ax_swaps.set_xlim(150, 260)
    ax_swaps.spines['top'].set_visible(False); ax_swaps.spines['right'].set_visible(False)
    ax_swaps.grid(True, linestyle='--', color=GRID_COLOR, axis='x', alpha=0.5)
    ax_swaps.tick_params(colors=TEXT_COLOR)
    
    legend_elements_swaps = [Patch(facecolor=COLOR_DANGER, label='Tool Broke'), Patch(facecolor=COLOR_SAFE, label='Swapped on Time')]
    ax_swaps.legend(handles=legend_elements_swaps, loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=2, 
                    fontsize=8, facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)

    # 5. Premature Breaks Plot
    ax_prem = fig_rep.add_subplot(gs_rep[3, 1])
    ax_prem.set_facecolor(PANEL_COLOR)
    prem_labels = [k for k, v in premature_counts.items() if v > 0]
    prem_vals = [v for v in premature_counts.values() if v > 0]
    
    if len(prem_vals) > 0:
        ax_prem.barh(prem_labels, prem_vals, color=COLOR_WARN, height=0.5)
        ax_prem.set_xticks(range(0, max(prem_vals) + 2))
    else:
        ax_prem.text(0.5, 0.5, "0 Premature Failures Detected", ha='center', va='center', color=COLOR_SAFE, fontweight='bold')
        ax_prem.set_xticks([])
        ax_prem.set_yticks([])
        
    ax_prem.set_title("Premature Breakdowns (<150 Wear)", fontweight='bold', fontsize=10, color=TEXT_COLOR)
    ax_prem.spines['top'].set_visible(False); ax_prem.spines['right'].set_visible(False)
    ax_prem.grid(True, linestyle='--', color=GRID_COLOR, axis='x', alpha=0.5)
    ax_prem.tick_params(colors=TEXT_COLOR)

    # 6. Lifecycle Plot
    ax_wear_plot = fig_rep.add_subplot(gs_rep[0:2, 2])
    ax_wear_plot.set_facecolor(PANEL_COLOR)
    ax_wear_plot.plot(list(x_time), list(y_wear), color=LINE_WEAR, linewidth=2.5)
    ax_wear_plot.axhline(200, color=COLOR_DANGER, linestyle='--', linewidth=1.5, label='Replacement Deadline')
    ax_wear_plot.set_title("Tool Lifecycle & Degradation Trend", fontweight='bold', color=TEXT_COLOR)
    ax_wear_plot.grid(True, linestyle='-', color=GRID_COLOR)
    ax_wear_plot.legend(loc='lower right', facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)
    ax_wear_plot.tick_params(colors=TEXT_COLOR)
    ax_wear_plot.set_ylabel("Wear [min]", color=TEXT_COLOR)
    
    # 7. OSF Map Plot
    ax_osf = fig_rep.add_subplot(gs_rep[2:4, 2])
    ax_osf.set_facecolor(PANEL_COLOR)
    ax_osf.plot(list(y_wear), list(y_torque), '-', color='#a0aec0', alpha=0.5)
    ax_osf.plot([system_state['wear']], [system_state['torque']], 'o', color='#ffffff', markersize=12, label='Current State')
    xc = np.linspace(20, 250, 100)
    ax_osf.plot(xc, 11000/xc, color=COLOR_DANGER, linestyle='-', linewidth=2, label='Overstrain Curve')
    ax_osf.axvline(200, color=COLOR_DANGER, linestyle=':', linewidth=2, label='Max Lifespan (200)') 
    ax_osf.set_xlim(0, 250); ax_osf.set_ylim(10, 80)
    ax_osf.set_title("Current Mechanical Stress Map", fontweight='bold', color=TEXT_COLOR)
    ax_osf.set_xlabel("Tool Wear", color=TEXT_COLOR); ax_osf.set_ylabel("Torque [Nm]", color=TEXT_COLOR)
    ax_osf.grid(True, linestyle='-', color=GRID_COLOR)
    ax_osf.legend(loc='lower left', facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)
    ax_osf.tick_params(colors=TEXT_COLOR)
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plt.tight_layout(rect=[0, 0, 1, 0.93])
    fig_rep.show() 

# ==========================================
# MAIN DASHBOARD UI
# ==========================================
plt.rcParams['axes.facecolor'] = PANEL_COLOR
plt.rcParams['figure.facecolor'] = BG_COLOR
plt.rcParams['axes.edgecolor'] = GRID_COLOR
plt.rcParams['grid.color'] = GRID_COLOR
plt.rcParams['text.color'] = TEXT_COLOR
plt.rcParams['axes.labelcolor'] = TEXT_COLOR
plt.rcParams['xtick.color'] = TEXT_COLOR
plt.rcParams['ytick.color'] = TEXT_COLOR

fig = plt.figure(figsize=(16, 10))
fig.suptitle('SMART FACTORY: Live Predictive Maintenance Dashboard', fontsize=20, fontweight='bold', color='#00d2ff', y=0.96)
fig.text(0.5, 0.02, '[SPACEBAR]: Pause/Resume Data Feed   |   [ENTER]: Generate Executive Report   |   [MOUSE DRAG]: Brush Data on Right Graph', 
         ha='center', color=COLOR_WARN, fontsize=11, fontweight='bold')

# Swap Log Count Text Indicator (Control Bar visual)
text_swap_log = fig.text(0.85, 0.02, 'Report Swap Log: 0/50', color='#00d2ff', fontsize=12, fontweight='bold')

gs = gridspec.GridSpec(2, 2, height_ratios=[2.5, 1], hspace=0.25, wspace=0.15)
ax1 = fig.add_subplot(gs[0, 0])
ax2 = fig.add_subplot(gs[0, 1])
ax3 = fig.add_subplot(gs[1, :])

info_text = """DASHBOARD INFORMATION GUIDE:

1. Tool Wear Trajectory (Top Left):
Tracks physical degradation. Orange cone is a prediction of when the tool will break.
    
2. Live Overstrain Analysis (Top Right) [BRUSHABLE]:
Maps Force vs Age. Click and drag here to Highlight/Link data across graphs.

3. Historical Failures (Bottom):
- TWF: Tool Wear Failure (Snapped from age)
- HDF: Heat Dissipation Failure (Overheated)
- PWF: Power Failure (Power drop/surge)
- OSF: Overstrain Failure (Mechanical limit passed)
- RNF: Random Failure (Sensor ghosting)

(Click '?' again or press Spacebar to resume dashboard)"""

help_box = fig.text(0.5, 0.5, info_text, ha='center', va='center', fontsize=13, color='#ffffff',
                    bbox=dict(facecolor='#1e2b4d', edgecolor=LINE_WEAR, boxstyle='round,pad=1.5', linewidth=2),
                    zorder=100, visible=False)

ax_btn = plt.axes([0.94, 0.92, 0.04, 0.05])
btn_help = Button(ax_btn, '?', color=PANEL_COLOR, hovercolor=GRID_COLOR)
btn_help.label.set_fontsize(18); btn_help.label.set_color(LINE_WEAR); btn_help.label.set_fontweight('bold')

def toggle_help(event):
    global anim_running
    is_visible = help_box.get_visible()
    help_box.set_visible(not is_visible)
    if not is_visible: 
        if anim_running: ani.pause(); anim_running = False
    fig.canvas.draw_idle()
btn_help.on_clicked(toggle_help)

def on_key(event):
    global anim_running
    if event.key == ' ':
        if help_box.get_visible(): help_box.set_visible(False)
        
        # Clear brush highlights when resuming
        highlight_ax1.set_data([], [])
        highlight_ax2.set_data([], [])
        brush.clear()
        
        if anim_running: ani.pause()
        else: ani.resume()
        anim_running = not anim_running
    elif event.key == 'enter':
        if anim_running: ani.pause(); anim_running = False
        generate_printable_report()

fig.canvas.mpl_connect('key_press_event', on_key)

# AX1: Wear Trajectory
ax1.set_title('Tool Wear Trajectory (Confidence Interval Zone)', fontweight='bold', color='white')
ax1.set_ylabel('Tool Wear [min]')
ax1.set_ylim(0, 250); ax1.grid(True, linestyle='--', alpha=0.5)
ax1.axhline(y=200, color=COLOR_DANGER, linestyle='-', linewidth=2, label='Failure Threshold (200)')
pred_zone = Polygon([[0,0], [0,0], [0,0]], color=LINE_PRED, alpha=0.15, label='Uncertainty Zone')
ax1.add_patch(pred_zone)
line_wear, = ax1.plot([], [], color=LINE_WEAR, linewidth=2.5, label='Actual Wear')
line_pred_mean, = ax1.plot([], [], color=LINE_PRED, linestyle='--', linewidth=2, label='Mean Prediction')
text_ttf = ax1.text(0.03, 0.90, 'Initializing...', transform=ax1.transAxes, fontsize=11, color='white', 
                    bbox=dict(facecolor=PANEL_COLOR, alpha=0.9, edgecolor=LINE_PRED, boxstyle='round,pad=0.5'))

# Highlight layers for Brushing
highlight_ax1, = ax1.plot([], [], 'o', color=HIGHLIGHT_COLOR, markersize=6, zorder=10, label='Brushed Data')

handles1, labels1 = ax1.get_legend_handles_labels()
order1_seq = ['Failure Threshold (200)', 'Uncertainty Zone', 'Mean Prediction', 'Actual Wear', 'Brushed Data']
h1 = [handles1[labels1.index(l)] for l in order1_seq if l in labels1]
l1 = [l for l in order1_seq if l in labels1]
ax1.legend(h1, l1, loc='lower right', facecolor=BG_COLOR, edgecolor=GRID_COLOR)

# AX2: Live Overstrain
ax2.set_title('Live Overstrain Analysis (Torque vs Wear)', fontweight='bold', color='white')
ax2.set_xlabel('Tool Wear [min]'); ax2.set_ylabel('Torque [Nm]')
ax2.set_xlim(0, 250); ax2.set_ylim(10, 80); ax2.grid(True, linestyle='--', alpha=0.5)
x_curve = np.linspace(20, 250, 100)
y_danger = 11000 / x_curve
ax2.plot(x_curve, y_danger, color=COLOR_DANGER, linestyle='-', linewidth=1.5, label='Overstrain Curve')
ax2.fill_between(x_curve, y_danger, 80, color=COLOR_DANGER, alpha=0.1)
y_warning = 9000 / x_curve
ax2.plot(x_curve, y_warning, color=COLOR_WARN, linestyle='--', linewidth=1.5, label='Warning Zone')
ax2.fill_between(x_curve, y_warning, y_danger, color=COLOR_WARN, alpha=0.08)
ax2.axvline(200, color=COLOR_DANGER, linestyle=':', linewidth=2, label='Max Lifespan (200)')
ax2.axvspan(200, 250, color=COLOR_DANGER, alpha=0.1)

scatter_history, = ax2.plot([], [], 'o', color='#a0aec0', alpha=0.4, markersize=5, label='Recent Path')
scatter_current, = ax2.plot([], [], 'o', color=LINE_WEAR, markersize=14, markeredgewidth=1.5, label='Current State')
line_osf_pred, = ax2.plot([], [], color='white', linestyle=':', linewidth=2)

# Highlight layers for Brushing
highlight_ax2, = ax2.plot([], [], 'o', color=HIGHLIGHT_COLOR, markersize=6, zorder=10)

text_osf = ax2.text(0.03, 0.90, 'Initializing...', transform=ax2.transAxes, fontsize=11, color='white', 
                    bbox=dict(facecolor=PANEL_COLOR, alpha=0.9, edgecolor='gray', boxstyle='round,pad=0.5'))

handles2, labels2 = ax2.get_legend_handles_labels()
order2_seq = ['Overstrain Curve', 'Max Lifespan (200)', 'Warning Zone', 'Current State', 'Recent Path']
h2 = [handles2[labels2.index(l)] for l in order2_seq if l in labels2]
l2 = [l for l in order2_seq if l in labels2]
ax2.legend(h2, l2, loc='lower left', facecolor=BG_COLOR, edgecolor=GRID_COLOR)

# AX3: Historical System Interruptions
ax3.set_title('Historical System Interruptions', fontweight='bold', color='white')
bars = ax3.bar(['TWF', 'HDF', 'PWF', 'OSF', 'RNF'], [0, 0, 0, 0, 0], color=BAR_COLORS, alpha=0.85)
max_fails = df[['TWF', 'HDF', 'PWF', 'OSF', 'RNF']].sum().max() + 10
ax3.set_ylim(0, max_fails)
ax3.grid(axis='y', linestyle='--', alpha=0.5)
ax3.spines['top'].set_visible(False); ax3.spines['right'].set_visible(False)

# ==========================================
# BRUSHING & LINKING LOGIC
# ==========================================
def on_brush(eclick, erelease):
    global anim_running
    
    if anim_running:
        ani.pause()
        anim_running = False
        
    x1, y1 = eclick.xdata, eclick.ydata
    x2, y2 = erelease.xdata, erelease.ydata
    
    if len(y_wear) == 0: return

    arr_wear = np.array(y_wear)
    arr_torque = np.array(y_torque)
    arr_time = np.array(x_time)
    
    # Check what data falls inside the bounding box on ax2
    mask = (arr_wear >= min(x1, x2)) & (arr_wear <= max(x1, x2)) & \
           (arr_torque >= min(y1, y2)) & (arr_torque <= max(y1, y2))
           
    # Apply to BOTH charts (Linking)
    highlight_ax2.set_data(arr_wear[mask], arr_torque[mask])
    highlight_ax1.set_data(arr_time[mask], arr_wear[mask])
    
    fig.canvas.draw_idle()

# Attach Brush to AX2
brush = RectangleSelector(ax2, on_brush, useblit=True, button=[1], minspanx=5, minspany=5,
                          spancoords='data', interactive=True,
                          props=dict(facecolor=HIGHLIGHT_COLOR, edgecolor='white', alpha=0.2, fill=True))


# ==========================================
# ANIMATION LOOP
# ==========================================
def update(frame):
    idx = frame % len(df)
    row = df.iloc[idx]
    
    current_time, current_wear, current_torque = idx, row['Tool wear [min]'], row['Torque [Nm]']
    current_load = current_wear * current_torque
    
    # SWAP LOGGING LOGIC (Only keeps up to 50 swaps)
    if system_state['step'] > 0 and current_wear < system_state['wear'] - 50:
        prev_row = df.iloc[idx - 1]
        reason = 'Proactive'
        c = COLOR_SAFE
        for f_type in ['TWF', 'HDF', 'PWF', 'OSF', 'RNF']:
            if prev_row[f_type] == 1:
                reason = f_type
                c = COLOR_DANGER
                break
        tool_swaps_log.append({'wear': system_state['wear'], 'reason': reason, 'color': c})
    
    x_time.append(current_time); y_wear.append(current_wear); y_torque.append(current_torque)
    
    system_state['step'] = current_time; system_state['wear'] = current_wear; system_state['torque'] = current_torque; system_state['load'] = current_load
    for col in ['TWF', 'HDF', 'PWF', 'OSF', 'RNF']: system_state['failures'][col] = row[f'cum_{col}']
        
    text_swap_log.set_text(f"Report Swap Log: {len(tool_swaps_log)}/50")
        
    ma_wear_slope = 0
    
    line_wear.set_data(x_time, y_wear)
    ax1.set_xlim(max(0, current_time - WINDOW_SIZE), max(WINDOW_SIZE, current_time + 80))

    if len(y_wear) >= MA_WINDOW and current_wear > 0:
        wear_diffs = np.diff(list(y_wear)[-MA_WINDOW:])
        ma_wear_slope = np.mean(wear_diffs)
        slope_std = np.std(wear_diffs)
        
        if ma_wear_slope > 0.1:
            steps_to_fail = (200 - current_wear) / ma_wear_slope
            line_pred_mean.set_data([current_time, current_time + steps_to_fail], [current_wear, 200])
            
            slope_max, slope_min = ma_wear_slope + slope_std, max(0.05, ma_wear_slope - slope_std) 
            steps_early, steps_late = (200 - current_wear) / slope_max, (200 - current_wear) / slope_min
            pred_zone.set_xy([(current_time, current_wear), (current_time + steps_early, 200), (current_time + steps_late, 200)])
            
            text_ttf.set_text(f"Current Wear: {current_wear} min\nEst. Steps to Maint: {int(steps_to_fail)}")
            text_ttf.get_bbox_patch().set_edgecolor(COLOR_DANGER if steps_to_fail < 40 else COLOR_WARN)
            system_state['twf_mean'], system_state['twf_early'], system_state['twf_late'] = steps_to_fail, steps_early, steps_late
        else:
            line_pred_mean.set_data([], []); pred_zone.set_xy([[0,0], [0,0], [0,0]])
            text_ttf.set_text(f"Current Wear: {current_wear} min\nStatus: Tool Replaced / Optimal")
            text_ttf.get_bbox_patch().set_edgecolor(COLOR_SAFE); system_state['twf_mean'] = -1
    else:
        line_pred_mean.set_data([], []); pred_zone.set_xy([[0,0], [0,0], [0,0]])
        text_ttf.set_text("Calibrating Predictor...")
        text_ttf.get_bbox_patch().set_edgecolor('gray'); system_state['twf_mean'] = -1

    scatter_history.set_data(y_wear, y_torque)
    scatter_current.set_data([current_wear], [current_torque])
    
    if current_load >= 11000 or current_wear >= 200: current_color, status_text = COLOR_DANGER, "CRITICAL LIMIT REACHED"
    elif current_load >= 9000: current_color, status_text = COLOR_WARN, "WARNING: HIGH STRESS"
    else: current_color, status_text = COLOR_SAFE, "NORMAL OPERATIONS"
        
    scatter_current.set_color('#ffffff') 
    system_state['osf_status'] = status_text
    
    est_steps = -1
    if len(y_torque) >= MA_WINDOW and ma_wear_slope > 0.1:
        ma_torque_slope = np.mean(np.diff(list(y_torque)[-MA_WINDOW:]))
        for t in range(1, 1000):
            fw, ft = current_wear + (ma_wear_slope * t), current_torque + (ma_torque_slope * t)
            if fw * ft >= 11000 or fw >= 200:
                est_steps = t; break
        
        if est_steps != -1:
            line_osf_pred.set_data([current_wear, current_wear + (ma_wear_slope * min(20, est_steps))], 
                                   [current_torque, current_torque + (ma_torque_slope * min(20, est_steps))])
            text_osf.set_text(f"Status: {status_text}\nEst. Steps to Overload: {est_steps}")
        else:
            line_osf_pred.set_data([], []); text_osf.set_text(f"Status: {status_text}\nTrajectory: Safe")
    else:
        line_osf_pred.set_data([], []); text_osf.set_text(f"Status: {status_text}\nCalibrating...")
        
    text_osf.get_bbox_patch().set_edgecolor(current_color); system_state['osf_pred'] = est_steps

    for bar, col in zip(bars, ['TWF', 'HDF', 'PWF', 'OSF', 'RNF']): bar.set_height(row[f'cum_{col}'])
    return line_wear, line_pred_mean, pred_zone, text_ttf, scatter_history, scatter_current, line_osf_pred, text_osf

ani = animation.FuncAnimation(fig, update, frames=len(df), interval=UPDATE_INTERVAL_MS, blit=False)

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

plt.show()