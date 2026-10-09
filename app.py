"""Research Workspace desktop application, version 1.0.0."""
from __future__ import annotations
import copy
import ctypes
import json
import os
import queue
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
from pathlib import Path
from tkinter import font as tkfont
from themes import THEMES, DEFAULT_STYLE, NODE_PRESETS, configure_style, node_colors
from workspace import (VERSION, Workspace, branch, children, ordered_nodes, node_path,
    project_path, make_outline, restore_backup, clean_name)

class App:
    def __init__(self, root, workspace=None):
        self.root, self.ws, self.map_id, self.focus_node = root, None, None, None
        self.selected, self.boxes, self.visible = set(), {}, []
        self.selection_source="node"
        self.attachment_hits,self.title_y={},{}
        self.loading, self.busy, self.dirty, self.save_job = False, False, False, None
        self.zoom, self.drag, self.anchor = 1.0, None, None
        self.inline_edit,self.html_bridge=None,None
        self.render_job=None
        self.resize_job=None
        self.sidebar_hidden, self.last_width = False, 260
        self.search_job = None
        self.config_path = Path(os.environ.get("RESEARCH_WORKSPACE_CONFIG",os.environ.get("APPDATA",str(Path.home())))) / "ResearchWorkspace" / "settings.json"
        self.config = {}
        try:
            self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            pass
        root.title("Research Workspace v" + VERSION)
        root.geometry("1380x860")
        root.minsize(1020,650)
        self.theme=THEMES.get(self.config.get("theme","ocean"),THEMES["ocean"])
        self.menus=[]
        self.style=ttk.Style(root)
        configure_style(self.style,self.theme)
        self.create_ui()
        self.apply_theme()
        root.protocol("WM_DELETE_WINDOW",self.close)
        root.bind_all("<Control-z>",lambda e:self.shortcut("undo",e))
        root.bind_all("<Control-y>",lambda e:self.shortcut("redo",e))
        root.bind_all("<Control-s>",lambda e:self.save())
        root.bind_all("<Delete>",lambda e:self.shortcut("delete",e))
        root.bind_all("<Return>",lambda e:self.shortcut("sibling",e))
        root.bind_all("<Tab>",lambda e:self.shortcut("child",e))
        root.bind_all("<Control-f>",lambda e:self.search_entry.focus_set())
        self.canvas.bind("<F2>",lambda e:self.edit_title())
        self.outline.bind("<F2>",lambda e:self.edit_title())
        root.bind_all("<Control-Return>",lambda e:self.open_node_details())
        self.install_drop()
        startup=workspace or (self.config.get("workspace") if Path(self.config.get("workspace","__missing__")).exists() else None)
        if startup:root.after(150,lambda:self.open_workspace(startup))
        self.root.after(250,self.poll_tasks)

    def create_ui(self):
        self.create_file_icons()
        self.create_menu_strip()
        bar=ttk.Frame(self.root,padding=(8,5))
        bar.pack(fill="x")
        self.toolbar=bar
        self.view=tk.StringVar(value="map")
        ttk.Button(bar,text="打开项目",command=self.workspace_menu).pack(side="left")
        ttk.Button(bar,text="保存",command=self.save).pack(side="left")
        for text,value in [("思维导图","map"),("大纲","outline")]:
            ttk.Radiobutton(bar,text=text,value=value,variable=self.view,command=self.show_view,
                            style="Segment.TRadiobutton").pack(side="left")
        for text,cmd in [("新建节点",lambda:self.add_node(False)),("同级",lambda:self.add_node(True)),
                         ("删除",self.delete_selection),("撤销",self.undo),("重做",lambda:self.undo(True))]:
            ttk.Button(bar,text=text,command=cmd).pack(side="left")
        self.toolbar_spacer=ttk.Frame(bar,width=1)
        self.toolbar_spacer.pack(side="left",fill="x",expand=True)
        self.search_group=ttk.Frame(bar)
        self.search_group.pack(side="left")
        profile=json.loads((Path(__file__).parent/"resources/github_profile.json").read_text(encoding="utf-8"))
        self.github_url=profile["url"]
        self.github_avatar=tk.PhotoImage(file=str(Path(__file__).parent/"resources/github_avatar.png"))
        self.github_button=ttk.Button(self.search_group,text=profile["displayName"],image=self.github_avatar,
                                      compound="left",cursor="hand2",command=self.open_github_profile)
        self.github_button.pack(side="left",padx=(0,6))
        self.search_var=tk.StringVar()
        self.search_entry=ttk.Entry(self.search_group,textvariable=self.search_var,width=16)
        self.search_entry.pack(side="left",padx=8)
        self.search_entry.bind("<Return>",lambda e:self.search_dialog())
        ttk.Button(self.search_group,text="搜索",command=self.search_dialog).pack(side="left")
        self.count_var=tk.StringVar(value="已选 0 节点")
        self.main = tk.PanedWindow(self.root,orient="horizontal",sashwidth=7,bg="#dbe2ec",bd=0,opaqueresize=False,proxyrelief="flat",proxyborderwidth=0)
        self.main.pack(fill="both",expand=True)
        self.sidebar = ttk.Frame(self.main,padding=(9,10))
        row = ttk.Frame(self.sidebar)
        row.pack(fill="x")
        ttk.Label(row,text="当前项目",font=("Microsoft YaHei UI",11,"bold")).pack(side="left")
        ttk.Button(row,text="＋项目",command=self.add_project).pack(side="right")
        self.project_tree = ttk.Treeview(self.sidebar,show="tree",selectmode="extended",style="Project.Treeview")
        self.project_tree.pack(fill="both",expand=True,pady=12)
        self.project_tree.bind("<<TreeviewSelect>>",self.select_project)
        self.project_tree.bind("<Button-3>",self.project_context)
        self.project_tree.bind("<ButtonPress-1>",self.project_press,add="+")
        self.project_tree.bind("<ButtonRelease-1>",self.project_release,add="+")
        ttk.Button(self.sidebar,text="＋新建导图",command=self.add_map).pack(fill="x",pady=4)
        self.main.add(self.sidebar,minsize=180,width=260)
        self.right = ttk.Frame(self.main)
        self.main.add(self.right,minsize=700)
        self.main.bind("<ButtonRelease-1>",self.pane_released,add="+")
        self.main.bind("<Double-Button-1>",self.reset_sidebar,add="+")
        self.zoom_var=tk.StringVar(value="100%")
        self.content = tk.PanedWindow(self.right,orient="horizontal",sashwidth=5,bg="#dbe2ec",bd=0,opaqueresize=False,proxyrelief="flat",proxyborderwidth=0)
        self.content.pack(fill="both",expand=True)
        self.content.bind("<ButtonRelease-1>",self.pane_released,add="+")
        self.view_frame = ttk.Frame(self.content)
        self.content.add(self.view_frame,minsize=330,width=850,stretch="always")
        self.canvas_frame = ttk.Frame(self.view_frame)
        self.canvas_frame.pack(fill="both",expand=True)
        self.canvas = tk.Canvas(self.canvas_frame,bg="#f5f7fb",highlightthickness=0,confine=False)
        sx,sy = ttk.Scrollbar(self.canvas_frame,orient="horizontal",command=self.canvas.xview),ttk.Scrollbar(self.canvas_frame,command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=lambda *a:self.canvas_scrolled(sx,"x",a),
                              yscrollcommand=lambda *a:self.canvas_scrolled(sy,"y",a))
        self.canvas.grid(row=0,column=0,sticky="nsew")
        self.empty_start=ttk.Button(self.canvas,text="＋ 新建项目",command=self.begin_project)
        sy.grid(row=0,column=1,sticky="ns")
        sx.grid(row=1,column=0,sticky="ew")
        self.overview=ttk.Frame(self.canvas,style="Card.TFrame",padding=7)
        self.overview.place(relx=1,rely=1,anchor="se",x=-18,y=-18)
        self.minimap=tk.Canvas(self.overview,width=185,height=112,highlightthickness=1,cursor="hand2")
        self.minimap.pack(fill="x")
        self.minimap.bind("<Button-1>",self.minimap_click)
        self.minimap.bind("<B1-Motion>",self.minimap_click)
        self.zoom_controls=ttk.Frame(self.overview,style="Card.TFrame")
        self.zoom_controls.pack(fill="x",pady=(6,0))
        for text,cmd in [("−",lambda:self.change_zoom(.8)),("适应画布",self.fit_view),
                         ("＋",lambda:self.change_zoom(1.25))]:
            ttk.Button(self.zoom_controls,text=text,command=cmd).pack(side="left",padx=2)
        self.canvas.bind("<Configure>",self.canvas_resized,add="+")
        self.canvas_frame.rowconfigure(0,weight=1)
        self.canvas_frame.columnconfigure(0,weight=1)
        self.outline_page=ttk.Frame(self.view_frame,style="Outline.TFrame")
        self.outline_title=tk.StringVar(value="科研资料")
        self.outline_meta=tk.StringVar(value="")
        ttk.Label(self.outline_page,textvariable=self.outline_title,style="OutlineTitle.TLabel").pack(anchor="w",padx=38,pady=(30,4))
        ttk.Label(self.outline_page,textvariable=self.outline_meta,style="OutlineMeta.TLabel").pack(anchor="w",padx=40,pady=(0,20))
        self.outline_sheet=ttk.Frame(self.outline_page,style="Outline.TFrame")
        self.outline_sheet.pack(fill="both",expand=True,padx=24,pady=(0,20))
        self.outline = ttk.Treeview(self.outline_sheet,columns=("files",),show="tree headings",selectmode="extended",style="Outline.Treeview")
        self.outline.column("#0",width=390,stretch=True)
        self.outline.heading("#0",text="内容 · 双击编辑")
        self.outline.heading("files",text="附件")
        self.outline.column("files",width=220,stretch=False)
        self.outline.pack(side="left",fill="both",expand=True)
        self.outline_scroll=ttk.Scrollbar(self.outline_sheet,command=self.outline.yview)
        self.outline_scroll.pack(side="right",fill="y")
        self.outline.configure(yscrollcommand=self.outline_scrolled)
        self.outline.bind("<<TreeviewSelect>>",self.outline_select)
        self.outline.bind("<ButtonPress-1>",self.outline_toggle)
        self.outline.bind("<Button-3>",self.node_context)
        self.outline.bind("<<TreeviewOpen>>",lambda e:self.outline_collapse(False))
        self.outline.bind("<<TreeviewClose>>",lambda e:self.outline_collapse(True))
        self.outline.bind("<Double-Button-1>",self.outline_double_click)
        self.canvas.bind("<Tab>",self.tab_child)
        self.outline.bind("<Tab>",self.tab_child)
        self.canvas.bind("<Return>",lambda e:self.shortcut("sibling",e))
        self.outline.bind("<Return>",lambda e:self.shortcut("sibling",e))
        self.canvas.bind("<ButtonPress-1>",self.canvas_press)
        self.canvas.bind("<B1-Motion>",self.canvas_motion)
        self.canvas.bind("<ButtonRelease-1>",self.canvas_release)
        self.canvas.bind("<Double-Button-1>",self.canvas_double_click)
        self.canvas.bind("<Motion>",self.canvas_hover)
        self.canvas.bind("<Button-3>",self.node_context)
        self.canvas.bind("<ButtonPress-2>",lambda e:self.canvas.scan_mark(e.x,e.y))
        self.canvas.bind("<B2-Motion>",lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1))
        self.canvas.bind("<Control-MouseWheel>",lambda e:self.change_zoom(1.15 if e.delta>0 else 1/1.15))
        self.canvas.bind("<MouseWheel>",lambda e:self.canvas.yview_scroll(-int(e.delta/120),"units"))
        self.canvas.bind("<Shift-MouseWheel>",lambda e:self.canvas.xview_scroll(-int(e.delta/120),"units"))
        self.inspector=ttk.Frame(self.content,padding=(8,10))
        self.content.add(self.inspector,minsize=285,width=315,stretch="never")
        self.inspector_tabs=ttk.Notebook(self.inspector)
        self.inspector_tabs.pack(fill="both",expand=True)
        self.editor_win=tk.Toplevel(self.root)
        self.editor_win.withdraw()
        self.editor_win.transient(self.root)
        self.editor_win.geometry("700x620")
        self.editor_win.protocol("WM_DELETE_WINDOW",self.finish_details)
        self.editor=ttk.Frame(self.editor_win,padding=20)
        self.editor.pack(fill="both",expand=True)
        self.attachment_panel=ttk.Frame(self.inspector_tabs,padding=12)
        self.canvas_settings=ttk.Frame(self.inspector_tabs,padding=12)
        self.inspector_tabs.add(self.attachment_panel,text="附件")
        self.inspector_tabs.add(self.canvas_settings,text="画布")
        self.create_canvas_settings()

        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(self.editor,textvariable=self.title_var)
        ttk.Label(self.editor,textvariable=self.title_var,style="Heading.TLabel").pack(anchor="w",pady=(0,12))
        self.title_entry.bind("<Tab>",self.tab_child)
        self.title_var.trace_add("write",lambda *_:self.editor_changed())
        colors = ttk.Frame(self.editor)
        colors.pack(fill="x")
        for index,(text,cmd) in enumerate([("高亮片段",self.highlight),("清除高亮",self.clear_highlight)]):
            ttk.Button(colors,text=text,command=cmd).grid(row=index//2,column=index%2,sticky="ew",padx=2,pady=2)
        colors.columnconfigure(0,weight=1)
        colors.columnconfigure(1,weight=1)
        ttk.Label(self.editor,text="正文（支持多行与片段高亮）").pack(anchor="w",pady=(9,2))
        self.body = tk.Text(self.editor,height=8,width=24,wrap="word",undo=True,font=("Microsoft YaHei UI",10))
        self.body.pack(fill="both",expand=True)
        self.body.bind("<<Modified>>",self.editor_changed)
        ttk.Label(self.editor,text="备注").pack(anchor="w",pady=(8,2))
        self.notes = tk.Text(self.editor,height=4,width=24,wrap="word",undo=True,font=("Microsoft YaHei UI",10))
        self.notes.pack(fill="x")
        self.notes.bind("<<Modified>>",self.editor_changed)
        ttk.Button(self.editor,text="完成",command=self.finish_details,style="Accent.TButton").pack(anchor="e",pady=(14,0))
        row = ttk.Frame(self.attachment_panel)
        row.pack(fill="x",pady=6)
        self.attachment_summary=tk.StringVar(value="所选节点的附件")
        ttk.Label(row,textvariable=self.attachment_summary).pack(side="left")
        ttk.Button(row,text="文件",command=lambda:self.import_files(False)).pack(side="right")
        ttk.Button(row,text="文件夹",command=lambda:self.import_files(True)).pack(side="right")
        attachment_list=ttk.Frame(self.attachment_panel)
        attachment_list.pack(fill="both",expand=True)
        self.attach_tree = ttk.Treeview(attachment_list,columns=("size",),show="tree headings",height=5,selectmode="extended")
        self.attach_tree.heading("#0",text="名称 / 类型")
        self.attach_tree.heading("size",text="大小")
        self.attach_tree.column("#0",width=205)
        self.attach_tree.column("size",width=70)
        attach_scroll=ttk.Scrollbar(attachment_list,orient="vertical",command=self.attach_tree.yview)
        attach_scroll.pack(side="right",fill="y")
        self.attach_tree.configure(yscrollcommand=attach_scroll.set)
        self.attach_tree.pack(fill="both",expand=True)
        self.attach_tree.bind("<Double-Button-1>",lambda e:self.open_attachment())
        self.attach_tree.bind("<Button-3>",self.attachment_context)
        self.attach_tree.bind("<<TreeviewSelect>>",self.attachment_details)
        self.export_button=ttk.Button(self.attachment_panel,text="导出附件…",
                                     command=self.export_selected_attachments,style="Accent.TButton")
        self.export_button.pack(fill="x",pady=(10,6))
        self.export_button.state(["disabled"])
        self.attachment_info = tk.StringVar(value="HTML 使用内置修订工具；其他附件使用系统默认应用")
        ttk.Label(self.attachment_panel,textvariable=self.attachment_info,wraplength=290).pack(anchor="w",pady=3)
        self.status = tk.StringVar(value="新建项目并选择保存文件夹，或打开已有项目")
        status_bar=ttk.Frame(self.root,padding=(12,5))
        status_bar.pack(fill="x")
        ttk.Label(status_bar,textvariable=self.status,anchor="w").pack(side="left")
        ttk.Label(status_bar,textvariable=self.count_var,style="Muted.TLabel").pack(side="right")
        ttk.Label(status_bar,textvariable=self.zoom_var,style="Muted.TLabel").pack(side="right",padx=20)

        self.wrap_toolbar(bar)
        self.task_queue = queue.Queue()
        self.inspector_tabs.select(self.attachment_panel)
        self.enable_editor(False)


    def open_github_profile(self):
        webbrowser.open_new_tab(self.github_url)

    def wrap_toolbar(self,frame):
        widgets=frame.winfo_children()
        rows=[]
        previous=None
        def arrange(event=None):
            nonlocal previous
            sizes=tuple(w.winfo_reqwidth()+4 for w in widgets)
            width=max(200,frame.winfo_width()-12)
            key=(width,sizes)
            if key==previous:
                return
            previous=key
            for w in widgets:
                w.pack_forget()
            for row in rows:
                row.pack_forget()
            line,used=0,0
            for w,size in zip(widgets,sizes):
                if used and used+size>width:
                    line+=1
                    used=0
                while len(rows)<=line:
                    rows.append(ttk.Frame(frame))
                rows[line].pack(fill="x",pady=1)
                stretch=w==getattr(self,"toolbar_spacer",None)
                w.pack(in_=rows[line],side="left",padx=2,fill="x" if stretch else "none",expand=stretch)
                w.lift()
                used+=size
        frame.bind("<Configure>",arrange)
        self.root.after_idle(arrange)

    def menu(self):
        p=self.theme
        m=tk.Menu(self.root,tearoff=False,bg=p["panel"],fg=p["text"],
                  activebackground=p["selection"],activeforeground=p["text"],bd=0)
        self.menus.append(m)
        return m

    def create_menu_strip(self):
        strip=ttk.Frame(self.root,padding=(8,2))
        strip.pack(fill="x")
        items=[
            ("文件",[("打开项目文件夹",lambda:self.open_workspace()),("打开项目包…",self.open_project_package),
                     ("导出所选项目包…",self.export_project_package),("保存 · Ctrl+S",self.save),
                     ("导出大纲",self.export_outline),("备份工作区",self.backup_dialog),
                     ("从备份恢复",self.restore_dialog)]),
            ("编辑",[("撤销",lambda:self.undo()),("重做",lambda:self.undo(True)),
                     ("选择整个分支",self.select_branch),("缩进",self.indent),("提升",self.outdent),
                     ("上移",lambda:self.sort_node(-1)),("下移",lambda:self.sort_node(1)),
                     ("全局搜索",self.search_dialog)]),
            ("插入",[("项目",self.add_project),("子文件夹",self.add_folder),("导图",self.add_map),
                     ("子主题",lambda:self.add_node(False)),("同级主题",lambda:self.add_node(True)),
                     ("归档文件",lambda:self.import_files(False)),("资源文件夹",lambda:self.import_files(True))]),
            ("查看",[("思维导图",lambda:self.switch_view("map")),("大纲",lambda:self.switch_view("outline")),
                     ("画布配色",lambda:self.inspector_tabs.select(self.canvas_settings)),
                     ("适应视图",self.fit_view),("项目侧栏",self.toggle_sidebar)]),
            ("帮助",[("快捷键与使用说明",self.help_dialog),("归档附件管理",self.archive_manager)])]
        for title,entries in items:
            button=ttk.Menubutton(strip,text=title)
            m=self.menu()
            for label,cmd in entries:
                m.add_command(label=label,command=cmd)
            button.configure(menu=m)
            button.pack(side="left")
        self.location_var=tk.StringVar(value="Research Workspace")
        ttk.Label(strip,textvariable=self.location_var,style="Muted.TLabel").pack(side="right",padx=10)

    def switch_view(self,value):
        self.view.set(value)
        self.show_view()

    def create_canvas_settings(self):
        outer=self.canvas_settings
        self.settings_canvas=tk.Canvas(outer,highlightthickness=0,bg=self.theme["ui"])
        bar=ttk.Scrollbar(outer,orient="vertical",command=self.settings_canvas.yview)
        bar.pack(side="right",fill="y")
        self.settings_canvas.pack(side="left",fill="both",expand=True)
        self.settings_canvas.configure(yscrollcommand=bar.set)
        frame=ttk.Frame(self.settings_canvas)
        window=self.settings_canvas.create_window(0,0,anchor="nw",window=frame)
        frame.bind("<Configure>",lambda e:self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>",lambda e:self.settings_canvas.itemconfigure(window,width=e.width))
        def wheel(event):
            widget=event.widget
            while widget:
                if widget==outer:
                    self.settings_canvas.yview_scroll(-int(event.delta/120),"units")
                    return "break"
                widget=getattr(widget,"master",None)
        self.root.bind("<MouseWheel>",wheel,add="+")
        def card(title):
            panel=ttk.Frame(frame,style="Panel.TFrame",padding=13)
            panel.pack(fill="x",pady=(0,12))
            ttk.Label(panel,text=title,style="CardHeading.TLabel").pack(anchor="w",pady=(0,12))
            return panel
        palette=card("画布主题")
        self.theme_name=tk.StringVar(value=self.theme["name"])
        combo=ttk.Combobox(palette,textvariable=self.theme_name,state="readonly",
                           values=[p["name"] for p in THEMES.values()],width=19)
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>",lambda e:self.set_theme(next(k for k,v in THEMES.items() if v["name"]==self.theme_name.get())))
        self.palette_previews=[]
        grid=ttk.Frame(palette,style="Card.TFrame")
        grid.pack(fill="x",pady=(9,0))
        for index,(key,p) in enumerate((k,p) for k,p in THEMES.items() if k!="plum"):
            tile=tk.Canvas(grid,width=100,height=76,highlightthickness=1,
                           highlightbackground=p["branch"],background=p["canvas"],cursor="hand2")
            tile.grid(row=index//2,column=index%2,padx=3,pady=4,sticky="ew")
            tile.create_rectangle(10,24,35,40,outline=p["text"],width=1)
            tile.create_line(35,32,52,32,52,16,71,16,fill=p["branch"],width=2,smooth=True)
            tile.create_line(35,32,52,32,52,48,87,48,fill=p["branch"],width=2,smooth=True)
            tile.create_rectangle(71,8,92,24,outline=p["branch"])
            tile.create_text(51,64,text=p["name"],fill=p["text"],font=("Microsoft YaHei UI",9))
            tile.bind("<Button-1>",lambda e,k=key:self.set_theme(k))
            self.palette_previews.append((key,tile))
        grid.columnconfigure(0,weight=1);grid.columnconfigure(1,weight=1)
        options=card("分支设置")
        self.rainbow_var=tk.BooleanVar(value=True)
        self.taper_var=tk.BooleanVar(value=True)
        self.grid_var=tk.BooleanVar(value=True)
        ttk.Checkbutton(options,text="彩色分支",variable=self.rainbow_var,command=self.change_branch_style,
                        style="Card.TCheckbutton").pack(anchor="w",pady=4)
        ttk.Checkbutton(options,text="线条逐级变细",variable=self.taper_var,command=self.change_branch_style,
                        style="Card.TCheckbutton").pack(anchor="w",pady=4)
        ttk.Checkbutton(options,text="显示画布网格",variable=self.grid_var,command=self.change_branch_style,
                        style="Card.TCheckbutton").pack(anchor="w",pady=4)
        ttk.Label(options,text="左 → 右",style="CardMuted.TLabel").pack(anchor="w",pady=(10,0))
        presets_card=card("节点调色")
        presets=ttk.Frame(presets_card,style="Card.TFrame")
        presets.pack(fill="x")
        for index,(label,(bg,fg)) in enumerate(NODE_PRESETS.items()):
            ttk.Button(presets,text=label,style=label+".TButton",
                      command=lambda x=label:self.set_node_preset(x)).grid(row=index//2,column=index%2,sticky="ew",padx=3,pady=3)
        presets.columnconfigure(0,weight=1);presets.columnconfigure(1,weight=1)
        ttk.Button(presets_card,text="自定义背景色",command=lambda:self.color_node("background")).pack(fill="x",pady=(9,3))
        ttk.Button(presets_card,text="自定义文字色",command=lambda:self.color_node("foreground")).pack(fill="x",pady=3)
        ttk.Button(presets_card,text="恢复节点主题色",command=lambda:self.set_node_preset(None),style="Accent.TButton").pack(fill="x",pady=(8,0))
        ttk.Label(frame,text="双击内容编辑 · Tab 添加子节点\n文件拖入节点即可归档",style="Muted.TLabel",wraplength=250).pack(anchor="w",padx=4,pady=6)

    def apply_theme(self):
        configure_style(self.style,self.theme)
        p=self.theme
        self.root.configure(background=p["ui"])
        self.root.option_add("*TCombobox*Listbox.background",p["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground",p["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground",p["selection"])
        self.main.configure(bg=p["border"],proxybackground=p["accent"])
        self.content.configure(bg=p["border"],proxybackground=p["accent"])
        self.canvas.configure(bg=p["canvas"])
        self.minimap.configure(bg=p["canvas"],highlightbackground=p["border"])
        self.settings_canvas.configure(bg=p["ui"])
        for text in (self.body,self.notes):
            text.configure(bg=p["panel"],fg=p["text"],insertbackground=p["text"],
                           selectbackground=p["selection"],selectforeground=p["text"],
                           highlightbackground=p["border"],highlightcolor=p["accent"],
                           highlightthickness=1,bd=0,padx=9,pady=7)
        for m in self.menus:
            try:
                m.configure(bg=p["panel"],fg=p["text"],activebackground=p["selection"],activeforeground=p["text"])
            except tk.TclError:
                pass
        self.outline.tag_configure("branch",font=("Microsoft YaHei UI",11,"bold"))
        self.outline.tag_configure("leaf",foreground=p["text"])
        self.theme_name.set(p["name"])
        for key,tile in self.palette_previews:
            tile.configure(highlightthickness=2 if THEMES[key] is self.theme else 1)
        if os.name=="nt":
            try:
                hwnd=ctypes.windll.user32.GetAncestor(self.root.winfo_id(),2)
                dark=ctypes.c_int(0 if p is THEMES["paper"] else 1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),20,ctypes.byref(dark),4)
            except OSError:
                pass
        self.render()

    def apply_workspace_theme(self):
        prefs=self.ws.data["preferences"] if self.ws else {}
        key=prefs.get("theme",self.config.get("theme","ocean"))
        self.theme=THEMES.get(key,THEMES["ocean"])
        self.rainbow_var.set(bool(prefs.get("colorfulBranches",True)))
        self.taper_var.set(bool(prefs.get("taperLines",True)))
        self.grid_var.set(bool(prefs.get("showGrid",True)))
        self.apply_theme()

    def set_theme(self,key):
        if key not in THEMES or not self.guard():
            return
        self.checkpoint()
        self.ws.data["preferences"]["theme"]=key
        self.theme=THEMES[key]
        self.config["theme"]=key
        self.write_config()
        self.apply_theme()
        self.changed()

    def change_branch_style(self):
        if not self.guard():
            return
        self.checkpoint()
        self.ws.data["preferences"]["colorfulBranches"]=self.rainbow_var.get()
        self.ws.data["preferences"]["taperLines"]=self.taper_var.get()
        self.ws.data["preferences"]["showGrid"]=self.grid_var.get()
        self.render()
        self.changed()

    def set_node_preset(self,label):
        if not self.guard() or not self.focus_node:
            return
        self.checkpoint()
        targets=self.selected or {self.focus_node}
        for i in targets:
            n=self.ws.data["nodes"][i]
            if label:
                bg,fg=NODE_PRESETS[label]
                n["style"].update(background=bg,foreground=fg,custom=True)
            else:
                n["style"].update(DEFAULT_STYLE,custom=False)
        self.render()
        self.changed()

    def rounded_box(self,box,fill,outline,width=2,tags=()):
        x1,y1,x2,y2=box
        r=min(15*self.zoom,(y2-y1)/4)
        points=[x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,
                x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1]
        return self.canvas.create_polygon(points,smooth=True,splinesteps=20,fill=fill,
                                          outline=outline,width=width,tags=tags)

    FILE_TYPES = {
        "word": ("W", "#5799f7", {".doc", ".docx"}),
        "excel": ("X", "#48c58d", {".xls", ".xlsx", ".xlsm", ".csv"}),
        "ppt": ("P", "#f49a63", {".ppt", ".pptx", ".pptm"}),
        "html": ("H", "#f2bd63", {".html", ".htm"}),
        "markdown": ("M", "#b79afb", {".md", ".markdown"}),
        "image": ("", "#f18bbe", {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff", ".ico"}),
        "pdf": ("F", "#f57c84", {".pdf"}),
        "folder": ("D", "#e7bc69", {"folder"}),
        "file": ("·", "#94b5ce", set())}

    def attachment_kind(self,record):
        extension=Path(record["originalName"]).suffix.lower()
        if record.get("type")=="folder":return "folder"
        return next((kind for kind,(_,_,extensions) in self.FILE_TYPES.items()
                     if extension in extensions),"file")

    def create_file_icons(self):
        glyphs={"W":["101","101","101","111","101"],
                "X":["101","101","010","101","101"],
                "P":["110","101","110","100","100"],
                "H":["101","101","111","101","101"],
                "M":["101","111","111","101","101"],
                "F":["111","100","110","100","100"],
                "D":["110","101","101","101","110"],
                "·":["000","000","010","000","000"]}
        self.file_icons={}
        for kind,(letter,color,_) in self.FILE_TYPES.items():
            icon=tk.PhotoImage(width=20,height=22)
            # Pixel shapes stay sharp at the native list size and use Tk only.
            for y in range(2,20):
                right=15 if y>=6 else 11+(y-2)
                icon.put(color,to=(3,y,right+1,y+1))
            if kind=="image":
                for x,y in [(7,7),(6,12),(7,11),(8,10),(9,11),(10,12),(11,13),(12,12),(13,11)]:
                    icon.put("#ffffff",to=(x,y,x+2,y+2))
            else:
                for y,row in enumerate(glyphs[letter]):
                    for x,pixel in enumerate(row):
                        if pixel=="1":icon.put("#ffffff",to=(6+x*2,7+y*2,8+x*2,9+y*2))
            self.file_icons[kind]=icon

    def draw_attachment_icon(self,x,y,z,tags,record,badge=False):
        kind=self.attachment_kind(record)
        letter,ink,_=self.FILE_TYPES[kind]
        if badge:
            self.rounded_box((x-12*z,y-14*z,x+24*z,y+14*z),self.theme["panel"],
                             self.theme["accent"],z,tags)
        if kind=="image":
            self.canvas.create_rectangle(x-6*z,y-9*z,x+17*z,y+9*z,
                                         outline=ink,width=max(1,2*z),tags=tags)
            self.canvas.create_oval(x-2*z,y-6*z,x+3*z,y-z,fill=ink,outline=ink,tags=tags)
            self.canvas.create_line(x-4*z,y+6*z,x+3*z,y,x+8*z,y+5*z,x+12*z,y+z,x+15*z,y+6*z,
                                    fill=ink,width=max(1,2*z),tags=tags)
        else:
            self.canvas.create_polygon(x-6*z,y-11*z,x+10*z,y-11*z,x+17*z,y-4*z,
                x+17*z,y+11*z,x-6*z,y+11*z,fill=ink,outline=ink,tags=tags)
            self.canvas.create_line(x+10*z,y-11*z,x+10*z,y-4*z,x+17*z,y-4*z,
                                    fill=self.theme["panel"],width=max(1,z),tags=tags)
            self.canvas.create_text(x+5*z,y+2*z,text="</>" if kind=="html" else letter,
                fill="#ffffff",font=("Segoe UI",max(5,int((9 if kind=="html" else 12)*z)),"bold"),tags=tags)

    def node_content(self,i):
        n=self.ws.data["nodes"][i]
        return "\n".join(x for x in (n["title"],n["bodyRichText"]["text"],n["notes"]) if x)

    def canvas_double_click(self,e):
        if self.attachment_at(e.x,e.y):
            return "break"
        i=self.node_at(e.x,e.y)
        if i:
            self.select_node(i)
            self.edit_title(i)
        return "break"

    def attachment_at(self,x,y):
        x,y=self.canvas.canvasx(x),self.canvas.canvasy(y)
        for (_,attachment),box in self.attachment_hits.items():
            if box[0]<=x<=box[2] and box[1]<=y<=box[3]:
                return attachment
        return None

    def outline_double_click(self,e):
        i=self.outline.identify_row(e.y)
        if not i:return "break"
        self.select_node(i)
        if self.outline.identify_column(e.x)=="#1":
            files=self.ws.data["nodes"][i]["attachmentIds"]
            if files:self.open_attachment(files[0])
        else:self.edit_title(i)
        return "break"

    def edit_title(self,i=None):
        if not self.guard():return
        i=i or self.focus_node
        if i not in self.ws.data["nodes"]:return
        self.finish_inline()
        if self.view.get()=="map":
            box=self.boxes.get(i)
            if not box:return
            x=box[0]-self.canvas.canvasx(0)+4
            y=box[1]-self.canvas.canvasy(0)+4
            width=max(160,box[2]-box[0]-8)
            height=max(52,min(240,box[3]-box[1]-8))
            parent=self.canvas
        else:
            self.outline.see(i);self.root.update_idletasks()
            box=self.outline.bbox(i,"#0")
            if not box:return
            depth=len(node_path(self.ws.data,i))-1
            inset=34+depth*20
            x,y,width,height=box
            x+=inset;width=max(160,width-inset-8)
            height=max(68,min(240,28*(self.node_content(i).count("\n")+1)))
            parent=self.outline
        entry=tk.Text(parent,wrap="word",undo=True,font=("Microsoft YaHei UI",11),
                      bg=self.theme["panel"],fg=self.theme["text"],insertbackground=self.theme["text"],
                      selectbackground=self.theme["selection"],bd=0,highlightthickness=3,
                      highlightbackground="#ffd84d",highlightcolor="#ffd84d",padx=8,pady=6)
        entry.insert("1.0",self.node_content(i))
        entry.place(x=x,y=y,width=width,height=height)
        self.inline_edit={"node":i,"entry":entry}
        entry.bind("<Return>",lambda e:self.finish_inline())
        entry.bind("<Shift-Return>",lambda e:None)
        entry.bind("<Control-Return>",lambda e:self.finish_inline())
        entry.bind("<Escape>",lambda e:self.finish_inline(False))
        entry.bind("<Tab>",self.inline_tab)
        def save_content(event):
            self.finish_inline();self.save()
            return "break"
        entry.bind("<Control-s>",save_content)
        entry.bind("<FocusOut>",lambda e:self.finish_inline())
        entry.focus_set();entry.tag_add("sel","1.0","end-1c")

    def finish_inline(self,commit=True):
        editing=self.inline_edit
        if not editing:return "break"
        self.inline_edit=None
        i=editing["node"]
        value=editing["entry"].get("1.0","end-1c").strip() or "新节点"
        editing["entry"].destroy()
        if commit and self.ws and i in self.ws.data["nodes"] and self.node_content(i)!=value:
            self.checkpoint()
            n=self.ws.data["nodes"][i]
            n["title"]=value
            n["bodyRichText"]={"text":"","highlights":[]}
            n["notes"]=""
            self.changed();self.render();self.load_editor(i)
        (self.canvas if self.view.get()=="map" else self.outline).focus_set()
        return "break"

    def inline_tab(self,e):
        self.finish_inline()
        self.tab_child()
        return "break"

    def open_node_details(self,field=None):
        self.edit_title()

    def finish_details(self):
        self.editor_changed()
        self.editor_win.withdraw()
        self.save()
        (self.canvas if self.view.get()=="map" else self.outline).focus_set()

    def enable_editor(self, enabled):
        state = "normal" if enabled else "disabled"
        self.title_entry.configure(state=state)
        self.body.configure(state=state)
        self.notes.configure(state=state)

    def guard(self):
        if self.busy:
            self.status.set("正在处理文件，请等待完成")
            return False
        if not self.ws:
            self.status.set("请先新建或打开项目")
            return False
        return True

    def error(self, e):
        self.status.set("操作失败：" + str(e))
        messagebox.showerror("Research Workspace",str(e),parent=self.root)

    def workspace_menu(self):
        menu = self.menu()
        menu.add_command(label="打开项目文件夹",command=lambda:self.open_workspace())
        menu.add_command(label="新建项目…",command=self.add_project)
        menu.add_command(label="打开项目包…",command=self.open_project_package)
        menu.add_command(label="导出所选项目包…",command=self.export_project_package)
        menu.add_command(label="保存 · Ctrl+S",command=self.save)
        menu.add_command(label="备份整个工作区为 ZIP",command=self.backup_dialog)
        menu.add_command(label="从 ZIP 恢复到新目录",command=self.restore_dialog)
        menu.add_command(label="归档附件管理",command=self.archive_manager)
        menu.add_command(label="使用说明与快捷键",command=self.help_dialog)
        menu.tk_popup(self.root.winfo_rootx()+10,self.root.winfo_rooty()+65)

    def open_workspace(self,path=None):
        if self.busy:
            return
        if not path:
            path = filedialog.askdirectory(title="打开项目文件夹",parent=self.root)
        if not path:
            self.status.set("点击“＋项目”新建，或“打开项目”选择已有项目目录")
            return
        try:
            if self.ws and Path(path).resolve()==self.ws.root:
                return True
            if not self.prepare_to_leave("切换项目"):
                return False
            new_ws = Workspace(path)
            if self.html_bridge:
                self.html_bridge.close()
                self.flush_html_events()
                self.html_bridge=None
            if self.ws:
                self.ws.close()
            self.ws = new_ws
            self.map_id, self.focus_node, self.selected = None,None,set()
            recovered = new_ws.recovered_from
            self.config["workspace"] = str(new_ws.root)
            self.write_config()
            self.apply_workspace_theme()
            self.last_width = min(500,max(180,new_ws.data["preferences"].get("sidebarWidth",260)))
            self.root.after(100,lambda:self.main.sash_place(0,self.last_width,0))
            self.refresh_projects()
            maps = new_ws.data["mindmaps"]
            last = new_ws.data["preferences"].get("lastMindmap")
            if maps:
                self.load_map(last if last in maps else next(iter(maps)))
            else:
                self.render()
                self.load_editor(None)
            self.dirty=False
            self.selection_source="project"
            self.status.set("项目目录：" + str(new_ws.root) + " · 已保存")
            if recovered:
                messagebox.showinfo("元数据恢复","已加载快照：" + recovered + "\n保存时会保留损坏元数据副本。")
                self.changed()
            return True
        except Exception as e:
            self.error(e)
            return False

    def write_config(self):
        self.config_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.config,ensure_ascii=False),encoding="utf-8")
        os.replace(temporary,self.config_path)

    def changed(self):
        if not self.ws:return
        self.dirty=True
        self.status.set("有未保存修改 · Ctrl+S 保存")
        self.update_count()

    def prepare_to_leave(self,title,always=False):
        if not self.ws:return True
        if not always and not (self.dirty or self.inline_edit or
                (self.html_bridge and self.html_bridge.has_unsaved())):
            return True
        choice=messagebox.askyesnocancel(title,"是否保存当前项目？",parent=self.root)
        if choice is None:return False
        if choice:
            if self.html_bridge and self.html_bridge.has_unsaved():
                self.status.set("请先在 HTML 编辑窗口保存内容，再继续操作")
                return False
            self.finish_inline()
            return self.save()
        self.finish_inline(False)
        if self.save_job:
            self.root.after_cancel(self.save_job);self.save_job=None
        self.dirty=False
        return True

    def save(self):
        self.finish_inline()
        if self.save_job:
            self.root.after_cancel(self.save_job)
            self.save_job=None
        if not self.ws or not self.dirty:
            return True
        if self.busy:
            self.save_job=self.root.after(700,self.save)
            return False
        try:
            self.ws.save()
            self.dirty=False
            self.status.set("已保存 · " + time.strftime("%H:%M:%S") + " · " + self.ws.data["name"])
            return True
        except Exception as e:
            self.error(e)
            return False

    def checkpoint(self):
        self.ws.checkpoint()

    def refresh_projects(self,selected=None):
        self.loading=True
        previous_selection=self.project_tree.selection()
        opened={i for i in self.project_tree.get_children("") if self.project_tree.item(i,"open")}
        def collect(parent=""):
            for i in self.project_tree.get_children(parent):
                if self.project_tree.item(i,"open"):
                    opened.add(i)
                collect(i)
        collect()
        self.project_tree.delete(*self.project_tree.get_children())
        if self.ws:
            projects=sorted(self.ws.data["projects"].values(),key=lambda x:x["sortOrder"])
            pending=projects[:]
            while pending:
                next_pending=[]
                for p in pending:
                    parent="p:"+p["parentId"] if p["parentId"] else ""
                    if parent and not self.project_tree.exists(parent):
                        next_pending.append(p)
                        continue
                    i="p:"+p["id"]
                    self.project_tree.insert(parent,"end",iid=i,text=("▣ " if not p["parentId"] else "📁 ")+p["name"],open=i in opened or not opened)
                if len(next_pending)==len(pending):
                    break
                pending=next_pending
            for m in self.ws.data["mindmaps"].values():
                self.project_tree.insert("p:"+m["projectId"],"end",iid="m:"+m["id"],text="◇ "+m["name"])
            retained=[i for i in previous_selection if self.project_tree.exists(i)]
            if selected and self.project_tree.exists(selected):
                self.project_tree.selection_set(selected)
                self.project_tree.focus(selected)
                self.project_tree.see(selected)
            elif retained:
                self.project_tree.selection_set(retained)
        self.loading=False

    def current_project(self):
        items=self.project_tree.selection()
        if items:
            kind,i=items[0].split(":",1)
            return i if kind=="p" else self.ws.data["mindmaps"][i]["projectId"]
        if self.map_id:
            return self.ws.data["mindmaps"][self.map_id]["projectId"]
        return None

    def select_project(self,event=None):
        if self.loading or self.busy or not self.ws:
            return
        items=self.project_tree.selection()
        item=self.project_tree.focus()
        if item not in items: item=items[0] if items else ""
        if item.startswith("m:") and item[2:]!=self.map_id:
            self.load_map(item[2:],preserve_selection=True)

    def add_project(self,parent=None):
        if self.busy:return
        if parent:
            self.add_folder(parent)
            return
        directory=filedialog.askdirectory(title="选择新项目保存文件夹",parent=self.root)
        if not directory:return
        existing=Path(directory)/"workspace.json"
        if existing.exists():
            try:
                populated=bool(json.loads(existing.read_text(encoding="utf-8"))["projects"])
            except (OSError,ValueError,KeyError):
                self.open_workspace(directory)
                return
            if populated:
                self.open_workspace(directory)
                return
        name=simpledialog.askstring("新建项目","项目名称",initialvalue=Path(directory).name,parent=self.root)
        if not name:return
        if not self.open_workspace(directory) or self.ws.root!=Path(directory).resolve():return
        self.checkpoint()
        self.ws.data["name"]=name.strip()
        project=self.ws.add_project(name.strip())
        self.refresh_projects("p:"+project)
        self.render();self.load_editor(None)
        self.changed();self.save()
        self.status.set("项目已创建："+str(self.ws.root)+" · 在项目下新建文件夹或导图")

    def add_folder(self,parent=None):
        if not self.guard():return
        parent=parent or self.current_project()
        if not parent:
            self.status.set("请先在左侧选择项目或文件夹")
            return
        name=simpledialog.askstring("新建子文件夹","文件夹名称",parent=self.root)
        if not name:return
        self.finish_inline()
        self.checkpoint()
        folder=self.ws.add_project(name.strip(),parent)
        self.refresh_projects("p:"+folder)
        self.selection_source="project"
        self.changed()

    def add_map(self):
        if not self.guard():return
        project=self.current_project()
        if not project:
            self.status.set("请先在左侧选择项目或文件夹")
            return
        name=simpledialog.askstring("创建导图","导图名称",parent=self.root)
        if name:
            self.finish_inline()
            self.checkpoint()
            i=self.ws.add_map(project,name.strip(),starter=True)
            self.refresh_projects("m:"+i)
            self.load_map(i)
            self.changed()

    def project_context(self,event):
        if not self.guard():
            return
        self.selection_source="project"
        item=self.project_tree.identify_row(event.y)
        if item and item not in self.project_tree.selection():
            self.project_tree.selection_set(item)
        menu=self.menu()
        menu.add_command(label="新建项目…",command=self.add_project)
        if self.project_tree.selection():
            menu.add_command(label="导出所选项目包…",command=self.export_project_package)
        if item:
            kind,i=item.split(":",1)
            if kind=="p":
                menu.add_command(label="新建子文件夹",command=lambda:self.add_folder(i))
                menu.add_command(label="新建导图",command=self.add_map)
            menu.add_command(label="重命名",command=lambda:self.rename_project_item(kind,i))
            menu.add_command(label="移动…",command=lambda:self.move_project_item(kind,i))
            menu.add_command(label="删除",command=lambda:self.delete_project_item(kind,i))
        menu.tk_popup(event.x_root,event.y_root)

    def rename_project_item(self,kind,i):
        if not self.guard():
            return
        table="projects" if kind=="p" else "mindmaps"
        value=self.ws.data[table][i]
        name=simpledialog.askstring("重命名","名称",initialvalue=value["name"],parent=self.root)
        if name:
            self.checkpoint()
            value["name"]=name.strip()
            self.refresh_projects(kind+":"+i)
            self.changed()

    def choose_project(self,title,allow_root=False):
        win=tk.Toplevel(self.root)
        win.title(title)
        win.geometry("530x380")
        tree=ttk.Treeview(win,show="tree",selectmode="browse")
        tree.pack(fill="both",expand=True,padx=10,pady=10)
        if allow_root:
            tree.insert("","end",iid="root",text="工作区顶层")
        remaining=list(self.ws.data["projects"].values())
        while remaining:
            deferred=[]
            for p in remaining:
                if p["parentId"] and not tree.exists(p["parentId"]):
                    deferred.append(p)
                else:
                    tree.insert(p["parentId"] or "","end",iid=p["id"],text=p["name"],open=True)
            remaining=deferred
        result=[]
        def accept():
            if tree.selection():
                result.append(None if tree.selection()[0]=="root" else tree.selection()[0])
                win.destroy()
        ttk.Button(win,text="确定",command=accept).pack(pady=8)
        win.transient(self.root)
        win.grab_set()
        self.root.wait_window(win)
        return result

    def move_project_item(self,kind,i,target=None):
        if not self.guard():
            return
        if target is None:
            choice=self.choose_project("选择目标项目",kind=="p")
            if not choice:
                return
            target=choice[0]
        try:
            self.checkpoint()
            if kind=="p":
                self.ws.move_project(i,target)
            else:
                self.ws.data["mindmaps"][i]["projectId"]=target
            self.refresh_projects(kind+":"+i)
            self.changed()
        except Exception as e:
            self.error(e)

    def project_press(self,e):
        self.selection_source="project"
        self.project_drag=None if e.state & 5 or len(self.project_tree.selection())>1 else (self.project_tree.identify_row(e.y),e.x,e.y)

    def project_release(self,e):
        if not self.guard() or not getattr(self,"project_drag",None):
            return
        item,x,y=self.project_drag
        target=self.project_tree.identify_row(e.y)
        if item and target and item!=target and abs(e.y-y)>12:
            kind,i=item.split(":",1)
            tknd,tid=target.split(":",1)
            dest=tid if tknd=="p" else self.ws.data["mindmaps"][tid]["projectId"]
            self.move_project_item(kind,i,dest)

    def delete_project_item(self,kind,i):
        if not self.guard():return
        table="projects" if kind=="p" else "mindmaps"
        if i not in self.ws.data[table]:return
        self.finish_inline()
        self.checkpoint()
        self.ws.remove_project(i) if kind=="p" else self.ws.remove_map(i)
        self.after_history_change()

    def delete_selection(self,widget=None):
        if widget==self.project_tree or (widget is None and self.selection_source=="project"):
            items=self.project_tree.selection()
            if items:
                kind,i=items[0].split(":",1)
                self.delete_project_item(kind,i)
            return
        self.delete_nodes()


    def load_map(self,i,preserve_selection=False):
        if not self.ws or i not in self.ws.data["mindmaps"] or self.busy:
            return
        if i!=self.map_id:
            self.selected=set()
            self.map_id=i
            self.zoom=self.ws.data["mindmaps"][i]["viewState"].get("zoom",1)
            self.focus_node=self.ws.data["mindmaps"][i]["rootNodeId"]
            self.selected={self.focus_node}
        self.ws.data["preferences"]["lastMindmap"]=i
        if not preserve_selection:self.refresh_projects("m:"+i)
        self.render()
        self.load_editor(self.focus_node)
        self.changed()

    def show_view(self):
        self.finish_inline()
        if self.view.get()=="map":
            self.outline_page.pack_forget()
            self.canvas_frame.pack(fill="both",expand=True)
        else:
            self.canvas_frame.pack_forget()
            self.outline_page.pack(fill="both",expand=True)
        self.root.update_idletasks()
        self.render()

    def request_render(self):
        if self.render_job:
            self.root.after_cancel(self.render_job)
        self.render_job=self.root.after(80,self.render)

    def render(self):
        if self.render_job:
            self.root.after_cancel(self.render_job)
            self.render_job=None
        self.canvas.delete("all")
        self.boxes,self.visible={},[]
        self.attachment_hits,self.title_y={},{}
        p=self.theme
        if not self.ws or self.map_id not in self.ws.data["mindmaps"]:
            self.outline.delete(*self.outline.get_children())
            self.outline_title.set("科研资料")
            self.outline_meta.set("创建项目和导图，开始整理")
            self.canvas.create_text(230,140,text="创建或打开项目文件夹\n按章节新建思维导图",
                fill=p["muted"],font=("Microsoft YaHei UI",13),justify="left")
            self.canvas.create_window(230,230,window=self.empty_start)
            self.empty_start.configure(text="＋ 新建章节导图" if self.ws and self.ws.data["projects"] else "＋ 新建项目并选择保存文件夹")
            self.overview.place_forget()
            self.update_count()
            self.refresh_drop_regions()
            self.refresh_attachment_panel()
            return
        self.overview.place(relx=1,rely=1,anchor="se",x=-18,y=-18)
        data=self.ws.data
        root=data["mindmaps"][self.map_id]["rootNodeId"]
        self.location_var.set(" / ".join(project_path(data,data["mindmaps"][self.map_id]["projectId"])+[data["mindmaps"][self.map_id]["name"]]))
        self.outline_title.set(data["nodes"][root]["title"])
        self.outline_meta.set(f'{len(ordered_nodes(data,self.map_id))} 个节点 · 双击内容编辑 · Shift+Enter 换行')
        pending=[(root,0,None)]
        depth,visible_children,branch_key={},{},{}
        child_index={}
        for node in data["nodes"].values():
            if node["mindmapId"]==self.map_id:
                child_index.setdefault(node["parentId"],[]).append(node["id"])
        for kids in child_index.values():
            kids.sort(key=lambda i:(data["nodes"][i]["sortOrder"],i))
        def kids_of(i):
            return child_index.get(i,[])
        complete=[]
        stack=[root]
        while stack:
            i=stack.pop()
            complete.append(i)
            stack.extend(reversed(kids_of(i)))
        first=kids_of(root)
        while pending:
            i,d,top=pending.pop()
            self.visible.append(i)
            depth[i]=d
            branch_key[i]=top
            kids=[] if data["nodes"][i]["collapsed"] else kids_of(i)
            visible_children[i]=kids
            pending.extend((k,d+1,k if i==root else top) for k in reversed(kids))
        z=self.zoom
        title_font=tkfont.Font(family="Microsoft YaHei UI",size=11,weight="bold")
        widths,heights={},{}
        for i in self.visible:
            n=data["nodes"][i]
            d=depth[i]
            content=self.node_content(i)
            files=n["attachmentIds"]
            file_node=len(files)==1 and n["title"]==data["attachments"][files[0]]["originalName"] and not n["bodyRichText"]["text"] and not n["notes"]
            lines=content.split("\n")
            measure=max(title_font.measure(line) for line in lines)
            widths[i]=min(560,max(170,measure+(74 if file_node else 58)))
            line_count=sum(max(1,(title_font.measure(line)+widths[i]-53)//(widths[i]-52)) for line in lines)
            heights[i]=max(54,24+line_count*24+(0 if file_node else len(files)*30))
        # Subtree spans include each card's actual attachment rows.
        spans={}
        for i in reversed(self.visible):
            spans[i]=max(heights[i]+34,sum(spans[k] for k in visible_children[i]))
        ypos={}
        pending=[(root,30)]
        while pending:
            i,top=pending.pop()
            ypos[i]=top+spans[i]/2
            offset=top+(spans[i]-sum(spans[k] for k in visible_children[i]))/2
            for k in visible_children[i]:
                pending.append((k,offset))
                offset+=spans[k]
        height=spans[root]+60
        x_positions={root:60}
        for i in self.visible[1:]:
            parent=data["nodes"][i]["parentId"]
            x_positions[i]=x_positions[parent]+widths[parent]+56
        extent=max((x_positions[i]+widths[i]+60)*z for i in self.visible)
        pad_x=max(0,(self.canvas.winfo_width()-extent)/2)
        pad_y=max(0,(self.canvas.winfo_height()-height*z)/2)
        colors={}
        for i in self.visible:
            top=branch_key[i]
            colors[i]=p["rainbow"][first.index(top)%len(p["rainbow"])] if self.rainbow_var.get() and top in first else p["branch"]
            d=depth[i]
            x,y=x_positions[i]*z+pad_x,ypos[i]*z+pad_y
            half=heights[i]*z/2
            self.boxes[i]=(x,y-half,x+widths[i]*z,y+half)
        for i in self.visible:
            parent=data["nodes"][i]["parentId"]
            if parent not in self.boxes:
                continue
            a,b=self.boxes[parent],self.boxes[i]
            ax,ay=a[2],(a[1]+a[3])/2
            bx,by=b[0],(b[1]+b[3])/2
            mid=(ax+bx)/2
            r=min(24*z,(bx-ax)/2,abs(by-ay)/2)
            sign=1 if by>ay else -1
            pts=[ax,ay,mid-r,ay,mid,ay,mid,ay+sign*r,mid,by-sign*r,mid,by,mid+r,by,bx,by]
            width=max(1.5,(3.5 if depth[i]==1 else 2.5 if depth[i]==2 else 2)*z) if self.taper_var.get() else max(1.5,3*z)
            self.canvas.create_line(*pts,smooth=True,splinesteps=24,fill=colors[i],width=width)
        for i in self.visible:
            n=data["nodes"][i]
            x1,y1,x2,y2=self.boxes[i]
            d=depth[i]
            top=branch_key[i]
            bg,fg,custom=node_colors(n["style"],p)
            if not custom and d:
                bg=p["node"]
                if d==1 and top==first[0] and self.rainbow_var.get():
                    bg=p["accent"]
                fg=p["text"] if p is not THEMES["paper"] else ("#ffffff" if bg==p["accent"] else p["text"])
            tags=("node",i)
            selected=i in self.selected
            edge="#ffd84d" if selected else p["accent"] if d==0 else colors[i] if d==1 else p["border"]
            self.rounded_box((x1+2*z,y1+3*z,x2+2*z,y2+3*z),p["ui"],p["ui"],1,tags)
            self.rounded_box(self.boxes[i],bg,edge,max(3,5*z) if selected else (3 if d==0 else 1)*z,tags)
            files=n["attachmentIds"]
            file_node=len(files)==1 and n["title"]==data["attachments"][files[0]]["originalName"] and not n["bodyRichText"]["text"] and not n["notes"]
            label=self.node_content(i)+("  ▸" if n["collapsed"] and kids_of(i) else "")
            title_height=heights[i]-(0 if file_node else len(files)*30)
            self.title_y[i]=y1+title_height*z/2
            self.canvas.create_text(x1+14*z,self.title_y[i],text=label,anchor="w",
                width=(widths[i]-(68 if file_node else 28))*z,fill=fg,
                font=("Microsoft YaHei UI",max(5,int((13 if d==0 else 11)*z)),"bold"),tags=tags)
            if file_node:
                a=files[0]
                self.attachment_hits[(i,a)]=(x2-48*z,y1,x2,y2)
                self.draw_attachment_icon(x2-30*z,(y1+y2)/2,z,tags+("attachment",a),data["attachments"][a],True)
            else:
                row_top=y1+title_height*z
                for a in files:
                    filename=data["attachments"][a]["originalName"]
                    self.attachment_hits[(i,a)]=(x1+9*z,row_top,x2-9*z,row_top+28*z)
                    self.draw_attachment_icon(x1+18*z,row_top+14*z,.7*z,tags+("attachment",a),data["attachments"][a])
                    self.canvas.create_text(x1+44*z,row_top+14*z,text=filename,anchor="w",
                        width=(widths[i]-58)*z,fill=fg,font=("Microsoft YaHei UI",max(5,int(9*z))),
                        tags=tags+("attachment",a))
                    row_top+=30*z
        maxx=max(b[2] for b in self.boxes.values())+60*z
        maxy=max(b[3] for b in self.boxes.values())+60*z
        self.canvas.configure(scrollregion=(0,0,maxx+pad_x,maxy+pad_y))
        self.zoom_var.set(f"{round(z*100)}%" if self.view.get()=="map" else "大纲")
        self.draw_grid()
        self.draw_minimap()
        self.loading=True
        if getattr(self,"outline_map",None)!=self.map_id:
            self.outline.delete(*self.outline.get_children())
            self.outline_ids=set()
            self.outline_map=self.map_id
        for i in complete:
            n=data["nodes"][i]
            label=("☑ " if i in self.selected else "☐ ")+self.node_content(i).replace("\n","  /  ")
            a=n["attachmentIds"]
            pill=(self.ws.data["attachments"][a[0]]["type"].lstrip(".").upper()+f" · {len(a)}") if a else ""
            tags=["branch" if kids_of(i) else "leaf"]
            bg,fg,custom=node_colors(n["style"],p)
            if custom:
                tag="color:"+i
                self.outline.tag_configure(tag,background=bg,foreground=fg)
                tags.append(tag)
            values=(pill,)
            if self.outline.exists(i):
                self.outline.item(i,text=label,image=self.file_icons[self.attachment_kind(data["attachments"][a[0]])] if a else "",values=values,tags=tags,open=not n["collapsed"])
                self.outline.move(i,n["parentId"] or "","end")
            else:
                self.outline.insert(n["parentId"] or "","end",iid=i,text=label,image=self.file_icons[self.attachment_kind(data["attachments"][a[0]])] if a else "",values=values,tags=tags,open=not n["collapsed"])
        for i in self.outline_ids-set(complete):
            if self.outline.exists(i):
                self.outline.delete(i)
        self.outline_ids=set(complete)
        self.outline.selection_set(*[i for i in self.selected if self.outline.exists(i)])
        if self.focus_node and self.outline.exists(self.focus_node):
            self.outline.focus(self.focus_node)
        self.loading=False
        self.update_count()
        self.refresh_drop_regions()
        self.refresh_attachment_panel()

    def canvas_resized(self,event):
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        def redraw():
            self.resize_job=None
            self.render()
        self.resize_job=self.root.after_idle(redraw)

    def canvas_scrolled(self,scrollbar,axis,values):
        scrollbar.set(*values)
        if hasattr(self,"grid_var"):
            self.draw_grid()
            self.minimap_viewport()
            self.refresh_drop_regions()

    def draw_grid(self):
        self.canvas.delete("grid")
        if not getattr(self,"grid_var",None) or not self.grid_var.get() or not self.boxes:
            return
        left,top=self.canvas.canvasx(0),self.canvas.canvasy(0)
        right,bottom=left+self.canvas.winfo_width(),top+self.canvas.winfo_height()
        step=max(40,round(110*self.zoom))
        for x in range(int(left//step)*step,int(right)+step,step):
            self.canvas.create_line(x,top,x,bottom,fill=self.theme["grid"],dash=(2,6),tags="grid")
        for y in range(int(top//step)*step,int(bottom)+step,step):
            self.canvas.create_line(left,y,right,y,fill=self.theme["grid"],dash=(2,6),tags="grid")
        self.canvas.tag_lower("grid")

    def draw_minimap(self):
        self.minimap.delete("all")
        if not self.boxes:
            return
        _,_,width,height=map(float,self.canvas.cget("scrollregion").split())
        scale=min(171/max(1,width),98/max(1,height))
        self.overview_scale=scale
        for i,box in self.boxes.items():
            parent=self.ws.data["nodes"][i]["parentId"]
            if parent in self.boxes:
                a=self.boxes[parent]
                self.minimap.create_line(7+a[2]*scale,7+(a[1]+a[3])*scale/2,
                    7+box[0]*scale,7+(box[1]+box[3])*scale/2,fill=self.theme["branch"])
            self.minimap.create_rectangle(*(7+v*scale for v in box),
                outline="#ffd84d" if i in self.selected else self.theme["branch"],
                fill=self.theme["panel"])
        self.minimap_viewport()

    def minimap_viewport(self):
        if not hasattr(self,"overview_scale") or not self.boxes:
            return
        s=self.overview_scale
        left,top=self.canvas.canvasx(0),self.canvas.canvasy(0)
        box=(7+left*s,7+top*s,7+(left+self.canvas.winfo_width())*s,
             7+(top+self.canvas.winfo_height())*s)
        self.minimap.delete("viewport")
        self.minimap.create_rectangle(*box,outline=self.theme["text"],dash=(3,2),tags="viewport")

    def minimap_click(self,event):
        if not self.boxes:
            return
        _,_,width,height=map(float,self.canvas.cget("scrollregion").split())
        x=(event.x-7)/self.overview_scale-self.canvas.winfo_width()/2
        y=(event.y-7)/self.overview_scale-self.canvas.winfo_height()/2
        self.canvas.xview_moveto(max(0,x)/width)
        self.canvas.yview_moveto(max(0,y)/height)

    def update_count(self):
        self.count_var.set(f"已选 {len(self.selected)} 节点 · {len(self.selected_attachment_ids())} 附件")

    def node_at(self,x,y):
        x,y=self.canvas.canvasx(x),self.canvas.canvasy(y)
        for i,box in self.boxes.items():
            if box[0]<=x<=box[2] and box[1]<=y<=box[3]:
                return i
        return None

    def expanded_nodes(self,items):
        return {node for item in items if item in self.ws.data["nodes"]
                for node in branch(self.ws.data,item)}

    def select_node(self,i,ctrl=False,shift=False):
        if not self.ws or i not in self.ws.data["nodes"]:return
        self.selection_source="node"
        selected_branch=set(branch(self.ws.data,i))
        if shift and self.anchor in self.visible and i in self.visible:
            a,b=sorted([self.visible.index(self.anchor),self.visible.index(i)])
            self.selected.update(self.expanded_nodes(self.visible[a:b+1]))
        elif ctrl:
            if i in self.selected:
                self.selected.difference_update(selected_branch)
            else:
                self.selected.update(selected_branch)
        else:
            self.selected=selected_branch
        self.focus_node=i
        if not shift:self.anchor=i
        self.render()
        self.load_editor(i)

    def canvas_hover(self,e):
        hand=self.attachment_at(e.x,e.y) or not self.node_at(e.x,e.y)
        self.canvas.configure(cursor="hand2" if hand else "")

    def canvas_press(self,e):
        self.selection_source="node"
        self.finish_inline()
        if not self.guard() or not self.map_id:
            return
        self.canvas.focus_set()
        i=self.node_at(e.x,e.y)
        if not i:
            self.drag={"pan":True,"x":e.x,"y":e.y}
            self.canvas.scan_mark(e.x,e.y)
            self.canvas.configure(cursor="hand2")
            return
        self.drag={"node":i,"x":e.x,"y":e.y,"moved":False,"ctrl":bool(e.state&4)}
        self.select_node(i,bool(e.state&4),bool(e.state&1))

    def canvas_motion(self,e):
        if not self.drag:
            return
        d=self.drag
        if d.get("pan"):
            self.canvas.scan_dragto(e.x,e.y,gain=1)
            return
        if abs(e.x-d["x"])+abs(e.y-d["y"])>10:
            d["moved"]=True
        x,y=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y)
        if d["moved"]:
            if "ghost" not in d:
                box=self.boxes[d["node"]]
                self.rounded_box(box,self.theme["selection"],self.theme["accent"],2,("drag-ghost",))
                self.canvas.create_text(box[0]+12*self.zoom,(box[1]+box[3])/2,
                    text=self.ws.data["nodes"][d["node"]]["title"],anchor="w",
                    width=box[2]-box[0]-24*self.zoom,fill=self.theme["text"],
                    font=("Microsoft YaHei UI",max(7,int(11*self.zoom))),tags="drag-ghost")
                d["ghost"]=True
                d["last"]=(self.canvas.canvasx(d["x"]),self.canvas.canvasy(d["y"]))
                d["line"]=self.canvas.create_line(*d["last"],x,y,arrow="last",
                    fill=self.theme["accent"],width=2,tags="drag")
            lx,ly=d["last"]
            self.canvas.move("drag-ghost",x-lx,y-ly)
            d["last"]=(x,y)
            self.canvas.coords(d["line"],self.canvas.canvasx(d["x"]),self.canvas.canvasy(d["y"]),x,y)

    def repaint_panes(self):
        if not self.root.winfo_exists():
            return
        self.root.update_idletasks()
        if os.name=="nt":
            hwnd=ctypes.windll.user32.GetAncestor(self.root.winfo_id(),2)
            ctypes.windll.user32.RedrawWindow(ctypes.c_void_p(hwnd),None,None,0x185)

    def pane_released(self,e):
        def finish():
            if e.widget==self.main:
                self.sidebar_resize()
            self.repaint_panes()
        self.root.after_idle(finish)

    def begin_project(self):
        if not self.ws or not self.ws.data["projects"]:
            self.add_project()
        else:
            if not self.current_project():
                self.refresh_projects("p:"+next(iter(self.ws.data["projects"])))
            self.add_map()

    def tab_child(self,e=None):
        if self.guard() and self.focus_node:
            self.add_node(False,focus_title=False)
        return "break"

    def canvas_release(self,e):
        if not self.drag:
            return
        d,self.drag=self.drag,None
        if d.get("pan"):
            self.canvas_hover(e)
            return
        if d["node"] and d["moved"]:
            target=self.node_at(e.x,e.y)
            if target and target!=d["node"]:
                try:
                    self.checkpoint()
                    self.ws.move_node(d["node"],target)
                    self.ws.data["nodes"][target]["collapsed"]=False
                    self.changed()
                except Exception as error:
                    self.error(error)
            self.render()
            self.root.after_idle(self.repaint_panes)
        elif d["node"]:
            attachment=self.attachment_at(e.x,e.y)
            if attachment:
                last=getattr(self,"last_attachment_open",(None,0))
                now=time.monotonic()
                if attachment!=last[0] or now-last[1]>.5:
                    self.last_attachment_open=(attachment,now)
                    self.open_attachment(attachment)

    def outline_select(self,e=None):
        if self.loading or self.busy or not self.ws:return
        items=set(self.outline.selection())
        if items==self.selected:return
        self.selection_source="node"
        self.selected=self.expanded_nodes(items)
        self.focus_node=self.outline.focus() or next(iter(items),None)
        self.loading=True
        if set(self.outline.selection())!=self.selected:
            self.outline.selection_set(list(self.selected))
        for i in ordered_nodes(self.ws.data,self.map_id) if self.map_id else []:
            self.outline.item(i,text=("☑ " if i in self.selected else "☐ ")+self.node_content(i).replace("\n","  /  "))
        self.loading=False
        if getattr(self,"editor_node",None)!=self.focus_node:
            self.load_editor(self.focus_node)
        self.update_count()
        self.refresh_attachment_panel()

    def outline_toggle(self,e):
        self.selection_source="node"
        i=self.outline.identify_row(e.y)
        if not self.guard():return "break"
        if i and "indicator" not in self.outline.identify_element(e.x,e.y):
            self.outline.focus_set()
            self.select_node(i,bool(e.state&4),bool(e.state&1))
            return "break"

    def outline_collapse(self,collapsed):
        if self.loading or not self.guard():
            return
        i=self.outline.focus()
        if i:
            self.checkpoint()
            self.ws.data["nodes"][i]["collapsed"]=collapsed
            self.changed()
            self.root.after_idle(self.render)

    def node_context(self,e):
        self.selection_source="node"
        if not self.guard():
            return
        i=self.node_at(e.x,e.y) if e.widget==self.canvas else self.outline.identify_row(e.y)
        if i and i not in self.selected:
            self.select_node(i)
        menu=self.menu()
        for label,cmd in [("添加子节点 · Tab",lambda:self.add_node(False)),
            ("添加同级 · Enter",lambda:self.add_node(True)),("选择整个分支",self.select_branch),
            ("编辑内容",self.edit_title),
            ("折叠 / 展开",self.toggle_node),("缩进",self.indent),("提升",self.outdent),
            ("上移",lambda:self.sort_node(-1)),("下移",lambda:self.sort_node(1)),
            ("删除所选节点",self.delete_nodes)]:
            menu.add_command(label=label,command=cmd)
        menu.tk_popup(e.x_root,e.y_root)

    def select_branch(self):
        if self.guard() and self.focus_node:
            self.selected.update(branch(self.ws.data,self.focus_node))
            self.render()

    def add_node(self,sibling=False,focus_title=True):
        self.selection_source="node"
        if not self.guard() or not self.map_id:
            return
        parent=self.focus_node or self.ws.data["mindmaps"][self.map_id]["rootNodeId"]
        self.checkpoint()
        i=self.ws.add_node(parent,sibling=sibling)
        self.ws.data["nodes"][self.ws.data["nodes"][i]["parentId"]]["collapsed"]=False
        self.selected={i}
        self.focus_node=i
        self.render()
        self.load_editor(i)
        self.changed()
        if self.view.get()=="outline":
            self.outline.see(i)
        elif i in self.boxes:
            x1,y1,x2,y2=self.boxes[i]
            region=list(map(float,self.canvas.cget("scrollregion").split()))
            width,height=self.canvas.winfo_width(),self.canvas.winfo_height()
            if x1<self.canvas.canvasx(0) or x2>self.canvas.canvasx(width):
                self.canvas.xview_moveto(max(0,((x1+x2-width)/2)/region[2]))
            if y1<self.canvas.canvasy(0) or y2>self.canvas.canvasy(height):
                self.canvas.yview_moveto(max(0,((y1+y2-height)/2)/region[3]))
        if focus_title:
            self.edit_title(i)
        else:
            (self.canvas if self.view.get()=="map" else self.outline).focus_set()

    def delete_nodes(self):
        if not self.guard() or not self.selected:return
        self.finish_inline()
        try:
            self.checkpoint()
            root=self.ws.data["mindmaps"][self.map_id]["rootNodeId"]
            if root in self.selected:
                self.ws.remove_map(self.map_id)
            else:
                self.ws.remove_nodes(self.selected)
            self.after_history_change()
        except Exception as e:
            self.error(e)

    def toggle_node(self):
        if self.guard() and self.focus_node:
            self.checkpoint()
            n=self.ws.data["nodes"][self.focus_node]
            n["collapsed"]=not n["collapsed"]
            self.render()
            self.changed()

    def indent(self):
        if not self.guard() or not self.focus_node:
            return
        n=self.ws.data["nodes"][self.focus_node]
        if not n["parentId"]:
            return
        siblings=children(self.ws.data,n["parentId"])
        index=siblings.index(n["id"])
        if index:
            self.checkpoint()
            self.ws.move_node(n["id"],siblings[index-1])
            self.ws.data["nodes"][siblings[index-1]]["collapsed"]=False
            self.render()
            self.changed()

    def outdent(self):
        if not self.guard() or not self.focus_node:
            return
        n=self.ws.data["nodes"][self.focus_node]
        if n["parentId"]:
            parent=self.ws.data["nodes"][n["parentId"]]
            if parent["parentId"]:
                self.checkpoint()
                self.ws.move_node(n["id"],parent["parentId"])
                self.render()
                self.changed()

    def sort_node(self,direction):
        if not self.guard() or not self.focus_node:
            return
        n=self.ws.data["nodes"][self.focus_node]
        if not n["parentId"]:
            return
        siblings=children(self.ws.data,n["parentId"])
        old=siblings.index(n["id"])
        new=old+direction
        if 0<=new<len(siblings):
            self.checkpoint()
            siblings[old],siblings[new]=siblings[new],siblings[old]
            for order,i in enumerate(siblings):
                self.ws.data["nodes"][i]["sortOrder"]=order
            self.render()
            self.changed()

    def change_zoom(self,factor):
        if not self.guard() or not self.map_id:
            return
        self.zoom=min(2.5,max(.2,self.zoom*factor))
        self.ws.data["mindmaps"][self.map_id]["viewState"]["zoom"]=self.zoom
        self.render()
        self.changed()
        return "break"

    def fit_view(self):
        if self.view.get()=="outline":
            if self.focus_node and self.outline.exists(self.focus_node):
                self.outline.see(self.focus_node)
            return
        if not self.guard() or not self.boxes:
            return
        maxx=(max(b[2] for b in self.boxes.values())-min(b[0] for b in self.boxes.values()))/self.zoom+120
        maxy=(max(b[3] for b in self.boxes.values())-min(b[1] for b in self.boxes.values()))/self.zoom+100
        self.zoom=min(1.3,max(.2,min(self.canvas.winfo_width()/maxx,self.canvas.winfo_height()/maxy)))
        self.ws.data["mindmaps"][self.map_id]["viewState"]["zoom"]=self.zoom
        self.render()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.changed()

    def sidebar_resize(self,e=None):
        if self.ws and not self.sidebar_hidden:
            width=min(500,max(180,self.main.sash_coord(0)[0]))
            self.last_width=width
            self.main.sash_place(0,width,0)
            self.ws.data["preferences"]["sidebarWidth"]=width
            self.changed()

    def reset_sidebar(self,e=None):
        if e and abs(e.x-self.main.sash_coord(0)[0])>9:
            return
        self.main.sash_place(0,260,0)
        self.sidebar_resize()

    def toggle_sidebar(self):
        if self.sidebar_hidden:
            self.main.add(self.sidebar,before=self.right,minsize=180,width=self.last_width)
        else:
            self.sidebar_resize()
            self.main.forget(self.sidebar)
        self.sidebar_hidden=not self.sidebar_hidden

    def shortcut(self,action,e):
        if isinstance(e.widget,(tk.Text,tk.Entry,ttk.Entry,ttk.Combobox)):
            if action in {"undo","redo"} and isinstance(e.widget,tk.Text):
                try:
                    e.widget.edit_undo() if action=="undo" else e.widget.edit_redo()
                except tk.TclError:
                    pass
                return "break"
            return
        if action=="undo":
            self.undo()
        elif action=="redo":
            self.undo(True)
        elif action=="delete":
            self.delete_selection(e.widget)
        else:
            self.add_node(action=="sibling",focus_title=False)
        return "break"

    def undo(self,redo=False):
        if self.guard() and self.ws.undo(redo):
            self.after_history_change()

    def after_history_change(self):
        if self.map_id not in self.ws.data["mindmaps"]:
            self.map_id=next(iter(self.ws.data["mindmaps"]),None)
        self.selected={i for i in self.selected if i in self.ws.data["nodes"] and
                       self.ws.data["nodes"][i]["mindmapId"]==self.map_id}
        if self.focus_node not in self.selected:
            self.focus_node=self.ws.data["mindmaps"][self.map_id]["rootNodeId"] if self.map_id else None
        if not self.selected and self.focus_node:self.selected={self.focus_node}
        self.ws.data["preferences"]["lastMindmap"]=self.map_id
        self.apply_workspace_theme()
        self.refresh_projects("m:"+self.map_id if self.map_id else None)
        self.render()
        self.load_editor(self.focus_node)
        self.changed()

    def load_editor(self,i):
        if not self.ws or i not in self.ws.data["nodes"]:
            self.editor_win.withdraw()
        self.loading=True
        self.editor_node=i
        self.enable_editor(True)
        self.title_var.set("")
        self.body.delete("1.0","end")
        self.notes.delete("1.0","end")
        for tag in self.body.tag_names():
            if tag.startswith("hl"):
                self.body.tag_delete(tag)
        if self.ws and i in self.ws.data["nodes"]:
            n=self.ws.data["nodes"][i]
            self.title_var.set(n["title"])
            self.body.insert("1.0",n["bodyRichText"]["text"])
            self.notes.insert("1.0",n["notes"])
            for h in n["bodyRichText"]["highlights"]:
                self.add_highlight_tag(h["start"],h["end"],h["color"])
        else:
            self.enable_editor(False)
        self.body.edit_modified(False)
        self.notes.edit_modified(False)
        self.body.edit_reset()
        self.notes.edit_reset()
        self.loading=False
        self.refresh_attachment_panel(refresh=True)

    def editor_changed(self,e=None):
        if self.loading:
            self.body.edit_modified(False)
            self.notes.edit_modified(False)
            return
        if not self.guard() or self.focus_node not in self.ws.data["nodes"]:
            return
        n=self.ws.data["nodes"][self.focus_node]
        body=self.body.get("1.0","end-1c")
        notes=self.notes.get("1.0","end-1c")
        highlights=[]
        for tag in self.body.tag_names():
            if tag.startswith("hl"):
                ranges=self.body.tag_ranges(tag)
                for k in range(0,len(ranges),2):
                    a=len(self.body.get("1.0",ranges[k]))
                    b=len(self.body.get("1.0",ranges[k+1]))
                    if b>a:
                        highlights.append({"start":a,"end":b,"color":self.body.tag_cget(tag,"background")})
        title=self.title_var.get()
        if (n["title"],n["bodyRichText"],n["notes"])!=(title,{"text":body,"highlights":highlights},notes):
            now=time.monotonic()
            if getattr(self,"edit_node",None)!=self.focus_node or now-getattr(self,"edit_time",0)>1.2:
                self.checkpoint()
            self.edit_node,self.edit_time=self.focus_node,now
            n["title"],n["notes"],n["bodyRichText"]=title,notes,{"text":body,"highlights":highlights}
            self.changed()
            self.request_render()
        self.body.edit_modified(False)
        self.notes.edit_modified(False)

    def color_node(self,key):
        if self.guard() and self.focus_node:
            n=self.ws.data["nodes"][self.focus_node]
            color=colorchooser.askcolor(n["style"][key],parent=self.root)[1]
            if color:
                self.checkpoint()
                n["style"][key]=color
                n["style"]["custom"]=True
                self.render()
                self.changed()

    def add_highlight_tag(self,start,end,color):
        name="hl"+str(time.time_ns())
        self.body.tag_configure(name,background=color)
        self.body.tag_add(name,f"1.0+{start}c",f"1.0+{end}c")

    def highlight(self):
        if not self.guard() or not self.focus_node:
            return
        try:
            start=len(self.body.get("1.0","sel.first"))
            end=len(self.body.get("1.0","sel.last"))
        except tk.TclError:
            self.status.set("请先在正文中选择需要高亮的文字")
            return
        color=colorchooser.askcolor("#fff0a6",parent=self.root)[1]
        if color:
            self.checkpoint()
            self.add_highlight_tag(start,end,color)
            self.editor_changed()

    def clear_highlight(self):
        if self.guard() and self.focus_node:
            self.checkpoint()
            for tag in self.body.tag_names():
                if tag.startswith("hl"):
                    self.body.tag_delete(tag)
            self.editor_changed()


    def run_task(self,label,work,done,require_workspace=True):
        if self.busy or (require_workspace and not self.guard()):
            return
        self.busy=True
        self.enable_editor(False)
        self.status.set(label+"…")
        def worker():
            try:
                result=work()
                self.task_queue.put((True,result,done))
            except Exception as e:
                self.task_queue.put((False,e,done))
        threading.Thread(target=worker,daemon=True).start()

    def poll_tasks(self):
        try:
            while True:
                ok,value,done=self.task_queue.get_nowait()
                self.busy=False
                self.enable_editor(bool(self.focus_node))
                if ok:
                    try:
                        done(value)
                    except Exception as e:
                        self.error(e)
                else:
                    self.error(value)
        except queue.Empty:
            pass
        self.flush_html_events()
        self.root.after(200,self.poll_tasks)

    def flush_html_events(self):
        if not self.html_bridge or not self.ws:
            return
        while not self.html_bridge.events.empty():
            event=self.html_bridge.events.get()
            if event in self.ws.data["attachments"]:
                self.ws.refresh_attachment(event)
                self.load_editor(self.focus_node)
                self.changed()
                self.status.set("HTML 归档副本已保存 · Ctrl+S 保存项目索引")

    def import_files(self,folder=False,paths=None,file_nodes=False):
        if not self.guard() or not self.focus_node:
            self.status.set("请先选择一个节点")
            return
        entry=None
        if folder:
            source=filedialog.askdirectory(title="导入文件夹，保留全部资源层级",parent=self.root)
            if not source:
                return
            paths=[source]
            if messagebox.askyesno("HTML 入口","是否指定该文件夹中的入口 HTML？\n选择“否”时双击附件打开归档文件夹。",parent=self.root):
                selected=filedialog.askopenfilename(title="选择入口 HTML",initialdir=source,
                    filetypes=[("HTML","*.html *.htm")],parent=self.root)
                if not selected:
                    return
                try:
                    entry=Path(selected).relative_to(Path(source)).as_posix()
                except ValueError:
                    self.error(ValueError("入口文件必须位于所选文件夹内"))
                    return
        elif paths is None:
            paths=filedialog.askopenfilenames(title="选择归档文件（支持多选）",parent=self.root)
        if not paths:
            return
        node=self.focus_node
        self.checkpoint()
        def work():
            imported,errors=[],[]
            for p in paths:
                try:
                    target=self.ws.add_node(node,Path(p).name) if file_nodes else node
                    try:
                        imported.append(self.ws.import_attachment(target,p,entry))
                    except Exception:
                        if file_nodes:self.ws.data["nodes"].pop(target,None)
                        raise
                except Exception as e:
                    errors.append(Path(p).name+"："+str(e))
            return imported,errors
        def done(result):
            imported,errors=result
            self.ws.data["nodes"][node]["collapsed"]=False
            if file_nodes and imported:
                self.focus_node=next(n["id"] for n in self.ws.data["nodes"].values() if imported[-1] in n["attachmentIds"])
                self.selected={self.focus_node}
            self.load_editor(self.focus_node)
            self.render()
            self.changed()
            self.status.set(f"导入完成：成功 {len(imported)}，失败 {len(errors)}")
            if errors:
                messagebox.showwarning("部分导入失败","\n".join(errors),parent=self.root)
        self.run_task(f"复制归档 {len(paths)} 项",work,done)

    def attachment_details(self,e=None):
        self.update_export_button()
        ids=self.attach_tree.selection()
        if not ids or not self.ws:
            return
        a=self.ws.data["attachments"][ids[0]]
        modified=time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(a["modifiedAt"]))
        self.attachment_info.set(f'{a["type"]} · {a["size"]:,} 字节\n归档 {a["importedAt"]}\n修改 {modified}')

    def attachment_context(self,e):
        if not self.guard():
            return
        i=self.attach_tree.identify_row(e.y)
        if i and i not in self.attach_tree.selection():
            self.attach_tree.selection_set(i)
        menu=self.menu()
        target=i or next(iter(self.attach_tree.selection()),None)
        entries=[("打开附件",lambda:self.open_attachment(target)),
            ("打开归档目录",lambda:self.open_attachment(target,folder=True)),
            ("刷新大小与修改时间",lambda:self.load_editor(self.focus_node)),
            ("移除节点关联…",self.unlink_attachments)]
        if target:
            record=self.ws.data["attachments"][target]
            if record["type"] in {".html",".htm"} or Path(record.get("entry") or "").suffix.lower() in {".html",".htm"}:
                entries.insert(1,("使用内置 HTML 修订工具",lambda:self.open_attachment(target,system=False)))
        for label,cmd in entries:menu.add_command(label=label,command=cmd)
        menu.tk_popup(e.x_root,e.y_root)

    def open_attachment(self,i=None,folder=False,system=False):
        if not self.guard():
            return
        ids=self.attach_tree.selection()
        i=i or (ids[0] if ids else None)
        if not i:
            return
        try:
            self.ws.refresh_attachment(i)
            p=self.ws.attachment_path(i,for_open=not folder)
            if folder and p.is_file():
                p=p.parent
            if not folder and not system and p.suffix.lower() in {".html",".htm"} and p.is_file():
                from html_editor import HtmlEditor
                if self.html_bridge is None:
                    self.html_bridge=HtmlEditor()
                archived=self.ws.attachment_path(i)
                resources=archived if archived.is_dir() else p.parent
                self.html_bridge.open(i,p,resources,self.ws.root/"snapshots"/"html"/i)
            else:
                os.startfile(str(p))
            self.load_editor(self.focus_node)
        except Exception as e:
            self.error(e)

    def unlink_attachments(self):
        if not self.guard() or not self.focus_node:
            return
        ids=set(self.attach_tree.selection())
        if ids and messagebox.askyesno("移除关联",f"移除 {len(ids)} 个附件关联？\n归档文件保留在工作区。",parent=self.root):
            self.checkpoint()
            for node in self.selected:
                n=self.ws.data["nodes"][node]
                n["attachmentIds"]=[a for a in n["attachmentIds"] if a not in ids]
            self.load_editor(self.focus_node)
            self.render()
            self.changed()

    def archive_manager(self):
        if not self.guard():
            return
        win=tk.Toplevel(self.root)
        win.title("归档附件管理")
        win.geometry("880x480")
        tree=ttk.Treeview(win,columns=("refs","size"),show="tree headings",selectmode="browse")
        tree.heading("#0",text="归档文件")
        tree.heading("refs",text="节点引用数")
        tree.heading("size",text="当前大小")
        tree.pack(fill="both",expand=True,padx=10,pady=10)
        def fill():
            tree.delete(*tree.get_children())
            for a in self.ws.data["attachments"].values():
                refs=sum(a["id"] in n["attachmentIds"] for n in self.ws.data["nodes"].values())
                try:
                    self.ws.refresh_attachment(a["id"])
                    size=f'{a["size"]:,}'
                except Exception:
                    size="文件缺失"
                tree.insert("","end",iid=a["id"],text=a["originalName"],values=(refs,size))
        fill()
        def selected():
            return tree.selection()[0] if tree.selection() else None
        def delete():
            i=selected()
            if not i or self.busy:
                return
            refs=sum(i in n["attachmentIds"] for n in self.ws.data["nodes"].values())
            if refs:
                self.error(ValueError(f"此附件仍由 {refs} 个节点引用，请先解除关联"))
                return
            if messagebox.askyesno("永久删除归档附件","永久删除 "+self.ws.data["attachments"][i]["originalName"]+"？\n此操作删除归档文件，并清空撤销历史。",parent=win):
                try:
                    self.ws.delete_attachment(i)
                    self.changed()
                    self.save()
                    fill()
                    self.load_editor(self.focus_node)
                except Exception as e:
                    self.error(e)
        row=ttk.Frame(win)
        row.pack(pady=8)
        ttk.Button(row,text="打开",command=lambda:self.open_attachment(selected()) if selected() else None).pack(side="left",padx=5)
        def link():
            i=selected()
            if self.busy or not i or not self.focus_node:
                return
            n=self.ws.data["nodes"][self.focus_node]
            if i not in n["attachmentIds"]:
                self.checkpoint()
                n["attachmentIds"].append(i)
                self.changed()
                self.load_editor(self.focus_node)
                self.render()
                fill()
        ttk.Button(row,text="关联到当前节点",command=link).pack(side="left",padx=5)
        ttk.Button(row,text="永久删除…",command=delete).pack(side="left",padx=5)
        ttk.Button(row,text="刷新",command=fill).pack(side="left",padx=5)
        win.transient(self.root)
        win.grab_set()

    def selected_attachment_ids(self):
        if not self.ws or self.map_id not in self.ws.data["mindmaps"]:return []
        ids=[]
        for node in ordered_nodes(self.ws.data,self.map_id) if self.map_id else []:
            if node in self.selected:
                for attachment in self.ws.data["nodes"][node]["attachmentIds"]:
                    if attachment not in ids:ids.append(attachment)
        return ids

    def refresh_attachment_panel(self,refresh=False):
        if not hasattr(self,"attach_tree"):return
        ids=self.selected_attachment_ids()
        old=self.attach_tree.get_children()
        signature=(self.map_id,frozenset(self.selected))
        selection_changed=signature!=getattr(self,"attachment_selection_signature",None)
        self.attachment_selection_signature=signature
        if tuple(ids)!=old:
            self.attach_tree.delete(*old)
            for a in ids:
                record=self.ws.data["attachments"][a]
                self.attach_tree.insert("","end",iid=a,text=record["originalName"],image=self.file_icons[self.attachment_kind(record)],values=("",))
        if refresh or tuple(ids)!=old:
            for a in ids:
                record=self.ws.data["attachments"][a]
                try:
                    record=self.ws.refresh_attachment(a)
                    size=f'{record["size"]/1024:.1f} KB'
                except (OSError,ValueError):
                    size="缺失"
                self.attach_tree.item(a,values=(size,))
        if ids and (selection_changed or tuple(ids)!=old):self.attach_tree.selection_set(ids)
        self.attachment_summary.set(f"所选 {len(self.selected)} 节点 · {len(ids)} 附件")
        self.update_export_button()
        if ids and tuple(ids)!=old:self.inspector_tabs.select(self.attachment_panel)

    def update_export_button(self):
        selected=self.attach_tree.selection()
        count=len(selected) or len(self.attach_tree.get_children())
        self.export_button.configure(text=f"导出所选 {count} 个附件…" if selected else f"导出全部 {count} 个附件…")
        self.export_button.state(["!disabled"] if count else ["disabled"])

    def export_selected_attachments(self):
        if not self.guard():return
        self.finish_inline()
        ids=list(self.attach_tree.selection()) or list(self.attach_tree.get_children())
        if not ids:
            self.status.set("选择带附件的节点后，在右侧导出")
            return
        parent=filedialog.askdirectory(title="选择附件导出位置",parent=self.root)
        if not parent:return
        plan=self.ws.export_plan([{"kind":"attachment","id":a} for a in ids],False)
        used=set()
        for item in sorted(plan["attachments"],key=lambda a:(a["originalName"].casefold(),a["id"])):
            name=item["originalName"]
            base=Path(name);index=2
            while name.casefold() in used:
                name=f"{base.stem}_{index}{base.suffix}"
                index+=1
            used.add(name.casefold())
            item["path"]=name
        def done(result):
            self.last_export=result
            self.status.set(f'附件导出完成：{result["success"]} 文件 · {result["output"]}')
            self.attachment_info.set("导出目录："+result["output"])
            if result["failed"]:
                messagebox.showwarning("附件导出结果","\\n".join(result["errors"][:8]),parent=self.root)
        self.run_task("导出附件",lambda:self.ws.export(plan,parent,False,False,False),done)

    def export_outline(self):
        if not self.guard() or not self.map_id:
            return
        dest=filedialog.asksaveasfilename(title="导出当前导图 Markdown 大纲",defaultextension=".md",
            initialfile="outline.md",filetypes=[("Markdown","*.md")],parent=self.root)
        if not dest:
            return
        if Path(dest).resolve().is_relative_to(self.ws.root):
            self.error(ValueError("请将导出文件保存到工作区以外"))
            return
        nodes=[]
        for i in ordered_nodes(self.ws.data,self.map_id):
            n=self.ws.data["nodes"][i]
            m=self.ws.data["mindmaps"][self.map_id]
            nodes.append({**n,"nodePath":node_path(self.ws.data,i),"projectPath":project_path(self.ws.data,m["projectId"]),
                "mindmapName":m["name"]})
        try:
            Path(dest).write_text(make_outline(nodes),encoding="utf-8")
            self.status.set("大纲已导出："+dest)
        except Exception as e:
            self.error(e)

    def search_dialog(self):
        if not self.guard():
            return
        query=self.search_var.get().strip()
        if not query:
            self.status.set("请输入搜索关键字；范围包括项目、导图、节点文字、备注和附件名")
            return
        win=tk.Toplevel(self.root)
        win.title("全局搜索："+query)
        win.geometry("980x520")
        info=tk.StringVar(value="正在搜索…")
        ttk.Label(win,textvariable=info,padding=8).pack(fill="x")
        tree=ttk.Treeview(win,columns=("location",),show="tree headings")
        tree.heading("#0",text="匹配文本")
        tree.heading("location",text="所属项目 / 导图 / 节点")
        tree.column("#0",width=330)
        tree.column("location",width=600)
        tree.pack(fill="both",expand=True,padx=10,pady=5)
        results=[]
        def done(value):
            if not win.winfo_exists():
                return
            results.extend(value)
            for index,r in enumerate(results):
                tree.insert("","end",iid=str(index),text=r["text"],values=(r["location"],))
            info.set(f"找到 {len(results)} 项" if results else "没有匹配结果")
            self.status.set(f"搜索完成：{len(results)} 项")
        def navigate(e=None):
            if not tree.selection() or self.busy:
                return
            r=results[int(tree.selection()[0])]
            win.destroy()
            if r["kind"]=="attachment":
                self.open_attachment(r["id"])
            elif r["kind"]=="project":
                self.refresh_projects("p:"+r["id"])
            else:
                i=r["id"]
                if r["kind"]=="node":
                    map_id=self.ws.data["nodes"][i]["mindmapId"]
                    self.load_map(map_id)
                    k=self.ws.data["nodes"][i]["parentId"]
                    while k:
                        self.ws.data["nodes"][k]["collapsed"]=False
                        k=self.ws.data["nodes"][k]["parentId"]
                    self.select_node(i)
                    if i in self.boxes:
                        bbox=self.boxes[i]
                        region=list(map(float,self.canvas.cget("scrollregion").split()))
                        self.canvas.xview_moveto(max(0,(bbox[0]-80)/max(1,region[2])))
                        self.canvas.yview_moveto(max(0,(bbox[1]-80)/max(1,region[3])))
                    self.outline.see(i)
                else:
                    self.load_map(i)
                self.changed()
        tree.bind("<Double-Button-1>",navigate)
        ttk.Button(win,text="定位所选结果",command=navigate).pack(pady=8)
        self.run_task("搜索工作区",lambda:self.ws.search(query),done)

    def export_project_package(self):
        if not self.guard():return
        refs=list(self.project_tree.selection())
        if not refs:
            self.status.set("请在左侧选择项目、文件夹或思维导图")
            return
        if self.html_bridge and self.html_bridge.has_unsaved():
            self.status.set("请先保存 HTML 编辑窗口中的内容，再导出项目包")
            return
        self.finish_inline()
        kind,item=refs[0].split(":",1)
        table="projects" if kind=="p" else "mindmaps"
        name=self.ws.data[table][item]["name"] if len(refs)==1 else "所选项目"
        output=filedialog.asksaveasfilename(title="保存项目包",initialfile=clean_name(name)+".rwp",
            defaultextension=".rwp",filetypes=[("Research Workspace 项目包","*.rwp")],parent=self.root)
        if output:
            workspace=self.ws
            self.run_task("打包项目、导图及附件",lambda:workspace.export_project_package(refs,output),
                          lambda p:self.status.set("项目包已保存："+str(p)))

    def open_project_package(self,archive=None):
        if self.busy:return
        if not archive:
            archive=filedialog.askopenfilename(title="打开项目包",
                filetypes=[("Research Workspace 项目包","*.rwp")],parent=self.root)
        if not archive:return
        parent=filedialog.askdirectory(title="选择项目包还原后的保存位置",parent=self.root)
        if not parent:return
        name=clean_name(Path(archive).stem)
        target=Path(parent)/name
        index=2
        while target.exists():
            target=Path(parent)/(name+"_"+str(index));index+=1
        def done(folder):
            if not self.open_workspace(str(folder)):
                self.status.set("项目包已还原到："+str(folder))
        self.run_task("校验并还原项目包",lambda:restore_backup(archive,target),done,require_workspace=False)

    def backup_dialog(self):
        if not self.guard() or not self.save():
            return
        output=filedialog.asksaveasfilename(title="备份为新 ZIP 文件",initialfile="Research_Backup_"+time.strftime("%Y%m%d_%H%M%S")+".zip",
            defaultextension=".zip",filetypes=[("ZIP","*.zip")],parent=self.root)
        if output:
            self.run_task("备份整个工作区",lambda:self.ws.backup(output),
                lambda p:messagebox.showinfo("备份完成",str(p),parent=self.root))

    def restore_dialog(self):
        if not self.guard():
            return
        archive=filedialog.askopenfilename(title="选择工作区备份",filetypes=[("ZIP","*.zip")],parent=self.root)
        if not archive:
            return
        parent=filedialog.askdirectory(title="选择恢复目标的父目录",parent=self.root)
        if not parent:
            return
        name=simpledialog.askstring("恢复目录","请输入新目录名称",initialvalue="Research_Restored_"+time.strftime("%Y%m%d_%H%M%S"),parent=self.root)
        if not name:
            return
        from workspace import clean_name
        if clean_name(name)!=name:
            self.error(ValueError("请输入普通目录名称，长度至多 70 个字符"))
            return
        target=Path(parent)/name
        if target.resolve().is_relative_to(self.ws.root):
            self.error(ValueError("恢复目标请设在当前工作区以外"))
            return
        def done(p):
            if messagebox.askyesno("恢复完成",str(p)+"\n是否切换到恢复后的工作区？",parent=self.root):
                self.open_workspace(str(p))
        self.run_task("校验并恢复备份",lambda:restore_backup(archive,target),done)

    def help_dialog(self):
        messagebox.showinfo("使用说明",
            "双击节点或大纲内容：直接编辑；Enter 提交内容，Shift+Enter 换行，Escape 取消。\n"
            "Tab 提交当前内容并添加子节点；Enter 在选中状态添加同级节点。\n"
            "从桌面或文件夹拖文件到节点：松开后为每个文件创建一个附件子节点。\n"
            "文件节点显示文件名；HTML 用内置修订工具打开，其他附件用系统默认应用打开。\n"
            "Ctrl+点击多选，Shift+点击范围；左键按住空白处自动使用手掌平移画布。\n中键同样可平移，Ctrl+滚轮缩放。\n"
            "选择父节点自动选择全部后代和附件；右侧附件支持多选导出。\n"
            "左侧 Ctrl/Shift 多选后右键导出项目包；拖入 .rwp 文件还原并打开。",
            parent=self.root)

    def install_drop(self):
        self.drop_regions=[]
        self.drop_exclusion=None
        self.package_drop_bounds=None
        self.native_drop_events=queue.Queue()
        self.pending_drop_hover=None
        if os.name!="nt":return
        from ctypes import wintypes
        user=ctypes.windll.user32
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
        user.GetAncestor.restype=wintypes.HWND
        self.root.update_idletasks()
        handles=[user.GetAncestor(self.root.winfo_id(),2),self.root.winfo_id(),
                 self.canvas.winfo_id(),self.outline.winfo_id(),self.attach_tree.winfo_id(),self.project_tree.winfo_id()]
        from native_drop import NativeFileDrop
        self.native_drop=NativeFileDrop(handles,self.native_hover,self.receive_ole_drop,
            lambda:setattr(self,"pending_drop_hover",None),
            lambda e:self.native_drop_events.put(("error",str(e))))
        self.root.bind("<Configure>",lambda e:self.root.after_idle(self.refresh_drop_regions),add="+")
        self.refresh_drop_regions()
        self.root.after(30,self.poll_drop_events)

    def refresh_drop_regions(self):
        if not hasattr(self,"drop_regions"):return
        regions=[]
        x,y=self.root.winfo_rootx(),self.root.winfo_rooty()
        self.package_drop_bounds=(x,y,x+self.root.winfo_width(),y+self.root.winfo_height())
        if self.ws and self.map_id:
            if self.view.get()=="map" and self.canvas.winfo_viewable():
                sx=self.canvas.winfo_rootx()-self.canvas.canvasx(0)
                sy=self.canvas.winfo_rooty()-self.canvas.canvasy(0)
                viewport=(self.canvas.winfo_rootx(),self.canvas.winfo_rooty(),
                          self.canvas.winfo_rootx()+self.canvas.winfo_width(),
                          self.canvas.winfo_rooty()+self.canvas.winfo_height())
                for i,(x1,y1,x2,y2) in self.boxes.items():
                    box=(max(viewport[0],sx+x1),max(viewport[1],sy+y1),
                         min(viewport[2],sx+x2),min(viewport[3],sy+y2))
                    if box[2]>box[0] and box[3]>box[1]:regions.append((("node",i),box))
            elif self.outline.winfo_viewable():
                for i in self.outline_ids:
                    box=self.outline.bbox(i)
                    if box:
                        x,y,w,h=box
                        sx,sy=self.outline.winfo_rootx(),self.outline.winfo_rooty()
                        regions.append((("node",i),(sx+x,sy+y,sx+x+w,sy+y+h)))
            tree=self.attach_tree
            if tree.winfo_viewable() and self.focus_node:
                x,y=tree.winfo_rootx(),tree.winfo_rooty()
                regions.append((("attachment",self.focus_node),(x,y,x+tree.winfo_width(),y+tree.winfo_height())))
        self.drop_regions=regions
        if self.overview.winfo_viewable():
            x,y=self.overview.winfo_rootx(),self.overview.winfo_rooty()
            self.drop_exclusion=(x,y,x+self.overview.winfo_width(),y+self.overview.winfo_height())
        else:self.drop_exclusion=None

    def outline_scrolled(self,*values):
        self.outline_scroll.set(*values)
        if hasattr(self,"drop_regions"):
            self.root.after_idle(self.refresh_drop_regions)

    def native_location(self,sx,sy,paths=None):
        if self.busy:return None
        if paths is None:
            receiver=getattr(self,"native_drop",None)
            paths=receiver.target.paths if receiver else []
        bounds=self.package_drop_bounds
        if (len(paths)==1 and Path(paths[0]).suffix.lower()==".rwp" and bounds
                and bounds[0]<=sx<=bounds[2] and bounds[1]<=sy<=bounds[3]):
            return ("package",None)
        if not self.ws:return None
        exclude=self.drop_exclusion
        if exclude and exclude[0]<=sx<=exclude[2] and exclude[1]<=sy<=exclude[3]:return None
        return next((location for location,(x1,y1,x2,y2) in self.drop_regions
                     if x1<=sx<=x2 and y1<=sy<=y2),None)

    def native_hover(self,sx,sy):
        location=self.native_location(sx,sy)
        self.pending_drop_hover=location
        return bool(location)

    def poll_drop_events(self):
        # OLE callbacks read Python snapshots; Tk updates run in its event loop.
        if self.pending_drop_hover!=getattr(self,"drop_highlight",None):
            self.canvas.delete("external-drop")
            self.drop_highlight=self.pending_drop_hover
            if self.drop_highlight:
                kind,node=self.drop_highlight
                if kind=="node" and self.view.get()=="map" and node in self.boxes:
                    box=self.boxes[node]
                    self.rounded_box((box[0]-4,box[1]-4,box[2]+4,box[3]+4),"",self.theme["accent"],3,("external-drop",))
                self.status.set("松开鼠标：还原并打开项目包" if kind=="package" else "松开鼠标：复制文件并创建附件子节点" if kind=="node" else "松开鼠标：归档到当前节点")
        while not self.native_drop_events.empty():
            event=self.native_drop_events.get_nowait()
            if event[0]=="drop":self.accept_drop(event[1],event[2])
            else:self.status.set("文件拖放："+event[1])
        self.root.after(30,self.poll_drop_events)

    def drop_location(self,sx,sy):
        if not self.ws or self.busy or not self.map_id:return None
        if (self.overview.winfo_viewable() and
            self.overview.winfo_rootx()<=sx<self.overview.winfo_rootx()+self.overview.winfo_width() and
            self.overview.winfo_rooty()<=sy<self.overview.winfo_rooty()+self.overview.winfo_height()):return None
        for surface in (self.canvas,self.outline):
            if (surface.winfo_viewable() and
                surface.winfo_rootx()<=sx<surface.winfo_rootx()+surface.winfo_width() and
                surface.winfo_rooty()<=sy<surface.winfo_rooty()+surface.winfo_height()):
                px,py=sx-surface.winfo_rootx(),sy-surface.winfo_rooty()
                node=self.node_at(px,py) if surface==self.canvas else self.outline.identify_row(py)
                if node:return ("node",node)
                return None
        tree=self.attach_tree
        if tree.winfo_viewable() and tree.winfo_rootx()<=sx<tree.winfo_rootx()+tree.winfo_width() and tree.winfo_rooty()<=sy<tree.winfo_rooty()+tree.winfo_height() and self.focus_node:
            return ("attachment",self.focus_node)
        return None

    def receive_ole_drop(self,paths,sx,sy):
        location=self.native_location(sx,sy,paths)
        if location:self.native_drop_events.put(("drop",paths,location))

    def accept_drop(self,paths,location):
        packages=[p for p in paths if Path(p).suffix.lower()==".rwp"]
        if packages:
            if len(paths)!=1:
                self.status.set("请一次拖入一个项目包")
                return
            self.open_project_package(packages[0])
            return
        if not self.guard() or location[1] not in self.ws.data["nodes"]:return
        self.finish_inline()
        self.select_node(location[1])
        self.import_files(paths=paths,file_nodes=location[0]=="node")

    def handle_drop(self,paths,widget,x,y):
        if any(Path(p).suffix.lower()==".rwp" for p in paths):
            self.accept_drop(paths,("package",None))
            return
        sx,sy=widget.winfo_rootx()+x,widget.winfo_rooty()+y
        location=self.drop_location(sx,sy)
        if location:self.accept_drop(paths,location)
        else:self.status.set("请把文件拖到目标节点框内")

    def close(self):
        if self.busy:
            self.status.set("请等待文件操作完成后关闭项目")
            return
        if not self.prepare_to_leave("关闭项目",always=True):return
        if self.html_bridge:
            self.html_bridge.close()
            self.html_bridge=None
        if self.ws:self.ws.close()
        if os.name=="nt" and getattr(self,"native_drop",None):
            self.native_drop.close();self.native_drop=None
        self.root.destroy()


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--workspace")
    args=parser.parse_args()
    if os.name=="nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root=tk.Tk()
    app=App(root,args.workspace)
    root.mainloop()

if __name__=="__main__":
    main()
