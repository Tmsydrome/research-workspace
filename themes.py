"""Research Workspace visual themes, version 1.0.0."""
from tkinter import ttk

THEMES = {
    "ocean":{"name":"深蓝","ui":"#111d2e","panel":"#1b2c43","canvas":"#13243a","outline":"#13243a",
             "border":"#2d405a","text":"#edf4fc","muted":"#95a9c1","accent":"#078077",
             "branch":"#439dd3","node":"#20649a","grid":"#1c304a","selection":"#125d66",
             "rainbow":["#21b9aa","#439dd3","#439dd3","#439dd3","#ca9861"]},
    "forest":{"name":"青绿","ui":"#112825","panel":"#193c35","canvas":"#102f29","outline":"#102f29",
              "border":"#31564b","text":"#ecf7f1","muted":"#9db9af","accent":"#16b79e",
              "branch":"#5ebba4","node":"#21765e","grid":"#193e35","selection":"#21584b",
              "rainbow":["#16b79e","#6ba9d0","#c5af73","#ae91c3","#d18e8b"]},
    "paper":{"name":"浅灰","ui":"#edf1f5","panel":"#ffffff","canvas":"#f7f9fc","outline":"#f7f9fc",
             "border":"#cfd9e4","text":"#24354a","muted":"#65788f","accent":"#087f7a",
             "branch":"#4b86b5","node":"#e0ecf7","grid":"#e8eef4","selection":"#d7eeec",
             "rainbow":["#087f7a","#4b86b5","#8b75b6","#b68950","#66956b"]},
    "warm":{"name":"暖棕","ui":"#2a211d","panel":"#3c2e26","canvas":"#31251f","outline":"#31251f",
            "border":"#615044","text":"#f5eee5","muted":"#c0ac99","accent":"#cd9b68",
            "branch":"#c79e78","node":"#775439","grid":"#3c2e26","selection":"#624530",
            "rainbow":["#c79e78","#99ada2","#b49dc4","#ce9390","#b2ba86"]},
    "plum":{"name":"暮紫","ui":"#211c2e","panel":"#302640","canvas":"#281d3b","outline":"#281d3b",
             "border":"#514461","text":"#f1edf6","muted":"#b3a7c4","accent":"#c778b3",
             "branch":"#cd6b9f","node":"#653d67","grid":"#342747","selection":"#57405e",
             "rainbow":["#cd6b9f","#6cbcc1","#d9ac62","#9395e3","#8dbd8b"]},
}
DEFAULT_STYLE={"background":"#e8efff","foreground":"#172947"}
NODE_PRESETS={"青绿":("#0d706e","#ffffff"),"红色":("#df2a33","#ffffff"),
              "石墨":("#555861","#ffffff"),"金色":("#f2c76c","#2c2310")}

