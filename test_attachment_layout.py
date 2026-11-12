"""Canvas attachment geometry regression, version 1.0.10."""
import json,os,tempfile,tkinter as tk
from pathlib import Path
from app import App
from workspace import VERSION


def main():
    cases=0
    with tempfile.TemporaryDirectory(prefix='research_layout_') as tmp:
        base=Path(tmp);os.environ['RESEARCH_WORKSPACE_CONFIG']=str(base/'config')
        root=tk.Tk();app=App(root);app.open_workspace(str(base/'workspace'))
        try:
            project=app.ws.add_project('排版检查');mindmap=app.ws.add_map(project,'附件排版')
            parent=app.ws.data['mindmaps'][mindmap]['rootNodeId']
            node=app.ws.add_node(parent,'新节点')
            names=['讨论_对话还原与任务分解_简约版.html','很长的文件名称_跨行附件排版验证_'*5+'.mp4','数据.xlsx']
            for name in names:
                source=base/name;source.write_text('layout fixture',encoding='utf-8')
                app.ws.import_attachment(node,source)
            file_node=app.ws.add_node(parent,names[1])
            app.ws.import_attachment(file_node,base/names[1])
            app.load_map(mindmap);app.select_node(node);root.update()
            for zoom in (.25,.5,1,1.5,2):
                app.zoom=zoom;app.render();root.update_idletasks()
                for current in (node,file_node):
                    card=app.boxes[current];rows=[];titles=[]
                    for item in app.canvas.find_withtag(current):
                        if app.canvas.type(item)!='text' or app.canvas.itemcget(item,'anchor')!='w':continue
                        box=app.canvas.bbox(item);tags=app.canvas.gettags(item)
                        assert box[0]>=card[0]-2 and box[1]>=card[1]-2,(zoom,'start',box,card)
                        assert box[2]<=card[2]+2 and box[3]<=card[3]+2,(zoom,'end',box,card)
                        if 'attachment' in tags:
                            hit=app.attachment_hits[(current,tags[-1])]
                            assert box[1]>=hit[1]-2 and box[3]<=hit[3]+2,(zoom,'row',box,hit)
                            rows.append(box)
                        else:titles.append(box)
                    rows.sort(key=lambda box:box[1])
                    for first,second in zip(rows,rows[1:]):assert first[3]<=second[1],(zoom,'overlap')
                    if rows:assert max(b[3] for b in titles)<=rows[0][1],(zoom,'title overlap')
                    cases+=1
            assert len(app.ws.data['nodes'][node]['attachmentIds'])==3
            app.ws.save()
        finally:
            app.ws.close();app.native_drop.close();root.destroy()
    report={'version':VERSION,'passed':cases,'failed':0,'checks':['Long attachment names, multiple rows, file nodes and title separation at five zoom levels']}
    Path('attachment_layout_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
