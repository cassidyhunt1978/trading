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

@app.route('/')
def index():
    """Render main page"""
    return render_template('index.html')

@app.route('/js/<path:filename>')
def serve_js(filename):
    """Serve JavaScript files"""
    return send_from_directory('js', filename)

@app.route('/css/<path:filename>')
def serve_css(filename):
    """Serve CSS files"""
    return send_from_directory('css', filename)

@app.route('/chart-terminal/src/<path:filename>')
def serve_chart_src(filename):
    """Serve charts app ES module source files"""
    return send_from_directory(os.path.join(CHARTS_REPO, 'src'), filename)

@app.route('/chart-terminal/style.css')
def serve_chart_css():
    """Serve charts app stylesheet"""
    return send_from_directory(CHARTS_REPO, 'style.css')

@app.route('/health')
def health():
    """Health check endpoint"""
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
