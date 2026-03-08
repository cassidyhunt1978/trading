"""Web server for UI with Jinja2 templating"""
from flask import Flask, render_template, send_from_directory
import os

app = Flask(__name__, 
            template_folder='templates',
            static_folder='.',
            static_url_path='')

# Configure Jinja2
app.jinja_env.auto_reload = True
app.config['TEMPLATES_AUTO_RELOAD'] = True

CHARTS_REPO = '/opt/charts_repo'

# ── Page routes ──────────────────────────────────────────────────────────────

@app.route('/')
def portfolio():
    return render_template('pages/portfolio.html', active_page='portfolio')

@app.route('/symbols')
def symbols():
    return render_template('pages/symbols.html', active_page='symbols')

@app.route('/strategies')
def strategies():
    return render_template('pages/strategies.html', active_page='strategies')

@app.route('/policies')
def policies():
    return render_template('pages/policies.html', active_page='policies')

@app.route('/system')
def system():
    return render_template('pages/system.html', active_page='system')

@app.route('/reports')
def reports():
    return render_template('pages/reports.html', active_page='reports')

# ── Static assets ────────────────────────────────────────────────────────────

@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory('js', filename)

@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory('css', filename)

@app.route('/chart-terminal/src/<path:filename>')
def serve_chart_src(filename):
    return send_from_directory(os.path.join(CHARTS_REPO, 'src'), filename)

@app.route('/chart-terminal/style.css')
def serve_chart_css():
    return send_from_directory(CHARTS_REPO, 'style.css')

@app.route('/health')
def health():
    return {'status': 'healthy'}

if __name__ == '__main__':
    os.chdir('/opt/trading/ui')
    print('=' * 60)
    print('🚀 Trading UI Server Starting (MODULAR)...')
    print('=' * 60)
    print('📊 Web UI: http://localhost:8010/')
    print('🏥 Health: http://localhost:8010/health')
    print('=' * 60)
    app.run(host='0.0.0.0', port=8010, debug=True, use_reloader=True)
