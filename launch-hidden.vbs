Option Explicit

Dim shell, fileSystem, projectRoot, runner, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
runner = fileSystem.BuildPath(projectRoot, "run-background.ps1")
command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & runner & """"

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
