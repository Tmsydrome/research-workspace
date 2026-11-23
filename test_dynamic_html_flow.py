"""Dynamic HTML review fixture and service checks, version 1.0.11."""
import json,sys,time
from pathlib import Path
from urllib.request import urlopen
import html_editor
from workspace import VERSION


FIXTURE='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>动态网页批注功能测试</title>
<style>body{margin:0;background:#f3f5f9;color:#1e293b;font:16px Arial,sans-serif}main{max-width:1000px;margin:auto;padding:28px}button{padding:8px 18px;margin-right:8px;border:1px solid #cbd5e1;background:white;border-radius:6px;cursor:pointer}.charts{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}.card{background:white;padding:18px;border-radius:10px}svg,canvas{width:100%;height:180px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border:1px solid #ccd5e2}p{line-height:1.8}</style>
<script src="chart_fixture.js" defer></script></head><body><main>
<h1>动态网页与文字批注</h1><p id="intro">这段说明文字用于测试添加文字批注，图表使用功能测试示例数据。</p>
<p>示例数据仅用于界面功能测试。</p><button id="familyA">家族 A</button><button id="familyB">家族 B</button>
<div class="charts"><section class="card"><h2>SVG 折线图</h2><div id="chart"></div></section><section class="card"><h2>Canvas 图表</h2><canvas id="canvas" width="420" height="180"></canvas></section></div>
<section class="card"><h2>动态表格</h2><div id="table"></div></section><p id="summary">结果说明文字保持独立，可以进行高亮、批注和修订。</p>
</main></body></html>'''
SCRIPT='''let family='A';
function render(){const values=family==='A'?[10,12,11]:[16,14,17];
document.querySelector('#chart').innerHTML='<svg viewBox="0 0 420 180" xmlns="http://www.w3.org/2000/svg"><path d="M20 150 L140 '+(160-values[0]*6)+' L260 '+(160-values[1]*6)+' L400 '+(160-values[2]*6)+'" fill="none" stroke="#2563eb" stroke-width="3"/><text x="20" y="25">家族 '+family+'</text></svg>';
const c=document.querySelector('#canvas'),ctx=c.getContext('2d');ctx.clearRect(0,0,420,180);values.forEach((value,i)=>{ctx.fillStyle='#22a699';ctx.fillRect(35+i*130,170-value*8,70,value*8)});
document.querySelector('#table').innerHTML='<table><tr><th>示例组</th><th>示例值</th></tr>'+values.map((value,i)=>'<tr><td>'+family+(i+1)+'</td><td>'+value+'</td></tr>').join('')+'</table>';document.body.dataset.family=family;}
document.querySelector('#familyA').addEventListener('click',()=>{family='A';render()});document.querySelector('#familyB').addEventListener('click',()=>{family='B';render()});
render();setTimeout(render,150);'''


def main():
    base=Path('qa/dynamic_html').resolve();base.mkdir(parents=True,exist_ok=True)
    source=base/'v1.0.11_dynamic_review_fixture.html';source.write_text(FIXTURE,encoding='utf-8')
    (base/'chart_fixture.js').write_text(SCRIPT,encoding='utf-8')
    exports=base/'exports';exports.mkdir(exist_ok=True)
    html_editor.desktop_directory=lambda:exports
    bridge=html_editor.HtmlEditor()
    try:
        url=bridge.url('dynamic-test',source,base,base/'history')
        with urlopen(url) as response:assert b'workspaceHostConfig' in response.read()
        review=bridge.render_origin+url[len(bridge.origin):].replace('/editor','/review')
        with urlopen(review) as response:assert b'allow-same-origin allow-scripts' in response.read()
        with urlopen(review.replace('/review','/runtime')) as response:
            runtime=response.read().decode('utf-8');assert 'chart_fixture.js' in runtime and '<base ' in runtime
        report={'version':VERSION,'passed':3,'failed':0,'checks':['Archive shell','Script-capable review frame','Runtime HTML and relative resources']}
        Path('dynamic_html_flow_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        info={'url':url,'renderOrigin':bridge.render_origin,'fixture':str(source),'exports':str(exports),'checks':3}
        actual=Path(sys.argv[sys.argv.index('--source')+1]) if '--source' in sys.argv else None
        if actual and actual.is_file():
            actual_dir=base/'actual';actual_dir.mkdir(exist_ok=True)
            copy=actual_dir/actual.name;copy.write_bytes(actual.read_bytes())
            info['actualURL']=bridge.url('actual-page-test',copy,actual_dir,actual_dir/'history')
        print(json.dumps(info),flush=True)
        if '--serve' in sys.argv:
            stop=base/'stop';stop.unlink(missing_ok=True)
            while not stop.exists():time.sleep(.2)
    finally:bridge.close()


if __name__=='__main__':main()
