"""Windows Explorer OLE file drop receiver, version 1.0.0."""
import ctypes
import uuid
import os,json
from ctypes import wintypes

HRESULT=ctypes.c_long
DWORD=wintypes.DWORD
PVOID=ctypes.c_void_p
CALL=ctypes.WINFUNCTYPE

class POINTL(ctypes.Structure):
    _fields_=[("x",wintypes.LONG),("y",wintypes.LONG)]

class FORMATETC(ctypes.Structure):
    _fields_=[("cfFormat",wintypes.WORD),("ptd",PVOID),("dwAspect",DWORD),
              ("lindex",wintypes.LONG),("tymed",DWORD)]

class STGMEDIUM(ctypes.Structure):
    _fields_=[("tymed",DWORD),("hGlobal",PVOID),("pUnkForRelease",PVOID)]

class COMObject(ctypes.Structure):
    _fields_=[("vtable",ctypes.POINTER(PVOID))]

def method(obj,index,result,*arguments):
    table=ctypes.cast(obj,ctypes.POINTER(COMObject)).contents.vtable
    return CALL(result,PVOID,*arguments)(table[index])

def files_from_object(obj):
    medium=STGMEDIUM()
    form=FORMATETC(15,None,1,-1,1)  # CF_HDROP, DVASPECT_CONTENT, TYMED_HGLOBAL.
    get=method(obj,3,HRESULT,ctypes.POINTER(FORMATETC),ctypes.POINTER(STGMEDIUM))
    if get(obj,ctypes.byref(form),ctypes.byref(medium))<0:
        return []
    try:
        shell=ctypes.windll.shell32
        shell.DragQueryFileW.argtypes=[PVOID,wintypes.UINT,wintypes.LPWSTR,wintypes.UINT]
        paths=[]
        for i in range(shell.DragQueryFileW(medium.hGlobal,0xffffffff,None,0)):
            n=shell.DragQueryFileW(medium.hGlobal,i,None,0)
            name=ctypes.create_unicode_buffer(n+1)
            shell.DragQueryFileW(medium.hGlobal,i,name,n+1)
            paths.append(name.value)
        return paths
    finally:
        ole=ctypes.windll.ole32
        ole.ReleaseStgMedium.argtypes=[ctypes.POINTER(STGMEDIUM)]
        ole.ReleaseStgMedium(ctypes.byref(medium))

class FileDropTarget:
    def __init__(self,hover,drop,leave,error):
        self.hover,self.drop,self.leave,self.error=hover,drop,leave,error
        self.paths=[]
        self.refs=1
        supported={uuid.UUID(x).bytes_le for x in (
            "00000000-0000-0000-C000-000000000046",
            "00000122-0000-0000-C000-000000000046")}
        def query(this,iid,out):
            if ctypes.string_at(iid,16) in supported:
                out[0]=ctypes.cast(ctypes.pointer(self.obj),PVOID)
                self.refs+=1
                return 0
            out[0]=None
            return -2147467262
        def add(this):
            self.refs+=1
            return self.refs
        def release(this):
            self.refs=max(0,self.refs-1)
            return self.refs
        def trace(event,**values):
            path=os.environ.get("RESEARCH_WORKSPACE_DROP_TRACE")
            if path:
                try:
                    with open(path,"a",encoding="utf-8") as f:
                        f.write(json.dumps({"event":event,**values},ensure_ascii=False)+"\n")
                except OSError:
                    pass
        def update(point,effect):
            effect[0]=1 if self.paths and self.hover(point.x,point.y) else 0
        def enter(this,data,keys,point,effect):
            try:
                self.paths=files_from_object(data)
                update(point,effect)
                trace("enter",paths=self.paths,x=point.x,y=point.y,effect=int(effect[0]))
            except Exception as e:
                effect[0]=0;self.error(e)
            return 0
        def over(this,keys,point,effect):
            try:
                update(point,effect)
                trace("over",x=point.x,y=point.y,effect=int(effect[0]))
            except Exception as e:
                effect[0]=0;self.error(e)
            return 0
        def leave(this):
            trace("leave")
            self.paths=[];self.leave()
            return 0
        def drop(this,data,keys,point,effect):
            try:
                paths=files_from_object(data)
                accepted=bool(paths) and self.hover(point.x,point.y)
                effect[0]=1 if accepted else 0
                trace("drop",paths=paths,x=point.x,y=point.y,effect=int(effect[0]))
                if accepted:self.drop(paths,point.x,point.y)
            except Exception as e:
                effect[0]=0;self.error(e)
            finally:
                self.paths=[];self.leave()
            return 0
        signatures=[
            (HRESULT,[PVOID,PVOID,ctypes.POINTER(PVOID)],query),
            (wintypes.ULONG,[PVOID],add),(wintypes.ULONG,[PVOID],release),
            (HRESULT,[PVOID,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD)],enter),
            (HRESULT,[PVOID,DWORD,POINTL,ctypes.POINTER(DWORD)],over),
            (HRESULT,[PVOID],leave),
            (HRESULT,[PVOID,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD)],drop)]
        self.callbacks=[CALL(restype,*args)(func) for restype,args,func in signatures]
        self.table=(PVOID*7)(*(ctypes.cast(f,PVOID).value for f in self.callbacks))
        self.obj=COMObject(ctypes.cast(self.table,ctypes.POINTER(PVOID)))

class NativeFileDrop:
    def __init__(self,handles,hover,drop,leave,error):
        self.ole=ctypes.windll.ole32
        self.ole.OleInitialize.argtypes=[PVOID]
        self.ole.OleInitialize.restype=HRESULT
        self.ole.RegisterDragDrop.argtypes=[wintypes.HWND,PVOID]
        self.ole.RegisterDragDrop.restype=HRESULT
        self.ole.RevokeDragDrop.argtypes=[wintypes.HWND]
        result=self.ole.OleInitialize(None)
        if result<0:raise OSError("OLE 初始化失败：0x%08X"%(result&0xffffffff))
        self.target=FileDropTarget(hover,drop,leave,error)
        self.handles=[]
        try:
            for handle in dict.fromkeys(handles):
                result=self.ole.RegisterDragDrop(handle,ctypes.byref(self.target.obj))
                if result<0:raise OSError("OLE 文件拖放注册失败：0x%08X"%(result&0xffffffff))
                self.handles.append(handle)
        except Exception:
            self.close();raise
    def close(self):
        for handle in self.handles:self.ole.RevokeDragDrop(handle)
        self.handles=[]
        self.ole.OleUninitialize()