def configure_style(style, theme):
    p=theme
    style.theme_use("clam")
    style.configure(".",background=p["ui"],foreground=p["text"],
                    font=("Microsoft YaHei UI",10))
    style.configure("TFrame",background=p["ui"])
    style.configure("TLabel",background=p["ui"],foreground=p["text"])
    style.configure("Muted.TLabel",foreground=p["muted"])
    style.configure("Heading.TLabel",font=("Microsoft YaHei UI",11,"bold"))
    style.configure("TButton",background=p["panel"],foreground=p["text"],padding=(7,4),
                    borderwidth=1,lightcolor=p["panel"],darkcolor=p["panel"],bordercolor=p["border"],width=0)
    style.map("TButton",background=[("pressed",p["selection"]),("active",p["selection"])],
              foreground=[("disabled",p["muted"])])
    style.configure("TMenubutton",background=p["ui"],foreground=p["text"],padding=(8,3),
                    borderwidth=0,arrowcolor=p["muted"],width=0)
    style.map("TMenubutton",background=[("active",p["panel"])])
    style.configure("TEntry",fieldbackground=p["panel"],foreground=p["text"],
                    insertcolor=p["text"],bordercolor=p["border"],lightcolor=p["panel"],darkcolor=p["panel"])
    style.map("TEntry",fieldbackground=[("disabled",p["ui"])],foreground=[("disabled",p["muted"])])
    style.configure("TCombobox",fieldbackground=p["panel"],background=p["panel"],foreground=p["text"],
                    arrowcolor=p["text"],bordercolor=p["border"],lightcolor=p["panel"],darkcolor=p["panel"])
    style.map("TCombobox",fieldbackground=[("readonly",p["panel"])],foreground=[("readonly",p["text"])])
    for name in ("TCheckbutton","TRadiobutton"):
        style.configure(name,background=p["ui"],foreground=p["text"],indicatorbackground=p["panel"],
                        indicatorforeground=p["text"],indicatormargin=4)
        style.map(name,background=[("active",p["panel"])])
    style.layout("Segment.TRadiobutton",style.layout("TButton"))
    style.configure("Segment.TRadiobutton",background=p["ui"],foreground=p["muted"],
                    padding=(12,5),borderwidth=0,width=0)
    style.map("Segment.TRadiobutton",background=[("selected",p["border"]),("active",p["panel"])],
              foreground=[("selected",p["text"])])
    style.configure("Treeview",background=p["panel"],fieldbackground=p["panel"],
                    foreground=p["text"],bordercolor=p["panel"],lightcolor=p["panel"],
                    darkcolor=p["panel"],borderwidth=0,rowheight=40)
    style.map("Treeview",background=[("selected",p["accent"])],foreground=[("selected",p["text"])])
    style.configure("Treeview.Heading",background=p["ui"],foreground=p["muted"],
                    bordercolor=p["border"],relief="flat")
    style.configure("Outline.Treeview",background=p["outline"],fieldbackground=p["outline"],
                    rowheight=42,font=("Microsoft YaHei UI",11))
    style.configure("Outline.TFrame",background=p["outline"])
    style.configure("OutlineTitle.TLabel",background=p["outline"],foreground=p["text"],
                    font=("Microsoft YaHei UI",20,"bold"))
    style.configure("OutlineMeta.TLabel",background=p["outline"],foreground=p["muted"])
    style.configure("TNotebook",background=p["ui"],borderwidth=0,
                    bordercolor=p["ui"],lightcolor=p["ui"],darkcolor=p["ui"])
    style.configure("TNotebook.Tab",background=p["panel"],foreground=p["muted"],padding=(13,8),bordercolor=p["border"],lightcolor=p["panel"],darkcolor=p["panel"])
    style.map("TNotebook.Tab",background=[("selected",p["border"])],foreground=[("selected",p["text"])])
    for name in ("Vertical.TScrollbar","Horizontal.TScrollbar"):
        style.configure(name,background=p["border"],troughcolor=p["ui"],arrowcolor=p["muted"],
                        bordercolor=p["ui"],lightcolor=p["border"],darkcolor=p["border"],borderwidth=0)
        style.map(name,background=[("active",p["muted"])])
    style.configure("TSeparator",background=p["border"])
    style.configure("Card.TFrame",background=p["panel"])
    style.configure("Card.TLabel",background=p["panel"],foreground=p["text"])
    style.configure("CardHeading.TLabel",background=p["panel"],foreground=p["text"],
                    font=("Microsoft YaHei UI",11,"bold"))
    style.configure("CardMuted.TLabel",background=p["panel"],foreground=p["muted"])
    style.configure("Card.TCheckbutton",background=p["panel"],foreground=p["text"])
    toggle="toggle."+p["name"]
    if toggle not in style.element_names():
        import tkinter as tk
        import math
        images=[]
        for selected in (False,True):
            image=tk.PhotoImage(master=style.master,width=30,height=18)
            rows=[]
            for y in range(18):
                colors=[]
                for x in range(30):
                    edge_x=max(8,min(21,x))
                    inside=(x-edge_x)**2+(y-8.5)**2<=8**2
                    knob=(x-(21 if selected else 8))**2+(y-8.5)**2<=6.2**2
                    colors.append(p["text"] if knob else p["accent"] if inside and selected else p["border"] if inside else p["panel"])
                rows.append("{"+ " ".join(colors)+"}")
            image.put(" ".join(rows))
            images.append(image)
        if not hasattr(style,"toggle_images"): style.toggle_images=[]
        style.toggle_images.extend(images)
        style.element_create(toggle,"image",images[0],("selected",images[1]),sticky="w")
    style.layout("Card.TCheckbutton",[("Checkbutton.padding",{"sticky":"nsew","children":[
        (toggle,{"side":"left","sticky":"w"}),("Checkbutton.focus",{"side":"left","sticky":"w","children":[
            ("Checkbutton.label",{"sticky":"w"})]})]})])
    style.configure("Card.TCheckbutton",padding=(0,2),indicatormargin=(0,0,8,0))

    style.map("Card.TCheckbutton",background=[("active",p["panel"])])
    style.configure("Project.Treeview",background=p["ui"],fieldbackground=p["ui"],rowheight=42)
    style.map("Project.Treeview",background=[("selected",p["accent"])],
              foreground=[("selected","#ffffff")])

    rounded_button(style,"TButton",p)
    rounded_button(style,"Accent.TButton",p,p["accent"],"#ffffff")
    rounded_button(style,"Panel.TFrame",p)
    style.layout("Panel.TFrame",[("rounded.Panel.TFrame."+p["name"],{"sticky":"nsew"})])
    rounded_button(style,"Segment.TRadiobutton",p)
    for label,(bg,fg) in NODE_PRESETS.items():
        rounded_button(style,label+".TButton",p,bg,fg)

