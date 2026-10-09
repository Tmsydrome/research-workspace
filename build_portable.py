"""Build the Windows portable distribution, version 1.0.0."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

VERSION = "1.0.0"
BASE = Path(__file__).resolve().parent
PYTHON = Path(sys.base_prefix)
OUTPUT = BASE / "dist" / ("v" + VERSION + "_Research_Workspace_Portable")
COMPILER = Path(os.environ.get("WINDIR",r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"

def build():
    if os.name != "nt" or not COMPILER.exists():
        raise SystemExit("构建需要 Windows 和系统 .NET Framework C# 编译器")
    if OUTPUT.exists():
        raise SystemExit("输出目录已存在；请另存现有构建，再重新打包")
    OUTPUT.mkdir(parents=True)
    runtime = OUTPUT / "runtime"
    runtime.mkdir()
    for name in ["pythonw.exe","python.exe","python3.dll","python312.dll","vcruntime140.dll","vcruntime140_1.dll"]:
        source=PYTHON/name
        if source.exists():
            shutil.copy2(source,runtime/name)
    shutil.copytree(PYTHON/"DLLs",runtime/"DLLs",
        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(PYTHON/"tcl",runtime/"tcl")
    with zipfile.ZipFile(runtime/"python312.zip","x",zipfile.ZIP_DEFLATED) as archive:
        lib=PYTHON/"Lib"
        for directory,dirs,files in os.walk(lib):
            dirs[:]=[d for d in dirs if d not in {"site-packages","__pycache__","test","tests","idlelib","ensurepip","turtledemo"}]
            for name in files:
                if name.endswith(".py"):
                    p=Path(directory)/name
                    archive.write(p,p.relative_to(lib).as_posix())
    # tkinter loads Tcl scripts and a filesystem package path, so keep it unpacked.
    shutil.copytree(PYTHON/"Lib/tkinter",runtime/"Lib/tkinter",
        ignore=shutil.ignore_patterns("__pycache__"))
    (runtime/"python312._pth").write_text("python312.zip\nDLLs\nLib\n..\n",encoding="ascii")
    for name in ["app.py","workspace.py","themes.py","html_editor.py","native_drop.py",
                 "test_node_flow.py","test_project_flow.py","test_package_flow.py","test_workspace.py","README.md","CHANGELOG.md","THIRD_PARTY_NOTICES.md","LICENSE","VERSION"]:
        if (BASE/name).exists():
            shutil.copy2(BASE/name,OUTPUT/name)
    (OUTPUT/"resources").mkdir()
    for name in ["v1.0.0_HTML修订批注工具.html","github_avatar.png","github_profile.json"]:
        shutil.copy2(BASE/"resources"/name,OUTPUT/"resources"/name)
    for license_path in [PYTHON/"LICENSE.txt",PYTHON/"LICENSE"]:
        if license_path.exists():
            shutil.copy2(license_path,runtime/"LICENSE.txt")
            break
    launcher=BASE/"launcher.cs"
    executable=OUTPUT/("v"+VERSION+"_Research_Workspace.exe")
    subprocess.run([str(COMPILER),"/nologo","/target:winexe","/platform:x64",
                    "/out:"+str(executable),"/reference:System.Windows.Forms.dll",str(launcher)],
                   check=True)
    subprocess.run([str(runtime/"python.exe"),"-I","-c",
        "import tkinter, json, zipfile; import workspace; print('Runtime', workspace.VERSION, tkinter.TkVersion)"],
        cwd=OUTPUT,check=True)
    source_dir=OUTPUT/"source"
    source_dir.mkdir()
    for name in ["build_portable.py","launcher.cs"]:
        shutil.copy2(BASE/name,source_dir/name)
    hashes={p.relative_to(OUTPUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in OUTPUT.rglob("*") if p.is_file()}
    (OUTPUT/"checksums.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
    package=Path(str(OUTPUT)+".zip")
    with zipfile.ZipFile(package,"x",zipfile.ZIP_DEFLATED) as archive:
        for p in OUTPUT.rglob("*"):
            if p.is_file():
                archive.write(p,OUTPUT.name+"/"+p.relative_to(OUTPUT).as_posix())
    print(json.dumps({"version":VERSION,"exe":str(executable),"zip":str(package),
                      "bytes":package.stat().st_size},ensure_ascii=False))
if __name__=="__main__":
    build()
