"""Finalize public release artifacts, version 1.0.0."""
import hashlib,json,os,zipfile
from pathlib import Path

VERSION="1.0.0"
BASE=Path(__file__).resolve().parent
PORTABLE=BASE/"dist"/("v"+VERSION+"_Research_Workspace_Portable")
SOURCE_FILES=["app.py","workspace.py","themes.py","html_editor.py","native_drop.py",
    "test_node_flow.py","test_project_flow.py","test_package_flow.py","test_workspace.py",
    "build_portable.py","finalize_delivery.py","launcher.cs",".gitignore","VERSION",
    "README.md","CHANGELOG.md","THIRD_PARTY_NOTICES.md","LICENSE",
    "resources/v1.0.0_HTML修订批注工具.html","resources/github_avatar.png","resources/github_profile.json"]
PORTABLE_ROOT_FILES={"app.py","workspace.py","themes.py","html_editor.py","native_drop.py",
    "test_node_flow.py","test_project_flow.py","test_package_flow.py","test_workspace.py",
    "README.md","CHANGELOG.md","THIRD_PARTY_NOTICES.md","LICENSE","VERSION",
    "v"+VERSION+"_Research_Workspace.exe"}
RESOURCES={p for p in SOURCE_FILES if p.startswith("resources/")}
REPORTS=["test_results.json","node_flow_results.json","project_flow_results.json","package_flow_results.json","portable_results.json"]

def atomic_zip(output,files):
    temporary=output.with_name(output.name+".tmp")
    try:
        with zipfile.ZipFile(temporary,"x",zipfile.ZIP_DEFLATED) as archive:
            for path,name in files:archive.write(path,name)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip():raise ValueError("发布包校验失败")
        os.replace(temporary,output)
    finally:temporary.unlink(missing_ok=True)

def main():
    for name in REPORTS:
        report=json.loads((BASE/name).read_text(encoding="utf-8"))
        assert report["version"]==VERSION and report["failed"]==0,name
    assert (BASE/"VERSION").read_text().strip()==VERSION
    for name in SOURCE_FILES:
        assert (BASE/name).is_file(),name
    for name in ["app.py","workspace.py","themes.py","html_editor.py","native_drop.py",
                 "test_node_flow.py","test_project_flow.py","test_package_flow.py","test_workspace.py",
                 "VERSION","README.md","CHANGELOG.md","THIRD_PARTY_NOTICES.md","LICENSE"]+sorted(RESOURCES):
        assert (BASE/name).read_bytes()==(PORTABLE/name).read_bytes(),name
    files=[]
    for path in PORTABLE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:continue
        relative=path.relative_to(PORTABLE).as_posix()
        if path.name=="checksums.json" or path.name.endswith("_results.json"):continue
        if not (relative in PORTABLE_ROOT_FILES or relative in RESOURCES or
                relative.startswith("runtime/") or relative in {"source/build_portable.py","source/launcher.cs"}):
            raise ValueError("发布目录存在未列入清单的文件："+relative)
        files.append((path,relative))
    hashes={name:hashlib.sha256(path.read_bytes()).hexdigest() for path,name in files}
    (PORTABLE/"checksums.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
    files.append((PORTABLE/"checksums.json","checksums.json"))
    portable_zip=BASE/"dist"/("v"+VERSION+"_Research_Workspace_Portable.zip")
    atomic_zip(portable_zip,[(p,PORTABLE.name+"/"+name) for p,name in sorted(files,key=lambda item:item[1])])
    source_zip=BASE/"dist"/("v"+VERSION+"_Research_Workspace_Source.zip")
    prefix="v"+VERSION+"_Research_Workspace_Source/"
    atomic_zip(source_zip,[(BASE/name,prefix+name) for name in SOURCE_FILES])
    artifacts=[{"name":p.name,"size":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (portable_zip,source_zip,PORTABLE/("v"+VERSION+"_Research_Workspace.exe"))]
    checksum=BASE/"dist"/("v"+VERSION+"_Research_Workspace_SHA256SUMS.txt")
    checksum.write_text("".join(a["sha256"]+"  "+a["name"]+"\n" for a in artifacts[:2]),encoding="utf-8")
    result={"version":VERSION,"zipValidation":"PASS","portableFiles":len(files),
            "sourceFiles":len(SOURCE_FILES),"artifacts":artifacts}
    (BASE/"delivery_results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
