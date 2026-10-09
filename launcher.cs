// Research Workspace portable launcher, version 1.0.0.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Research Workspace")]
[assembly: System.Reflection.AssemblyProduct("Research Workspace")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.0.0")]
class Launcher {
    [STAThread]
    static void Main(string[] args) {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        string app = Path.Combine(root, "app.py");
        try {
            if (!File.Exists(python) || !File.Exists(app))
                throw new IOException("请完整解压便携包，保留 runtime 目录与 app.py。");
            var start = new ProcessStartInfo(python);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.Arguments = "-I \"" + app + "\"";
            for (int i = 0; i < args.Length; i++) {
                if (args[i] == "--workspace" && i + 1 < args.Length) {
                    start.Arguments += " --workspace \"" + args[++i].Replace("\"", "") + "\"";
                }
            }
            Process.Start(start);
        } catch (Exception e) {
            MessageBox.Show(e.Message, "Research Workspace v1.0.0",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
