' Launches start.bat with no visible console window (window style 0).
' Double-click this instead of start.bat for a fully silent start.
Option Explicit
Dim shell, fso, repoDir
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
repoDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = repoDir
' 0 = hidden; False = do not wait (Python keeps running after this script exits)
shell.Run "cmd /c """ & repoDir & "\start.bat""", 0, False