def node_colors(style, theme):
    custom=style.get("custom",False) or any(style.get(k)!=v for k,v in DEFAULT_STYLE.items())
    return (style["background"],style["foreground"],True) if custom else (theme["canvas"],theme["text"],False)

def rounded_button(style,name,palette,bg=None,fg=None):
    import tkinter as tk
    import math
    p=palette
    bg=bg or p["panel"]
    fg=fg or p["text"]
    element="rounded."+name+"."+p["name"]
    if element not in style.element_names():
        images=[]
        hover=bg if bg!=p["panel"] else p["selection"]
        selected=p["accent"] if name=="Segment.TRadiobutton" else hover
        for fill,edge in ((bg,p["border"]),(hover,p["accent"]),(selected,p["accent"]),(bg,p["accent"])):
            size,radius=28,8
            rows=[]
            for y in range(size):
                pixels=[]
                for x in range(size):
                    cx=max(radius,min(size-radius-1,x))
                    cy=max(radius,min(size-radius-1,y))
                    distance=math.hypot(x-cx,y-cy)
                    pixels.append(p["ui"] if distance>radius else edge if distance>radius-1.2 or x in (0,size-1) or y in (0,size-1) else fill)
                rows.append("{"+ " ".join(pixels)+"}")
            photo=tk.PhotoImage(master=style.master,width=size,height=size)
            photo.put(" ".join(rows))
            images.append(photo)
        if not hasattr(style,"rounded_images"):
            style.rounded_images=[]
        style.rounded_images.extend(images)
        style.element_create(element,"image",images[0],("pressed",images[2]),("selected",images[2]),("active",images[1]),("focus",images[3]),border=8,sticky="nsew")
    style.layout(name,[(element,{"sticky":"nsew","children":[("Button.padding",{"sticky":"nsew","children":[("Button.label",{"sticky":"nsew"})]})]})])
    style.configure(name,padding=(8,4),foreground=fg,width=0)
    style.map(name,foreground=[("disabled",p["muted"]),("selected","#ffffff")])
